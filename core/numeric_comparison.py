"""Compare declared numeric representations without widening their tolerance.

Integers, including integer-valued floats, keep their exact integer value.
Noninteger floats use their displayed decimal representation, Decimal(str(value)).
Fraction arithmetic compares those representations without Decimal context rounding.
This is a comparison policy and an integer-mean precision check, not a new statistics
engine or a guarantee of unlimited precision for pandas/scipy computations.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import math
from numbers import Integral, Real
from typing import Iterable

# [작성: 0 이영 · Codex] 2026-10-01T06:07:34+09:00 — N08 정수→float 차이 소실과 N10 숨은 1e-12 오차를 공통 비교 경계에서 차단한다.
POLICY = "integer_exact_decimal_display"


class NumericComparisonError(ValueError):
    """A public error code; never echo unsupported or invalid numeric input."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NumericComparison:
    delta: float
    within_tolerance: bool
    delta_decimal: str
    policy: str = POLICY


def _fraction(value) -> Fraction:
    if isinstance(value, bool):
        raise NumericComparisonError("NUMERIC_INPUT_INVALID")
    if isinstance(value, Integral):
        return Fraction(int(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise NumericComparisonError("NUMERIC_INPUT_INVALID")
        # JSON/pandas call sites use ordinary finite numbers. Bound custom Decimal
        # exponent expansion rather than allocate an unbounded integer denominator.
        if abs(value.adjusted()) > 10000 or len(value.as_tuple().digits) > 10000:
            raise NumericComparisonError("NUMERIC_PRECISION_UNSUPPORTED")
        return Fraction(value)
    if not isinstance(value, Real):
        raise NumericComparisonError("NUMERIC_INPUT_INVALID")
    try:
        number = float(value)
        if not math.isfinite(number):
            raise NumericComparisonError("NUMERIC_INPUT_INVALID")
        # Preserve the actual integer represented by nextafter(1e20, +inf):
        # int(value) is 100000000000000016384, while str(value) rounds to ...20000.
        if number.is_integer():
            return Fraction(int(number))
        return Fraction(Decimal(str(value)))
    except NumericComparisonError:
        raise
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise NumericComparisonError("NUMERIC_INPUT_INVALID") from None


def _tolerance(value) -> Fraction:
    tolerance = _fraction(value)
    if tolerance < 0:
        raise NumericComparisonError("NUMERIC_TOLERANCE_INVALID")
    return tolerance


def _decimal_text(value: Fraction) -> str:
    """Render a nonnegative terminating decimal without context.prec arithmetic."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise NumericComparisonError("NUMERIC_PRECISION_UNSUPPORTED")
    places = max(twos, fives)
    coefficient = value.numerator * 2 ** (places - twos) * 5 ** (places - fives)
    try:
        digits = str(coefficient)
    except ValueError:
        raise NumericComparisonError("NUMERIC_PRECISION_UNSUPPORTED") from None
    if not places:
        return digits
    digits = digits.zfill(places + 1)
    return digits[:-places] + "." + digits[-places:]


def compare_numeric(actual, reported, tolerance) -> NumericComparison:
    """Compare exactly under POLICY; reject an incoherent finite float delta.

    No fixed epsilon is added. In particular 0.8 vs 0.7 at tolerance 0.1 matches,
    but a nonzero decimal difference at tolerance 0 does not. delta_decimal records
    the exact difference under this representation policy. If its finite float
    projection would reverse the tolerance decision, fail closed instead of returning
    e.g. delta=1e100 with within_tolerance=False at tolerance=1e100.
    """
    allowed = _tolerance(tolerance)
    difference = abs(_fraction(actual) - _fraction(reported))
    within = difference <= allowed
    try:
        delta = float(difference)
    except OverflowError:
        raise NumericComparisonError("NUMERIC_PRECISION_UNSUPPORTED") from None
    if not math.isfinite(delta) or (_fraction(delta) <= allowed) != within:
        raise NumericComparisonError("NUMERIC_PRECISION_UNSUPPORTED")
    return NumericComparison(delta, within, _decimal_text(difference))


def require_integer_mean_precision(values: Iterable, actual, tolerance) -> None:
    """Check an integer-input mean's representation error, without replacing its result.

    Only an all-integer, already selected numeric input is covered. Missing-value
    policy, prior CSV coercion, noninteger inputs and other estimators remain the
    responsibility of their existing computation/validation paths. A fractional
    integer mean at zero tolerance can be unsupported rather than falsely supported.
    """
    allowed = _tolerance(tolerance)
    total = count = 0
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Integral):
            return
        total += int(value)
        count += 1
    if count and abs(Fraction(total, count) - _fraction(actual)) > allowed:
        raise NumericComparisonError("INTEGER_MEAN_PRECISION_UNSUPPORTED")
