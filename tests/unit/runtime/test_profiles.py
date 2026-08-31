from __future__ import annotations

from acta.runtime.profiles import (
    BAND_16_32,
    BAND_32_64,
    BAND_64_PLUS,
    BAND_8_16,
    HARDWARE_PROFILES,
    recommend_for_ram,
)

_MODEL_ID_TOKENS = (
    "llama",
    "mistral",
    "mixtral",
    "qwen",
    "gemma",
    "phi-",
    "deepseek",
    "tinyllama",
    "command-r",
    "yi-",
    "gpt-",
    "claude",
    "gemini",
)


def test_profile_recommendations_contain_no_fixed_model_id() -> None:
    assert len(HARDWARE_PROFILES) == 4
    bands = {profile.band_id for profile in HARDWARE_PROFILES}
    assert bands == {BAND_8_16, BAND_16_32, BAND_32_64, BAND_64_PLUS}
    for profile in HARDWARE_PROFILES:
        blob = f"{profile.size_class} {profile.recommendation}".lower()
        for token in _MODEL_ID_TOKENS:
            assert token not in blob
        assert profile.size_class
        assert profile.recommendation


def test_recommend_for_ram_uses_size_class_bands() -> None:
    assert recommend_for_ram(7.9) is None
    compact = recommend_for_ram(8)
    mid = recommend_for_ram(16)
    large = recommend_for_ram(32)
    huge = recommend_for_ram(64)
    assert compact is not None and compact.band_id == BAND_8_16
    assert mid is not None and mid.band_id == BAND_16_32
    assert large is not None and large.band_id == BAND_32_64
    assert huge is not None and huge.band_id == BAND_64_PLUS
    assert compact.size_class == "3-4B-q4"
    assert mid.size_class == "7-9B-q4-q5"
    assert large.size_class == "14B"
    assert huge.size_class == "benchmark"
