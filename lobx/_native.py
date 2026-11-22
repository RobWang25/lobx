"""
Conversions between lobx's Python types and the C++ core's integers.

The C++ core (lobx._core) only handles integers. Prices become whole units of
0.0001, and string IDs become integers assigned in first-seen order.

lobx._core is optional. It exists only after building the package with
`pip install -e .` on Python 3.10 or newer, so check AVAILABLE first.
"""
from decimal import Decimal
from typing import Dict, List

try:
    from . import _core
except ImportError:
    _core = None

AVAILABLE = _core is not None

PRICE_SCALE = 10_000  # Must match kPriceScale in cpp/include/lobx/types.hpp
MAX_ORDER_QUANTITY = 1_000_000_000  # Must match kMaxOrderQuantity
_INT64_MAX = 2**63 - 1


def price_to_units(price: Decimal) -> int:
    """
    Convert a price to C++ units, raising ValueError if it can't be represented.

    Prices must be positive, have at most 4 decimal places and fit in an int64.
    """
    units = Decimal(price) * PRICE_SCALE
    if units != units.to_integral_value():
        raise ValueError(f"Price {price} has more than 4 decimal places")
    units = int(units)
    if not 0 < units <= _INT64_MAX:
        raise ValueError(f"Price {price} is out of range")
    return units


def units_to_price(units: int) -> Decimal:
    """Convert C++ units back to a price, e.g. 1_002_500 -> Decimal('100.2500')."""
    return Decimal(units).scaleb(-4)


class IdMap:
    """
    Assigns each string ID a stable integer, starting from 0, and converts back.

    Entries are never removed, so a reused string always gets the same integer.
    """

    def __init__(self):
        self._numbers: Dict[str, int] = {}
        self._names: List[str] = []

    def number(self, name: str) -> int:
        """Return the integer for this name, assigning the next one if it's new."""
        number = self._numbers.get(name)
        if number is None:
            number = len(self._names)
            self._numbers[name] = number
            self._names.append(name)
        return number

    def lookup(self, name: str):
        """Return the integer for this name, or None if it hasn't been seen."""
        return self._numbers.get(name)

    def name(self, number: int) -> str:
        return self._names[number]

    def __len__(self) -> int:
        return len(self._names)
