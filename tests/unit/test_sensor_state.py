"""Pure sensor state: error counters, log book, OCS detector, measurement range."""

from __future__ import annotations

import pytest

from isascale.domain.models import NominalRange, OcThresholds
from isascale.domain.sensor_state import ErrorCounters, LogBook, LogItem, LogSample, OcDetector, RangeTracker


def sample(current_ma=0.0, temperature_c=25.0, dt_s=1.0, in_range=True, pos=False, neg=False, counter=True):
    return LogSample(current_ma, temperature_c, dt_s, in_range, pos, neg, counter)


# ---------------------------------------------------------------- ErrorCounters


def test_error_counters_count_saturate_and_reset():
    counters = ErrorCounters(0x10)
    assert counters.size == 0x10 and not counters.any
    for _ in range(300):
        counters.increment(0x0F)
    assert counters.count(0x0F) == 255
    counters.increment(0x01)
    counters.reset(0x0F)
    assert (counters.count(0x0F), counters.count(0x01)) == (0, 1)
    counters.reset()
    assert not counters.any


@pytest.mark.parametrize("index", [0, 0x11, -1])
def test_error_counters_reject_unknown_index(index):
    with pytest.raises(ValueError):
        ErrorCounters(0x10).count(index)


@pytest.mark.parametrize(("index", "mask"), [(1, (0x01, 0)), (8, (0x80, 0)), (9, (0, 0x01)), (16, (0, 0x80))])
def test_error_bitmask_layout(index, mask):
    counters = ErrorCounters(0x10)
    counters.increment(index)
    assert counters.bitmask() == mask


# ---------------------------------------------------------------------- LogBook


def test_log_book_charge_split_by_sign():
    book = LogBook()
    book.update(sample(current_ma=10_000, dt_s=3.0))
    book.update(sample(current_ma=-4_000, dt_s=5.0))
    assert book.value(LogItem.AS_DISCHARGING) == 30
    assert book.value(LogItem.AS_CHARGING) == 20
    assert book.value(LogItem.AS_OVERALL) == 10


def test_log_book_charge_needs_active_counter():
    book = LogBook()
    book.update(sample(current_ma=10_000, counter=False))
    assert book.value(LogItem.AS_OVERALL) == 0
    assert book.value(LogItem.RUNTIME_OVERALL) == 1


def test_log_book_runtimes():
    book = LogBook()
    book.update(sample(dt_s=2.0))
    book.update(sample(dt_s=3.0, in_range=False, temperature_c=110.0, pos=True))
    book.update(sample(dt_s=4.0, temperature_c=-41.0, neg=True))
    assert book.value(LogItem.RUNTIME_OVERALL) == 9
    assert (book.value(LogItem.RUNTIME_I_IN), book.value(LogItem.RUNTIME_I_OUT)) == (6, 3)
    assert (book.value(LogItem.RUNTIME_T_IN), book.value(LogItem.RUNTIME_T_OUT)) == (2, 7)
    assert (book.value(LogItem.RUNTIME_OC_POS), book.value(LogItem.RUNTIME_OC_NEG)) == (3, 4)


def test_log_book_extremes_and_unmeasured_items():
    book = LogBook()
    assert book.value(LogItem.I_MAX) == 0  # nothing measured yet
    book.update(sample(current_ma=123_400, temperature_c=31.26))
    book.update(sample(current_ma=-5_600, temperature_c=-2.0))
    assert (book.value(LogItem.I_MAX), book.value(LogItem.I_MIN)) == (123, -6)
    assert (book.value(LogItem.T_MAX), book.value(LogItem.T_MIN)) == (313, -20)
    assert book.value(LogItem.U1_MAX) == book.value(LogItem.WH_OVERALL) == 0  # U0: no voltage
    book.reset()
    assert book.value(LogItem.I_MAX) == 0


def test_log_book_rejects_negative_dt():
    with pytest.raises(ValueError):
        LogBook().update(sample(dt_s=-0.1))


# ------------------------------------------------------------------- OcDetector


def test_oc_off_by_default():
    oc = OcDetector()
    assert not oc.update(1e9, OcThresholds(), OcThresholds())


def test_oc_positive_hysteresis():
    oc, pos, off = OcDetector(), OcThresholds(500, 450), OcThresholds()
    assert [oc.update(i * 1000, pos, off) for i in (499, 500, 470, 449, 470)] == [False, True, True, False, False]


def test_oc_negative_without_reset_threshold_releases_at_set_level():
    oc, off, neg = OcDetector(), OcThresholds(), OcThresholds(-300, 0)
    assert [oc.update(i * 1000, off, neg) for i in (-299, -300, -299, -350)] == [False, True, False, True]
    assert oc.negative and not oc.positive
    oc.reset()
    assert not oc.active


# ----------------------------------------------------------------- RangeTracker


def test_range_switch_and_return_hysteresis_1000a():
    tracker = RangeTracker(NominalRange.A1000)
    assert [tracker.update(i * 1000) for i in (1000, 1001, 951, 949, -1001)] == [False, True, True, False, True]
    tracker.reset()
    assert not tracker.extended


@pytest.mark.parametrize(
    ("nominal", "limit_a"),
    [(NominalRange.A100, 800), (NominalRange.A300, 2500), (NominalRange.A500, 6900),
     (NominalRange.A1000, 12200), (NominalRange.A2500, 48000)],
)
def test_overcurrent_range_clamp(nominal, limit_a):
    tracker = RangeTracker(nominal)
    assert tracker.clamp(10**10) == limit_a * 1000
    assert tracker.clamp(-(10**10)) == -limit_a * 1000
    assert tracker.clamp(1234) == 1234
