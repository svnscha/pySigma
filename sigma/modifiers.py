from abc import ABC, abstractmethod
from typing import ClassVar, Union, List, Sequence, Dict, Type, get_origin, get_args, get_type_hints
from collections.abc import Sequence as SequenceABC
from base64 import b64encode
from sigma.types import SigmaType, SigmaString, SigmaNumber, SpecialChars, SigmaRegularExpression, SigmaCompareExpression
from sigma.conditions import ConditionAND
from sigma.exceptions import SigmaTypeError, SigmaValueError

### Base Classes ###
class SigmaModifier(ABC):
    """Base class for all Sigma modifiers"""
    detection_item : "SigmaDetectionItem"
    applied_modifiers : List["SigmaModifier"]

    def __init__(self, detection_item : "SigmaDetectionItem", applied_modifiers : List["SigmaModifier"]):
        self.detection_item = detection_item
        self.applied_modifiers = applied_modifiers

    def type_check(self, val : Union[SigmaType, Sequence[SigmaType]], explicit_type=None) -> bool:
        th = explicit_type or get_type_hints(self.modify)["val"]      # get type annotation from val parameter of apply method or explicit_type parameter
        to = get_origin(th)                         # get possible generic type of type hint
        if to is None:                              # Plain type in annotation
            return isinstance(val, th)
        elif to is Union:                           # type hint is Union of multiple types, check if val is one of them
            for t in get_args(th):
                if isinstance(val, t):
                    return True
            return False
        elif to is SequenceABC:                     # type hint is sequence
            inner_type = get_args(th)[0]
            return all([
                self.type_check(item, explicit_type=inner_type)
                for item in val
            ])

    @abstractmethod
    def modify(self, val : Union[SigmaType, Sequence[SigmaType]]) -> Union[SigmaType, List[SigmaType]]:
        """This method should be overridden with the modifier implementation."""

    def apply(self, val : Union[SigmaType, Sequence[SigmaType]]) -> List[SigmaType]:
        """
        Modifier entry point containing the default operations:
        * Type checking
        * Ensure returned value is a list
        """
        if not self.type_check(val):
            raise SigmaTypeError(f"Modifier {self.__class__.__name__} incompatible to value type of '{ val }'")
        r = self.modify(val)
        if isinstance(r, List):
            return r
        else:
            return [r]

class SigmaValueModifier(SigmaModifier):
    """Base class for all modifiers that handle each value for the modifier scope separately"""
    @abstractmethod
    def modify(self, val : SigmaType) -> Union[SigmaType, List[SigmaType]]:
        """This method should be overridden with the modifier implementation."""

class SigmaListModifier(SigmaModifier):
    """Base class for all modifiers that handle all values for the modifier scope as a whole."""
    @abstractmethod
    def modify(self, val : Sequence[SigmaType]) -> Union[SigmaType, List[SigmaType]]:
        """This method should be overridden with the modifier implementation."""

### Modifier Implementations ###
class SigmaContainsModifier(SigmaValueModifier):
    def modify(self, val : SigmaString) -> SigmaString:
        if not val.startswith(SpecialChars.WILDCARD_MULTI):
            val = SpecialChars.WILDCARD_MULTI + val
        if not val.endswith(SpecialChars.WILDCARD_MULTI):
            val += SpecialChars.WILDCARD_MULTI
        return val

class SigmaStartswithModifier(SigmaValueModifier):
    def modify(self, val : SigmaString) -> SigmaString:
        if not val.endswith(SpecialChars.WILDCARD_MULTI):
            val += SpecialChars.WILDCARD_MULTI
        return val

class SigmaEndswithModifier(SigmaValueModifier):
    def modify(self, val : SigmaString) -> SigmaString:
        if not val.startswith(SpecialChars.WILDCARD_MULTI):
            val = SpecialChars.WILDCARD_MULTI + val
        return val

class SigmaBase64Modifier(SigmaValueModifier):
    def modify(self, val : SigmaString) -> SigmaString:
        if val.contains_special():
            raise SigmaValueError("Base64 encoding of strings with wildcards is not allowed")
        return SigmaString(b64encode(bytes(val)).decode())

