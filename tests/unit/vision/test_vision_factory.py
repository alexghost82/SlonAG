"""Factory registration for ``vision_local``."""

from __future__ import annotations

import importlib
from pathlib import Path

from providers.contracts import VisionProvider
from providers.registry import get, registered_ids

from acta.vision.provider import LocalVisionProvider

from tests.unit.vision.fakes import FakeEngine


def test_factory_vision_local_is_registered(
    clean_registry, tmp_path: Path
) -> None:
    import acta.vision as vision_pkg

    importlib.reload(vision_pkg)
    assert vision_pkg.PROVIDER_ID == "vision_local"
    assert "vision_local" in registered_ids()
    factory = get("vision_local")
    provider = factory(engine=FakeEngine(), temp_dir=tmp_path)
    assert factory is vision_pkg.LocalVisionProvider
    assert isinstance(provider, LocalVisionProvider)
    assert isinstance(provider, VisionProvider)
    assert provider.provider_id == "vision_local"


def test_register_factory_is_idempotent(clean_registry) -> None:
    import acta.vision as vision_pkg

    importlib.reload(vision_pkg)
    vision_pkg.register_factory()
    vision_pkg.register_factory()
    assert get("vision_local") is vision_pkg.LocalVisionProvider
