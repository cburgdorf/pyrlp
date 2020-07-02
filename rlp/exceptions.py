from typing import Any, Optional


class RLPException(Exception):
    """Base class for exceptions raised by this package."""
    pass


class EncodingError(RLPException):
    """Exception raised if encoding fails.

    :ivar obj: the object that could not be encoded
    """

    def __init__(self, message: str, obj: Any) -> None:
        super(EncodingError, self).__init__(message)
        self.obj = obj


class DecodingError(RLPException):
    """Exception raised if decoding fails.

    :ivar rlp: the RLP string that could not be decoded
    """

    def __init__(self, message: str, rlp: bytes) -> None:
        super(DecodingError, self).__init__(message)
        self.rlp = rlp


class SerializationError(RLPException):
    """Exception raised if serialization fails.

    :ivar obj: the object that could not be serialized
    """

    def __init__(self, message: str, obj: Any) -> None:
        super(SerializationError, self).__init__(message)
        self.obj = obj


class ListSerializationError(SerializationError):
    """Exception raised if serialization by a :class:`sedes.List` fails.

    :ivar element_exception: the exception that occurred during the serialization of one of the
                             elements, or `None` if the error is unrelated to a specific element
    :ivar index: the index in the list that produced the error or `None` if the error is unrelated
                 to a specific element
    """

    def __init__(self,
                 message: str=None,
                 obj: Any=None,
                 element_exception:
                 Exception=None,
                 index: int=None):
        if message is None:
            assert index is not None
            assert element_exception is not None
            message = ('Serialization failed because of element at index {} '
                       '("{}")'.format(index, str(element_exception)))
        super(ListSerializationError, self).__init__(message, obj)
        self.index = index
        self.element_exception = element_exception


class ObjectSerializationError(SerializationError):
    """Exception raised if serialization of a :class:`sedes.Serializable` object fails.

    :ivar sedes: the :class:`sedes.Serializable` that failed
    :ivar list_exception: exception raised by the underlying list sedes, or `None` if no such
                          exception has been raised
    :ivar field: name of the field of the object that produced the error, or `None` if no field
                 responsible for the error
    """

    def __init__(self,
                 message: str=None,
                 obj: Any=None,
                 sedes: Any=None,
                 list_exception: ListSerializationError=None):
        if message is None:
            assert list_exception is not None
            if list_exception.element_exception is None:
                field = None
                message = ('Serialization failed because of underlying list '
                           '("{}")'.format(str(list_exception)))
            else:
                assert sedes is not None
                field = sedes._meta.field_names[list_exception.index]
                message = ('Serialization failed because of field {} '
                           '("{}")'.format(field, str(list_exception.element_exception)))
        else:
            field = None
        super(ObjectSerializationError, self).__init__(message, obj)
        self.field = field
        self.list_exception = list_exception


class DeserializationError(RLPException):
    """Exception raised if deserialization fails.

    :ivar serial: the decoded RLP string that could not be deserialized
    """

    def __init__(self, message: str, serial: Optional[bytes]) -> None:
        super(DeserializationError, self).__init__(message)
        self.serial = serial


class ListDeserializationError(DeserializationError):
    """Exception raised if deserialization by a :class:`sedes.List` fails.

    :ivar element_exception: the exception that occurred during the deserialization of one of the
                             elements, or `None` if the error is unrelated to a specific element
    :ivar index: the index in the list that produced the error or `None` if the error is unrelated
                 to a specific element
    """

    def __init__(self,
                 message: str=None,
                 serial: bytes=None,
                 element_exception: Exception=None,
                 index: int=None):
        if not message:
            assert index is not None
            assert element_exception is not None
            message = ('Deserialization failed because of element at index {} '
                       '("{}")'.format(index, str(element_exception)))
        super(ListDeserializationError, self).__init__(message, serial)
        self.index = index
        self.element_exception = element_exception


class ObjectDeserializationError(DeserializationError):
    """Exception raised if deserialization by a :class:`sedes.Serializable` fails.

    :ivar sedes: the :class:`sedes.Serializable` that failed
    :ivar list_exception: exception raised by the underlying list sedes, or `None` if no such
                          exception has been raised
    :ivar field: name of the field of the object that produced the error, or `None` if no field
                 responsible for the error
    """

    def __init__(self,
                 message: str=None,
                 serial: bytes=None,
                 sedes: Any=None,
                 list_exception: Optional[ListDeserializationError]=None):
        if not message:
            assert list_exception is not None
            if list_exception.element_exception is None:
                field = None
                message = ('Deserialization failed because of underlying list '
                           '("{}")'.format(str(list_exception)))
            else:
                assert sedes is not None
                field = sedes._meta.field_names[list_exception.index]
                message = ('Deserialization failed because of field {} '
                           '("{}")'.format(field, str(list_exception.element_exception)))
        super(ObjectDeserializationError, self).__init__(message, serial)
        self.sedes = sedes
        self.list_exception = list_exception
        self.field = field
