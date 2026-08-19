"""In-memory vision engines for unit tests. No models, screenshots, or network."""

from __future__ import annotations

from pathlib import Path


class FakeEngine:
    """Records ``analyze`` calls and returns a canned string."""

    def __init__(self, text: str = "на изображении текст") -> None:
        self.text = text
        self.calls: list[tuple[bytes, str, str]] = []

    def analyze(self, image: bytes, prompt: str, kind: str) -> str:
        self.calls.append((image, prompt, kind))
        return self.text


class CloudEngine:
    """Cloud-marked engine. Must not run when the local policy forbids it."""

    cloud = True

    def __init__(self, text: str = "from cloud") -> None:
        self.text = text
        self.calls: list[tuple[bytes, str, str]] = []

    def analyze(self, image: bytes, prompt: str, kind: str) -> str:
        self.calls.append((image, prompt, kind))
        return self.text


class SnapshotWatchingEngine:
    """Records files present in ``temp_dir`` while ``analyze`` runs."""

    def __init__(self, temp_dir: Path, text: str = "ok") -> None:
        self.temp_dir = temp_dir
        self.text = text
        self.calls: list[tuple[bytes, str, str]] = []
        self.snapshots_during_call: list[Path] = []
        self.snapshot_bytes: list[bytes] = []

    def analyze(self, image: bytes, prompt: str, kind: str) -> str:
        self.calls.append((image, prompt, kind))
        self.snapshots_during_call = [
            path for path in self.temp_dir.iterdir() if path.is_file()
        ]
        self.snapshot_bytes = [path.read_bytes() for path in self.snapshots_during_call]
        return self.text


class ExplodingEngine:
    """Fails after recording any snapshot files under ``temp_dir``."""

    def __init__(self, temp_dir: Path | None = None) -> None:
        self.temp_dir = temp_dir
        self.calls: list[tuple[bytes, str, str]] = []
        self.snapshots_during_call: list[Path] = []

    def analyze(self, image: bytes, prompt: str, kind: str) -> str:
        self.calls.append((image, prompt, kind))
        if self.temp_dir is not None:
            self.snapshots_during_call = [
                path for path in self.temp_dir.iterdir() if path.is_file()
            ]
        raise RuntimeError("vision engine failed")
