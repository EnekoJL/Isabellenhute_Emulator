"""Built-in current profiles for an electric racing motorcycle (pure domain data).

Sign convention: + = discharge (traction), - = charge (regenerative braking).
Values are representative test stimuli, not measured data.
"""

from __future__ import annotations

from isascale.domain.models import CurrentProfile


def wot_acceleration() -> CurrentProfile:
    """Wide-open-throttle launch: ramp to 450 A peak, sustain, back off."""
    return CurrentProfile(
        "WOT acceleration",
        ((0.0, 5_000), (0.3, 250_000), (0.8, 450_000), (4.0, 420_000), (5.0, 300_000), (6.0, 20_000)),
    )


def regen_braking() -> CurrentProfile:
    """Hard braking from speed: cruise, regen peak -120 A, fade to idle."""
    return CurrentProfile(
        "Regen braking",
        ((0.0, 80_000), (0.5, 80_000), (0.8, -60_000), (1.2, -120_000), (3.0, -90_000), (4.0, -20_000), (4.5, 2_000)),
    )


def idle_consumption() -> CurrentProfile:
    """Standstill with ignition on: ~2 A auxiliaries with small pump/fan steps."""
    return CurrentProfile(
        "Idle consumption",
        ((0.0, 2_000), (2.0, 2_000), (2.1, 3_500), (5.0, 3_500), (5.1, 2_000), (10.0, 2_000)),
    )


BUILTIN_PROFILES = {
    "wot": wot_acceleration,
    "regen": regen_braking,
    "idle": idle_consumption,
}
