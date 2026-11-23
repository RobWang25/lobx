"""
Conversions between lobx's Python types and the C++ core's integers.

The C++ core (lobx._core) only handles integers. Prices become whole units of
0.0001, timestamps become microseconds since 1970, and string IDs become integers.

lobx._core is optional. It exists only after building the package with
`pip install -e .` on Python 3.10 or newer, so check AVAILABLE first.
"""
from datetime import datetime, timedelta
from decimal import Context, Decimal, Inexact, InvalidOperation
from importlib import import_module
from typing import Dict, List

try:
    _core = import_module("._core", __package__)
except ModuleNotFoundError as error:
    if error.name != f"{__package__}._core":
        raise
    _core = None

AVAILABLE = _core is not None

_PRICE_DECIMALS = 4
PRICE_SCALE = 10**_PRICE_DECIMALS  # Must match kPriceScale in cpp/include/lobx/types.hpp
MAX_ORDER_QUANTITY = 1_000_000_000  # Must match kMaxOrderQuantity
_INT64_MAX = 2**63 - 1
_UNIT_DIGITS = len(str(_INT64_MAX))
_PRICE_TICK = Decimal(f"1e-{_PRICE_DECIMALS}")
_PRICE_CONTEXT = Context(prec=_UNIT_DIGITS, Emin=-_PRICE_DECIMALS, Emax=_UNIT_DIGITS - 1,
                         traps=[Inexact, InvalidOperation])


def units_to_price(units: int) -> Decimal:
    """Convert C++ units back to a price, e.g. 1_002_500 -> Decimal('100.2500')."""
    return Decimal(f"{units}e-{_PRICE_DECIMALS}")


_MAX_PRICE = units_to_price(_INT64_MAX)


def price_to_units(price: Decimal) -> int:
    """
    Convert a price to C++ units, raising ValueError if it can't be represented.

    Prices must be positive, have at most 4 decimal places and fit in an int64.
    """
    price = Decimal(price)
    if not price.is_finite() or not 0 < price <= _MAX_PRICE:
        raise ValueError(f"Price {price} is out of range")
    # Quantizing with an Inexact trap rejects sub-tick prices without rounding them.
    context = _PRICE_CONTEXT.copy()
    try:
        exact_price = context.quantize(price, _PRICE_TICK)
    except Inexact:
        raise ValueError(f"Price {price} has more than {_PRICE_DECIMALS} decimal places") from None
    return int(context.scaleb(exact_price, _PRICE_DECIMALS))


_EPOCH = datetime(1970, 1, 1)
_MICROSECOND = timedelta(microseconds=1)


def timestamp_to_micros(timestamp: datetime) -> int:
    """Convert a naive datetime to whole microseconds since 1970, exactly."""
    if timestamp.tzinfo is not None:
        raise ValueError("The C++ backend needs naive timestamps, without a timezone")
    return (timestamp - _EPOCH) // _MICROSECOND


def micros_to_timestamp(micros: int) -> datetime:
    return _EPOCH + timedelta(microseconds=micros)


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
