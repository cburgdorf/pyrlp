import abc
import collections
import copy
import enum
import re
from inspect import Traceback
from typing import Dict, Any, Hashable, Iterable, Tuple, Sequence, Type, Union, Optional

from eth_utils import (
    to_dict,
    to_set,
    to_tuple,
)

from rlp.exceptions import (
    ListSerializationError,
    ObjectSerializationError,
    ListDeserializationError,
    ObjectDeserializationError,
)

from .lists import (
    List,
)


class MetaBase:
    fields = None
    field_names = None
    field_attrs = None
    sedes = None


def _get_duplicates(values: Iterable[str]) -> Tuple[str, ...]:
    counts = collections.Counter(values)
    return tuple(
        item
        for item, num in counts.items()
        if num > 1
    )


def validate_args_and_kwargs(args: Any,
                             kwargs: Any,
                             arg_names: Sequence[str],
                             allow_missing: bool=False) -> None:
    duplicate_arg_names = _get_duplicates(arg_names)
    if duplicate_arg_names:
        raise TypeError("Duplicate argument names: {0}".format(sorted(duplicate_arg_names)))

    needed_kwargs = arg_names[len(args):]
    used_kwargs = set(arg_names[:len(args)])

    duplicate_kwargs = used_kwargs.intersection(kwargs.keys())
    if duplicate_kwargs:
        raise TypeError("Duplicate kwargs: {0}".format(sorted(duplicate_kwargs)))

    unknown_kwargs = set(kwargs.keys()).difference(arg_names)
    if unknown_kwargs:
        raise TypeError("Unknown kwargs: {0}".format(sorted(unknown_kwargs)))

    missing_kwargs = set(needed_kwargs).difference(kwargs.keys())
    if not allow_missing and missing_kwargs:
        raise TypeError("Missing kwargs: {0}".format(sorted(missing_kwargs)))


@to_tuple
def merge_kwargs_to_args(args: Any,
                         kwargs: Any,
                         arg_names: Sequence[str],
                         allow_missing: bool=False) -> Iterable[str]:
    validate_args_and_kwargs(args, kwargs, arg_names, allow_missing=allow_missing)

    needed_kwargs = arg_names[len(args):]

    yield from args
    for arg_name in needed_kwargs:
        yield kwargs[arg_name]


@to_dict
def merge_args_to_kwargs(args: Any,
                         kwargs: Any,
                         arg_names: Sequence[str],
                         allow_missing: bool = False) -> Iterable[Tuple[str, Any]]:
    validate_args_and_kwargs(args, kwargs, arg_names, allow_missing=allow_missing)

    yield from kwargs.items()
    for value, name in zip(args, arg_names):
        yield name, value


def _eq(left: Any, right: Any) -> bool:
    """
    Equality comparison that allows for equality between tuple and list types
    with equivalent elements.
    """
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(_eq(*pair) for pair in zip(left, right))
    else:
        return left == right  # type: ignore  # there's no Comparable protocol


class ChangesetState(enum.Enum):
    INITIALIZED = 'INITIALIZED'
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'


class ChangesetField:
    field: Optional[str] = None

    def __init__(self, field: str) -> None:
        self.field = field

    def __get__(self, instance: Any, type: Any=None) -> Any:
        if instance is None:
            return self
        elif instance.__state__ is not ChangesetState.OPEN:
            raise AttributeError("Changeset is not active.  Attribute access not allowed")
        else:
            try:
                return instance.__diff__[self.field]
            except KeyError:
                return getattr(instance.__original__, self.field)  # type: ignore

    def __set__(self, instance: Any, value: Any) -> None:
        if instance.__state__ is not ChangesetState.OPEN:
            raise AttributeError("Changeset is not active.  Attribute access not allowed")
        instance.__diff__[self.field] = value


class BaseChangeset:
    # reference to the original Serializable instance.
    __original__: Any = None
    # the state of this fieldset.  Initialized -> Open -> Closed
    __state__: Any = None
    # the field changes that have been made in this change
    __diff__: Any = None

    def __init__(self, obj: Any, changes: Any=None) -> None:
        self.__original__ = obj
        self.__state__ = ChangesetState.INITIALIZED
        self.__diff__ = changes or {}

    def commit(self) -> Any:
        obj = self.build_rlp()
        self.close()
        return obj

    def build_rlp(self) -> Any:
        if self.__state__ == ChangesetState.OPEN:
            field_kwargs = {
                name: self.__diff__.get(name, self.__original__[name])
                for name
                in self.__original__._meta.field_names
            }
            return type(self.__original__)(**field_kwargs)
        else:
            raise ValueError("Cannot open Changeset which is not in the OPEN state")

    def open(self) -> None:
        if self.__state__ == ChangesetState.INITIALIZED:
            self.__state__ = ChangesetState.OPEN
        else:
            raise ValueError("Cannot open Changeset which is not in the INITIALIZED state")

    def close(self) -> None:
        if self.__state__ == ChangesetState.OPEN:
            self.__state__ = ChangesetState.CLOSED
        else:
            raise ValueError("Cannot close Changeset which is not in the OPEN state")

    def __enter__(self) -> 'BaseChangeset':
        if self.__state__ == ChangesetState.INITIALIZED:
            self.open()
            return self
        else:
            raise ValueError("Cannot open Changeset which is not in the INITIALIZED state")

    def __exit__(self,
                 exc_type: Type[Exception],
                 exc_value: Exception,
                 traceback: Traceback) -> None:
        if self.__state__ == ChangesetState.OPEN:
            self.close()


