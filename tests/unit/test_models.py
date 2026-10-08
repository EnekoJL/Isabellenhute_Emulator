"""Domain models: CANFrame, IVTConfig, MessageCounter, CurrentProfile."""

from __future__ import annotations

import pytest

from isascale.domain.models import (
    MAX_TOTAL_MESSAGES_PER_S,
    Bitrate,
    CANFrame,
    CurrentProfile,
    IVTConfig,
    MessageCounter,
    NominalRange,
)

# -------------------------------------------------------------------- CANFrame


@pytest.mark.parametrize("arbitration_id", [0x000, 0x411, 0x7FF])
def test_canframe_accepts_11_bit_ids(arbitration_id):
    assert CANFrame(arbitration_id, b"\x00").arbitration_id == arbitration_id


@pytest.mark.parametrize("arbitration_id", [-1, 0x800, 0x1FFFFFFF])
def test_canframe_rejects_non_11_bit_ids(arbitration_id):
    with pytest.raises(ValueError):
        CANFrame(arbitration_id, b"")


def test_canframe_rejects_more_than_8_bytes():
    with pytest.raises(ValueError):
        CANFrame(0x100, bytes(9))


@pytest.mark.parametrize("data", [bytearray(b"\x01\x02"), [1, 2], b"\x01\x02"])
def test_canframe_normalises_data_to_bytes(data):
    frame = CANFrame(0x100, data)
    assert isinstance(frame.data, bytes)
    assert frame.data == b"\x01\x02"
    assert frame.dlc == 2


def test_canframe_is_immutable():
    frame = CANFrame(0x100, b"")
    with pytest.raises(AttributeError):
        frame.arbitration_id = 0x200  # type: ignore[misc]


# -------------------------------------------------------------------- IVTConfig


def test_ivtconfig_defaults_match_datasheet():
    cfg = IVTConfig()
    assert cfg.bitrate is Bitrate.B500K
    assert (cfg.current_period_ms, cfg.temperature_period_ms, cfg.charge_period_ms) == (20, 100, 30)
    assert cfg.nominal_range is NominalRange.A1000
    assert cfg.temperature_enabled and cfg.charge_enabled


@pytest.mark.parametrize("field", ["current_period_ms", "temperature_period_ms", "charge_period_ms"])
@pytest.mark.parametrize("value", [0, -1, 101, 1000])
def test_ivtconfig_rejects_periods_outside_1_to_100_ms(field, value):
    with pytest.raises(ValueError):
        IVTConfig(**{field: value})


@pytest.mark.parametrize("field", ["current_period_ms", "temperature_period_ms", "charge_period_ms"])
def test_ivtconfig_accepts_100_ms_upper_bound(field):
    assert getattr(IVTConfig(**{field: 100}), field) == 100


@pytest.mark.parametrize("field", ["temperature_period_ms", "charge_period_ms"])
def test_ivtconfig_accepts_1_ms_lower_bound_when_rate_allows(field):
    cfg = IVTConfig(current_period_ms=100, temperature_enabled=False, charge_enabled=False, **{field: 1})
    assert getattr(cfg, field) == 1  # disabled channel: period still validated but not counted


def test_ivtconfig_rejects_more_than_1000_messages_per_second():
    # 1 ms current alone = 1000 msg/s; T (10/s) on top exceeds the datasheet limit.
    with pytest.raises(ValueError, match="1000"):
        IVTConfig(current_period_ms=1, temperature_enabled=True, charge_enabled=False)


def test_ivtconfig_accepts_exactly_1000_messages_per_second():
    cfg = IVTConfig(current_period_ms=1, temperature_enabled=False, charge_enabled=False)
    assert cfg.total_messages_per_s() == MAX_TOTAL_MESSAGES_PER_S


def test_ivtconfig_total_rate_counts_only_enabled_channels():
    assert IVTConfig().total_messages_per_s() == pytest.approx(50 + 10 + 1000 / 30)
    assert IVTConfig(temperature_enabled=False, charge_enabled=False).total_messages_per_s() == 50


@pytest.mark.parametrize("serial", [-1, 2**32])
def test_ivtconfig_rejects_serial_not_32_bit(serial):
    with pytest.raises(ValueError):
        IVTConfig(serial_number=serial)


# ---------------------------------------------------------------- MessageCounter


def test_message_counter_counts_0_to_15_then_wraps_to_0():
    counter = MessageCounter()
    values = [counter.next() for _ in range(40)]
    assert values == [i % 16 for i in range(40)]


def test_message_counter_overflow_0xf_to_0x0():
    counter = MessageCounter(start=0xF)
    assert counter.next() == 0xF
    assert counter.value == 0x0
    assert counter.next() == 0x0


def test_message_counters_are_independent():
    a, b = MessageCounter(), MessageCounter()
    for _ in range(20):
        a.next()
    assert b.value == 0
    assert b.next() == 0
    assert a.value == 20 % 16


def test_message_counter_reset():
    counter = MessageCounter(start=7)
    counter.next()
    counter.reset()
    assert counter.value == 0


@pytest.mark.parametrize("start", [-1, 16])
def test_message_counter_rejects_invalid_start(start):
    with pytest.raises(ValueError):
        MessageCounter(start)


# ---------------------------------------------------------------- CurrentProfile


@pytest.fixture
def triangle() -> CurrentProfile:
    return CurrentProfile("tri", ((0.0, 0.0), (1.0, 10_000.0), (3.0, -10_000.0)))


@pytest.mark.parametrize(
    ("t", "expected"),
    [(0.0, 0.0), (0.25, 2_500.0), (0.5, 5_000.0), (1.0, 10_000.0), (2.0, 0.0), (2.5, -5_000.0), (3.0, -10_000.0)],
)
def test_profile_linear_interpolation(triangle, t, expected):
    assert triangle.current_at(t) == pytest.approx(expected)


@pytest.mark.parametrize(("t", "expected"), [(-5.0, 0.0), (3.0001, -10_000.0), (1e6, -10_000.0)])
def test_profile_clamps_outside_range(triangle, t, expected):
    assert triangle.current_at(t) == expected


def test_profile_duration_and_bounds():
    profile = CurrentProfile("p", ((2.0, 1.0), (5.0, 2.0)))
    assert (profile.start_s, profile.end_s, profile.duration_s) == (2.0, 5.0, 3.0)


def test_profile_normalises_points_to_float():
    profile = CurrentProfile("p", ((0, 1), (1, 2)))
    assert profile.points == ((0.0, 1.0), (1.0, 2.0))
    assert all(isinstance(v, float) for point in profile.points for v in point)


@pytest.mark.parametrize(
    "points",
    [
        (),
        ((0.0, 1.0),),
        ((0.0, 1.0), (0.0, 2.0)),  # equal times
        ((0.0, 1.0), (2.0, 2.0), (1.0, 3.0)),  # decreasing
        ((-1.0, 1.0), (1.0, 2.0)),  # negative time
    ],
)
def test_profile_rejects_invalid_points(points):
    with pytest.raises(ValueError):
        CurrentProfile("bad", points)
