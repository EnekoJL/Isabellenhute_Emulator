"""Current sources (manual / profile) and the built-in motorcycle profiles."""

from __future__ import annotations

import pytest

from isascale.application.builtin_profiles import (
    BUILTIN_PROFILES,
    idle_consumption,
    regen_braking,
    wot_acceleration,
)
from isascale.application.sources import ConstantSource, ProfileSource
from isascale.domain.models import CurrentProfile, NominalRange


@pytest.fixture
def ramp() -> CurrentProfile:
    # 0 -> 10 A over 4 s
    return CurrentProfile("ramp", ((0.0, 0.0), (4.0, 10_000.0)))


# ---------------------------------------------------------------- ConstantSource


def test_constant_source_returns_fixed_current_any_time():
    src = ConstantSource(12_345)
    assert [src.current_at(t) for t in (0.0, 1.0, 1e6)] == [12_345.0] * 3


def test_constant_source_is_adjustable_in_real_time():
    src = ConstantSource(0)
    src.current_ma = -5_000
    assert src.current_at(3.0) == -5_000


def test_constant_source_is_endless():
    src = ConstantSource()
    assert src.name == "manual"
    assert src.duration_s is None
    assert src.progress(10.0) is None


# ----------------------------------------------------------------- ProfileSource


def test_profile_source_single_shot_holds_last_value(ramp):
    src = ProfileSource(ramp, loop=False)
    assert src.current_at(0.0) == 0.0
    assert src.current_at(2.0) == pytest.approx(5_000.0)
    assert src.current_at(4.0) == 10_000.0
    assert src.current_at(100.0) == 10_000.0
    assert not src.finished(3.9)
    assert src.finished(4.0)


def test_profile_source_loop_wraps(ramp):
    src = ProfileSource(ramp, loop=True)
    assert src.current_at(5.0) == pytest.approx(src.current_at(1.0))
    assert src.current_at(4.0) == pytest.approx(0.0)  # exactly one period -> start again
    assert src.current_at(10.0) == pytest.approx(5_000.0)
    assert not src.finished(1e6)


@pytest.mark.parametrize(("elapsed", "progress"), [(-1.0, 0.0), (0.0, 0.0), (1.0, 0.25), (4.0, 1.0), (40.0, 1.0)])
def test_profile_source_progress_single_shot(ramp, elapsed, progress):
    assert ProfileSource(ramp).progress(elapsed) == pytest.approx(progress)


@pytest.mark.parametrize(("elapsed", "progress"), [(1.0, 0.25), (5.0, 0.25), (6.0, 0.5)])
def test_profile_source_progress_loop(ramp, elapsed, progress):
    assert ProfileSource(ramp, loop=True).progress(elapsed) == pytest.approx(progress)


def test_profile_source_starts_at_first_point_even_if_not_zero():
    profile = CurrentProfile("offset", ((10.0, 1_000.0), (12.0, 3_000.0)))
    src = ProfileSource(profile)
    assert src.current_at(0.0) == 1_000.0
    assert src.current_at(1.0) == pytest.approx(2_000.0)
    assert src.duration_s == 2.0
    assert src.progress(1.0) == pytest.approx(0.5)


def test_profile_source_name_from_profile(ramp):
    assert ProfileSource(ramp).name == "ramp"


# -------------------------------------------------------------- builtin profiles


def test_builtin_registry_keys():
    assert set(BUILTIN_PROFILES) == {"wot", "regen", "idle"}
    for factory in BUILTIN_PROFILES.values():
        assert isinstance(factory(), CurrentProfile)


@pytest.mark.parametrize("factory", [wot_acceleration, regen_braking, idle_consumption])
def test_builtin_profiles_within_default_nominal_range(factory):
    profile = factory()
    assert profile.start_s == 0.0
    assert all(abs(i) <= int(NominalRange.A1000) * 1000 for _, i in profile.points)


def test_wot_is_pure_discharge_with_450a_peak():
    currents = [i for _, i in wot_acceleration().points]
    assert max(currents) == 450_000
    assert min(currents) > 0


def test_regen_has_negative_charge_current():
    assert min(i for _, i in regen_braking().points) == -120_000


def test_idle_is_small_positive():
    assert all(0 < i <= 5_000 for _, i in idle_consumption().points)