def Changeset(obj: Any, changes: Any) -> Any:
    namespace = {
        name: ChangesetField(name)
        for name
        in obj._meta.field_names
    }
    cls = type(
        "{0}Changeset".format(obj.__class__.__name__),
        (BaseChangeset,),
        namespace,
    )
    return cls(obj, changes)


class BaseSerializable(collections.abc.Sequence[Any]):
    _meta: Any

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if kwargs:
            field_values = merge_kwargs_to_args(args, kwargs, self._meta.field_names)
        else:
            field_values = args

        if len(field_values) != len(self._meta.field_names):
            raise TypeError(
                'Argument count mismatch. expected {0} - got {1} - missing {2}'.format(
                    len(self._meta.field_names),
                    len(field_values),
                    ','.join(self._meta.field_names[len(field_values):]),
                )
            )

        for value, attr in zip(field_values, self._meta.field_attrs):
            setattr(self, attr, make_immutable(value))

    _cached_rlp = None

    def as_dict(self) -> Dict[Hashable, Any]:
        return dict(
            (field, value)
            for field, value
            in zip(self._meta.field_names, self)
        )

    def __iter__(self) -> Any:
        for attr in self._meta.field_attrs:
            yield getattr(self, attr)

    def __getitem__(self, idx: Union[int, str, slice]) -> Any:
        if isinstance(idx, int):
            attr = self._meta.field_attrs[idx]
            return getattr(self, attr)
        elif isinstance(idx, slice):
            field_slice = self._meta.field_attrs[idx]
            return tuple(getattr(self, field) for field in field_slice)
        elif isinstance(idx, str):
            return getattr(self, idx)
        else:
            raise IndexError("Unsupported type for __getitem__: {0}".format(type(idx)))

    def __len__(self) -> int:
        return len(self._meta.fields)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Serializable) and hash(self) == hash(other)

    def __getstate__(self) -> Any:
        state = self.__dict__.copy()
        # The hash() builtin is not stable across processes
        # (https://docs.python.org/3/reference/datamodel.html#object.__hash__), so we do this here
        # to ensure pickled instances don't carry the cached hash() as that may cause issues like
        # https://github.com/ethereum/py-evm/issues/1318
        state['_hash_cache'] = None
        return state

    _hash_cache = None

    def __hash__(self) -> int:
        if self._hash_cache is None:
            self._hash_cache = hash(tuple(self))

        return self._hash_cache

    def __repr__(self) -> str:
        keyword_args = tuple("{}={!r}".format(k, v) for k, v in self.as_dict().items())
        return "{}({})".format(
            type(self).__name__,
            ", ".join(keyword_args),
        )

    @classmethod
    def serialize(cls, obj: Any) -> Any:
        try:
            return cls._meta.sedes.serialize(obj)
        except ListSerializationError as e:
            raise ObjectSerializationError(obj=obj, sedes=cls, list_exception=e)

    @classmethod
    def deserialize(cls, serial: bytes, **extra_kwargs: Any) -> Any:
        try:
            values = cls._meta.sedes.deserialize(serial)
        except ListDeserializationError as e:
            raise ObjectDeserializationError(serial=serial, sedes=cls, list_exception=e)

        args_as_kwargs = merge_args_to_kwargs(values, {}, cls._meta.field_names)
        return cls(**args_as_kwargs, **extra_kwargs)

    def copy(self, *args: Any, **kwargs: Any) -> Any:
        missing_overrides = set(
            self._meta.field_names
        ).difference(
            kwargs.keys()
        ).difference(
            self._meta.field_names[:len(args)]
        )
        unchanged_kwargs = {
            key: copy.deepcopy(value)
            for key, value
            in self.as_dict().items()
            if key in missing_overrides
        }
        combined_kwargs = dict(**unchanged_kwargs, **kwargs)  # type: ignore #???
        all_kwargs = merge_args_to_kwargs(args, combined_kwargs, self._meta.field_names)
        return type(self)(**all_kwargs)

    def __copy__(self) -> Any:
        return self.copy()

    def __deepcopy__(self, *args: Any) -> Any:
        return self.copy()

    _in_mutable_context = False

    def build_changeset(self, *args: Any, **kwargs: Any) -> Any:
        args_as_kwargs = merge_args_to_kwargs(
            args,
            kwargs,
            self._meta.field_names,
            allow_missing=True,
        )
        return Changeset(self, changes=args_as_kwargs)


