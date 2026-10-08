"""BatteryStateCounter: trapezoidal As / Ah integration."""

from __future__ import annotations

import pytest

from isascale.domain.accumulator import BatteryStateCounter
from isascale.domain.models import INT32_MAX, INT32_MIN


def integrate(samples: list[tuple[float, float]], counter: BatteryStateCounter | None = None) -> BatteryStateCounter:
    counter = counter or BatteryStateCounter()
    for t, ma in samples:
        counter.update(ma, t)
    return counter


def test_first_update_only_sets_reference():
    counter = BatteryStateCounter()
    assert counter.update(100_000, 10.0) == 0.0
    assert counter.charge_as == 0.0


@pytest.mark.parametrize("step_s", [0.02, 1.0, 60.0])
def test_constant_1a_for_one_hour_is_3600_as_and_1_ah(step_s):
    n = round(3600 / step_s)
    counter = integrate([(i * step_s, 1000.0) for i in range(n + 1)])
    assert counter.charge_as == pytest.approx(3600.0)
    assert counter.charge_ah == pytest.approx(1.0)
    assert counter.charge_as_int32 == 3600


def test_ramp_is_exact_with_trapezoid_even_with_two_samples():
    # 0 -> 10 A over 10 s: area = 0.5 * 10 s * 10 A = 50 As.
    assert integrate([(0.0, 0.0), (10.0, 10_000.0)]).charge_as == pytest.approx(50.0)


def test_trapezoid_profile_ramp_hold_ramp_down():
    # 0 -> 100 A in 2 s, hold 100 A 6 s, 100 -> 0 A in 2 s: 100 + 600 + 100 = 800 As.
    samples = [(0.0, 0.0), (2.0, 100_000.0), (8.0, 100_000.0), (10.0, 0.0)]
    assert integrate(samples).charge_as == pytest.approx(800.0)


def test_fine_sampling_of_ramp_gives_same_result():
    samples = [(i * 0.01, i * 0.01 * 1000.0) for i in range(1001)]  # 0..10 A over 10 s
    assert integrate(samples).charge_as == pytest.approx(50.0)


def test_regenerative_negative_current_decreases_charge():
    counter = integrate([(0.0, -50_000.0), (4.0, -50_000.0)])
    assert counter.charge_as == pytest.approx(-200.0)
    assert counter.charge_ah == pytest.approx(-200.0 / 3600)
    assert counter.charge_as_int32 == -200


def test_discharge_then_regen_nets_out():
    samples = [(0.0, 10_000.0), (10.0, 10_000.0), (10.0, -10_000.0), (20.0, -10_000.0)]
    assert integrate(samples).charge_as == pytest.approx(0.0)


def test_sign_change_between_samples_is_trapezoid():
    # +10 A -> -10 A linearly over 2 s: net zero.
    assert integrate([(0.0, 10_000.0), (2.0, -10_000.0)]).charge_as == pytest.approx(0.0)


def test_zero_dt_adds_nothing():
    assert integrate([(1.0, 5_000.0), (1.0, 5_000.0)]).charge_as == 0.0


def test_time_backwards_raises():
    counter = integrate([(5.0, 1000.0)])
    with pytest.raises(ValueError, match="backwards"):
        counter.update(1000.0, 4.999)


def test_reset_clears_charge_and_time_reference():
    counter = integrate([(0.0, 1000.0), (10.0, 1000.0)])
    counter.reset()
    assert counter.charge_as == 0.0
    # No integration across the gap and no "time backwards" after reset.
    counter.update(1000.0, 0.0)
    assert counter.charge_as == 0.0
    counter.update(1000.0, 1.0)
    assert counter.charge_as == pytest.approx(1.0)


def test_reset_with_initial_value():
    counter = integrate([(0.0, 1000.0), (10.0, 1000.0)])
    counter.reset(initial_as=-42.0)
    assert counter.charge_as == -42.0


def test_initial_value_in_constructor():
    counter = integrate([(0.0, 2000.0), (1.0, 2000.0)], BatteryStateCounter(initial_as=100.0))
    assert counter.charge_as == pytest.approx(102.0)


@pytest.mark.parametrize(("initial", "expected"), [(1e12, INT32_MAX), (-1e12, INT32_MIN), (INT32_MAX + 0.4, INT32_MAX)])
def test_int32_value_saturates(initial, expected):
    assert BatteryStateCounter(initial_as=initial).charge_as_int32 == expected


def test_int32_value_saturates_after_integration():
    counter = BatteryStateCounter(initial_as=INT32_MAX - 1)
    integrate([(0.0, 1_000_000.0), (10.0, 1_000_000.0)], counter)  # +10000 As
    assert counter.charge_as > INT32_MAX
    assert counter.charge_as_int32 == INT32_MAX


@pytest.mark.parametrize(("value", "expected"), [(1.4, 1), (1.6, 2), (-1.6, -2)])
def test_int32_value_is_rounded(value, expected):
    assert BatteryStateCounter(initial_as=value).charge_as_int32 == expected
