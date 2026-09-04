"""
Unit tests for app/services/technicals.py's pure math helpers.

These take plain lists of Decimal closes and return Decimals/None — no
database, no event loop needed. That purity is exactly what's tested here.
"""
from __future__ import annotations

from decimal import Decimal

from app.services.technicals import _detect_cross, _ema, _sma


def _closes(*values: float) -> list[Decimal]:
    return [Decimal(str(v)) for v in values]


class TestSma:
    def test_returns_none_when_not_enough_data(self):
        assert _sma(_closes(1, 2, 3), period=5) is None

    def test_returns_none_on_empty_list(self):
        assert _sma([], period=5) is None

    def test_averages_the_last_n_values_only(self):
        # 10 points, period=3 -> only the last 3 (8, 9, 10) should count.
        closes = _closes(*range(1, 11))
        assert _sma(closes, period=3) == Decimal(9)

    def test_exact_length_match(self):
        closes = _closes(2, 4, 6)
        assert _sma(closes, period=3) == Decimal(4)


class TestEma:
    def test_returns_none_when_not_enough_data(self):
        assert _ema(_closes(1, 2), period=5) is None

    def test_seeds_with_sma_when_exactly_period_length(self):
        closes = _closes(10, 20, 30)
        # With no points beyond `period`, EMA == SMA of the whole window.
        assert _ema(closes, period=3) == _sma(closes, period=3)

    def test_smooths_beyond_the_seed_window(self):
        # period=2 -> k = 2/3. Seed = avg(10, 20) = 15.
        # Next point 40: ema = 40*(2/3) + 15*(1/3) = 31.666...
        closes = _closes(10, 20, 40)
        result = _ema(closes, period=2)
        assert result == Decimal(40) * (Decimal(2) / Decimal(3)) + Decimal(15) * (
            Decimal(1) / Decimal(3)
        )


class TestDetectCross:
    def test_returns_none_with_fewer_than_51_points(self):
        assert _detect_cross(_closes(*range(50))) is None

    def test_no_cross_when_ordering_is_stable(self):
        # Monotonically increasing prices: SMA20 stays above SMA50
        # throughout, so the *ordering* never flips -> no cross event.
        closes = _closes(*range(1, 61))
        assert _detect_cross(closes) is None

    def test_detects_golden_cross(self):
        # Flat-then-rising series: engineered so SMA20 crosses above SMA50
        # exactly on the most recent point.
        closes = _closes(*([10] * 55)) + _closes(100)
        result = _detect_cross(closes)
        assert result == "golden_cross"

    def test_detects_death_cross(self):
        closes = _closes(*([100] * 55)) + _closes(1)
        result = _detect_cross(closes)
        assert result == "death_cross"