def make_immutable(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(make_immutable(item) for item in value)
    else:
        return value


@to_tuple
def _mk_field_attrs(field_names: Any, extra_namespace: Any) -> Iterable[str]:
    namespace = set(field_names).union(extra_namespace)
    for field in field_names:
        while True:
            field = '_' + field
            if field not in namespace:
                namespace.add(field)
                yield field
                break


def _mk_field_property(field: str, attr: str) -> Any:
    def field_fn_getter(self: Any) -> Any:
        return getattr(self, attr)

    def field_fn_setter(self: Any, value: Any) -> None:
        if not self._in_mutable_context:
            raise AttributeError("can't set attribute")
        setattr(self, attr, value)

    return property(field_fn_getter, field_fn_setter)


IDENTIFIER_REGEX = re.compile(r"^[^\d\W]\w*\Z", re.UNICODE)


def _is_valid_identifier(value: bool) -> bool:
    # Source: https://stackoverflow.com/questions/5474008/regular-expression-to-confirm-whether-a-string-is-a-valid-identifier-in-python  # noqa: E501
    if not isinstance(value, str):
        return False
    return bool(IDENTIFIER_REGEX.match(value))


@to_set
def _get_class_namespace(cls: Any) -> Iterable[Any]:
    if hasattr(cls, '__dict__'):
        yield from cls.__dict__.keys()
    if hasattr(cls, '__slots__'):
        yield from cls.__slots__


class SerializableBase(abc.ABCMeta):
    def __new__(cls, name: str, bases: Any, attrs: Any) -> Any:
        super_new = super(SerializableBase, cls).__new__

        serializable_bases = tuple(b for b in bases if isinstance(b, SerializableBase))
        has_multiple_serializable_parents = len(serializable_bases) > 1
        is_serializable_subclass = any(serializable_bases)
        declares_fields = 'fields' in attrs

        if not is_serializable_subclass:
            # If this is the original creation of the `Serializable` class,
            # just create the class.
            return super_new(cls, name, bases, attrs)
        elif not declares_fields:
            if has_multiple_serializable_parents:
                raise TypeError(
                    "Cannot create subclass from multiple parent `Serializable` "
                    "classes without explicit `fields` declaration."
                )
            else:
                # This is just a vanilla subclass of a `Serializable` parent class.
                parent_serializable = serializable_bases[0]

                if hasattr(parent_serializable, '_meta'):
                    fields = parent_serializable._meta.fields  # type: ignore
                else:
                    # This is a subclass of `Serializable` which has no
                    # `fields`, likely intended for further subclassing.
                    fields = ()
        else:
            # ensure that the `fields` property is a tuple of tuples to ensure
            # immutability.
            fields = tuple(tuple(field) for field in attrs.pop('fields'))

        # split the fields into names and sedes
        if fields:
            field_names, sedes = zip(*fields)
        else:
            field_names, sedes = (), ()

        # check that field names are unique
        duplicate_field_names = _get_duplicates(field_names)
        if duplicate_field_names:
            raise TypeError(
                "The following fields are duplicated in the `fields` "
                "declaration: "
                "{0}".format(",".join(sorted(duplicate_field_names)))
            )

        # check that field names are valid identifiers
        invalid_field_names = {
            field_name
            for field_name
            in field_names
            if not _is_valid_identifier(field_name)
        }
        if invalid_field_names:
            raise TypeError(
                "The following field names are not valid python identifiers: {0}".format(
                    ",".join("`{0}`".format(item) for item in sorted(invalid_field_names))
                )
            )

        # extract all of the fields from parent `Serializable` classes.
        parent_field_names = {
            field_name
            for base in serializable_bases if hasattr(base, '_meta')
            for field_name in base._meta.field_names  # type: ignore
        }

        # check that all fields from parent serializable classes are
        # represented on this class.
        missing_fields = parent_field_names.difference(field_names)
        if missing_fields:
            raise TypeError(
                "Subclasses of `Serializable` **must** contain a full superset "
                "of the fields defined in their parent classes.  The following "
                "fields are missing: "
                "{0}".format(",".join(sorted(missing_fields)))
            )

        # the actual field values are stored in separate *private* attributes.
        # This computes attribute names that don't conflict with other
        # attributes already present on the class.
        reserved_namespace = set(attrs.keys()).union(
            attr
            for base in bases
            for parent_cls in base.__mro__
            for attr in _get_class_namespace(parent_cls)
        )
        field_attrs = _mk_field_attrs(field_names, reserved_namespace)

        # construct the Meta object to store field information for the class
        meta_namespace = {
            'fields': fields,
            'field_attrs': field_attrs,
            'field_names': field_names,
            'sedes': List(sedes),
        }

        meta_base = attrs.pop('_meta', MetaBase)
        meta = type(
            'Meta',
            (meta_base,),
            meta_namespace,
        )
        attrs['_meta'] = meta

        # construct `property` attributes for read only access to the fields.
        field_props = tuple(
            (field, _mk_field_property(field, attr))
            for field, attr
            in zip(meta.field_names, meta.field_attrs)  # type: ignore
        )

        return super_new(
            cls,
            name,
            bases,
            dict(
                field_props +
                tuple(attrs.items())
            ),
        )


class Serializable(BaseSerializable, metaclass=SerializableBase):
    """
    The base class for serializable objects.
    """
    pass