class SigmaBase64OffsetModifier(SigmaValueModifier):
    start_offsets = (0, 2, 3)
    end_offsets = (None, -3, -2)

    def modify(self, val : SigmaString) -> List[SigmaString]:
        if val.contains_special():
            raise SigmaValueError("Base64 encoding of strings with wildcards is not allowed")
        return [
            SigmaString(b64encode(
                i * b' ' + bytes(val)
                )[
                    self.start_offsets[i]:
                    self.end_offsets[(len(val) + i) % 3]
                ].decode()
            )
            for i in range(3)
            ]

class SigmaWideModifier(SigmaValueModifier):
    def modify(self, val : SigmaString) -> SigmaString:
        r = list()
        for item in val.s:
            if isinstance(item, str):       # put 0x00 after each character by encoding it to utf-16le and decoding it as utf-8
                try:
                    r.append(item.encode("utf-16le").decode("utf-8"))
                except UnicodeDecodeError:         # this method only works for ascii characters
                    raise SigmaValueError(f"Wide modifier only allowed for ascii strings, input string '{str(val)}' isn't one")
            else:                           # just append special characters without further handling
                r.append(item)

        s = SigmaString()
        s.s = tuple(r)
        return(s)

class SigmaRegularExpressionModifier(SigmaValueModifier):
    def modify(self, val : SigmaString) -> SigmaRegularExpression:
        if len(self.applied_modifiers) > 0:
            raise SigmaValueError("Regular expression modifier only applicable to unmodified values")
        return SigmaRegularExpression(str(val))

class SigmaAllModifier(SigmaListModifier):
    def modify(self, val : Sequence[SigmaType]) -> List[SigmaType]:
        self.detection_item.value_linking = ConditionAND
        return val

class SigmaCompareModifier(SigmaValueModifier):
    """Base class for numeric comparison operator modifiers."""
    op : ClassVar[SigmaCompareExpression.CompareOperators]

    def modify(self, val : SigmaNumber) -> SigmaCompareExpression:
        return SigmaCompareExpression(val, self.op)

class SigmaLessThanModifier(SigmaCompareModifier):
    op : ClassVar[SigmaCompareExpression.CompareOperators] = SigmaCompareExpression.CompareOperators.LT

class SigmaLessThanEqualModifier(SigmaCompareModifier):
    op : ClassVar[SigmaCompareExpression.CompareOperators] = SigmaCompareExpression.CompareOperators.LTE

class SigmaGreaterThanModifier(SigmaCompareModifier):
    op : ClassVar[SigmaCompareExpression.CompareOperators] = SigmaCompareExpression.CompareOperators.GT

class SigmaGreaterThanEqualModifier(SigmaCompareModifier):
    op : ClassVar[SigmaCompareExpression.CompareOperators] = SigmaCompareExpression.CompareOperators.GTE

class SigmaExpandModifier(SigmaValueModifier):
    """
    Modifier for expansion of placeholders in values. It replaces placeholder strings (%something%)
    with stub objects that are later expanded to one or multiple strings or replaced with some SIEM
    specific list item or lookup by the processing pipeline.
    """
    def modify(self, val : SigmaString) -> SigmaString:
        return val.insert_placeholders()

# Mapping from modifier identifier strings to modifier classes
modifier_mapping : Dict[str, Type[SigmaModifier]] = {
    "contains"      : SigmaContainsModifier,
    "startswith"    : SigmaStartswithModifier,
    "endswith"      : SigmaEndswithModifier,
    "base64"        : SigmaBase64Modifier,
    "base64offset"  : SigmaBase64OffsetModifier,
    "wide"          : SigmaWideModifier,
    "re"            : SigmaRegularExpressionModifier,
    "all"           : SigmaAllModifier,
    "lt"            : SigmaLessThanModifier,
    "lte"           : SigmaLessThanEqualModifier,
    "gt"            : SigmaGreaterThanModifier,
    "gte"           : SigmaGreaterThanEqualModifier,
    "expand"        : SigmaExpandModifier,
}