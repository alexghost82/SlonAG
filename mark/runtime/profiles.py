"""Hardware RAM bands mapped to size-class recommendations.

Recommendations are configuration data, not a pinned model id. Callers pick
a concrete catalog entry that matches the size class.
"""

from __future__ import annotations

from dataclasses import dataclass

BAND_8_16 = "ram_8_16"
BAND_16_32 = "ram_16_32"
BAND_32_64 = "ram_32_64"
BAND_64_PLUS = "ram_64_plus"


@dataclass(frozen=True)
class HardwareProfile:
    """One RAM band and the size class it can host."""

    band_id: str
    ram_min_gb: int
    ram_max_gb: int | None
    size_class: str
    recommendation: str


HARDWARE_PROFILES: tuple[HardwareProfile, ...] = (
    HardwareProfile(
        band_id=BAND_8_16,
        ram_min_gb=8,
        ram_max_gb=16,
        size_class="3-4B-q4",
        recommendation="компактные 3–4B Q4",
    ),
    HardwareProfile(
        band_id=BAND_16_32,
        ram_min_gb=16,
        ram_max_gb=32,
        size_class="7-9B-q4-q5",
        recommendation="7–9B Q4/Q5",
    ),
    HardwareProfile(
        band_id=BAND_32_64,
        ram_min_gb=32,
        ram_max_gb=64,
        size_class="14B",
        recommendation="14B либо более качественные модели меньшего размера",
    ),
    HardwareProfile(
        band_id=BAND_64_PLUS,
        ram_min_gb=64,
        ram_max_gb=None,
        size_class="benchmark",
        recommendation="подобрать по локальному benchmark",
    ),
)


def recommend_for_ram(ram_gb: float) -> HardwareProfile | None:
    """Return the size-class profile for ``ram_gb``, or None below 8 GB.

    Bands are half-open: 8 ≤ x < 16, 16 ≤ x < 32, 32 ≤ x < 64, 64 ≤ x.
    """
    if ram_gb < 8:
        return None
    for profile in HARDWARE_PROFILES:
        upper = profile.ram_max_gb
        if upper is None:
            if ram_gb >= profile.ram_min_gb:
                return profile
            continue
        if profile.ram_min_gb <= ram_gb < upper:
            return profile
    return None


__all__ = [
    "BAND_16_32",
    "BAND_32_64",
    "BAND_64_PLUS",
    "BAND_8_16",
    "HARDWARE_PROFILES",
    "HardwareProfile",
    "recommend_for_ram",
]
