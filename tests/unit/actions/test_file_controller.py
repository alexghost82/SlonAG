"""Allowlisted paths, confirmation, and trash-only deletes for file_controller."""

from __future__ import annotations

from pathlib import Path

import pytest

from actions.file_controller import file_controller
from acta.safety import DecisionKind, RiskLevel, authorize, risk_for


SECRET = "sk-abcdefghijklmnopqrstuvwxyz012345"


def _run(
    tmp_path: Path,
    parameters: dict,
    *,
    confirmer=None,
    trash=None,
    logger=None,
    allowlist=None,
    source: str = "user",
    undo_stack=None,
) -> str:
    return file_controller(
        parameters=parameters,
        allowlist=allowlist if allowlist is not None else [tmp_path],
        confirmer=confirmer,
        trash=trash,
        logger=logger,
        source=source,
        undo_stack=undo_stack,
    )


def test_risk_and_authorize_mapping() -> None:
    assert risk_for("file_controller") is RiskLevel.CONFIRM
    listed = authorize(
        "file_controller",
        {"action": "list", "path": "desktop"},
        source="user",
    )
    assert listed.kind is DecisionKind.ALLOW
    assert listed.risk is RiskLevel.READ
    written = authorize(
        "file_controller",
        {"action": "write", "path": "desktop", "name": "n.txt"},
        source="user",
    )
    assert written.kind is DecisionKind.CONFIRM
    deleted = authorize(
        "file_controller",
        {"action": "delete", "path": "desktop", "name": "n.txt"},
        source="user",
    )
    assert deleted.kind is DecisionKind.EXACT_CONFIRM


def test_list_and_read_inside_allowlist_need_no_confirm(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")
    listed = _run(tmp_path, {"action": "list", "path": str(tmp_path)})
    assert "note.txt" in listed
    read = _run(tmp_path, {"action": "read", "path": str(target)})
    assert "hello" in read


def test_traversal_escape_blocked(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "ok.txt").write_text("ok", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("classified", encoding="utf-8")
    escaped = allowed / ".." / "secret.txt"

    read = file_controller(
        parameters={"action": "read", "path": str(escaped)},
        allowlist=[allowed],
    )
    assert "classified" not in read
    assert "denied by allowlist" in read

    written = file_controller(
        parameters={"action": "write", "path": str(escaped), "content": "x"},
        allowlist=[allowed],
        confirmer=lambda decision: True,
    )
    assert secret.read_text(encoding="utf-8") == "classified"
    assert "denied by allowlist" in written


def test_symlink_escape_blocked(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("classified", encoding="utf-8")
    link = allowed / "link.txt"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("symlinks are not available")

    result = file_controller(
        parameters={"action": "read", "path": str(link)},
        allowlist=[allowed],
    )
    assert "classified" not in result
    assert "denied by allowlist" in result


def test_home_root_and_system_blocked_even_if_listed(tmp_path: Path) -> None:
    home = Path.home()
    listed_home = _run(
        tmp_path,
        {"action": "list", "path": str(home)},
        allowlist=[tmp_path, home],
        confirmer=lambda decision: True,
    )
    assert "Path denied or denied by allowlist" in listed_home

    listed_root = _run(
        tmp_path,
        {"action": "list", "path": "/"},
        allowlist=[tmp_path, Path("/")],
        confirmer=lambda decision: True,
    )
    assert "Path denied or denied by allowlist" in listed_root

    import platform
    for system in ("/etc", "/System"):
        result = _run(
            tmp_path,
            {"action": "list", "path": system},
            allowlist=[tmp_path, Path(system)],
            confirmer=lambda decision: True,
        )
        assert "Path denied or denied by allowlist" in result
    if platform.system() == "Windows":
        for system in (r"C:\Windows", "C:\\", "C:/Windows"):
            result = _run(
                tmp_path,
                {"action": "list", "path": system},
                allowlist=[tmp_path, Path(system)],
                confirmer=lambda decision: True,
            )
            assert "Path denied or denied by allowlist" in result


def test_delete_without_confirm_does_not_remove(tmp_path: Path) -> None:
    target = tmp_path / "keep.txt"
    target.write_text("keep", encoding="utf-8")
    trashed: list[Path] = []

    declined = _run(
        tmp_path,
        {"action": "delete", "path": str(target)},
        confirmer=lambda decision: False,
        trash=trashed.append,
    )
    assert target.exists()
    assert trashed == []
    assert "Подтверждение отклонено." in declined

    missing = _run(
        tmp_path,
        {"action": "delete", "path": str(target)},
        trash=trashed.append,
    )
    assert target.exists()
    assert trashed == []
    assert "Требуется подтверждение." in missing


def test_delete_with_confirm_uses_trash_not_permanent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "gone.txt"
    target.write_text("x", encoding="utf-8")
    trashed: list[Path] = []
    decisions: list = []
    unlink_calls: list[str] = []

    def _unlink(self: Path, *args: object, **kwargs: object) -> None:
        unlink_calls.append("unlink")
        raise AssertionError("permanent delete must not run")

    def _rmtree(*args: object, **kwargs: object) -> None:
        unlink_calls.append("rmtree")
        raise AssertionError("permanent delete must not run")

    monkeypatch.setattr(Path, "unlink", _unlink)
    monkeypatch.setattr("acta.filesystem.operations.shutil.rmtree", _rmtree)

    def _confirm(decision) -> bool:
        decisions.append(decision)
        return True

    result = _run(
        tmp_path,
        {"action": "delete", "path": str(target)},
        confirmer=_confirm,
        trash=trashed.append,
    )
    assert not target.exists()
    assert trashed == [target.resolve()]
    assert unlink_calls == []
    assert decisions[0].kind is DecisionKind.EXACT_CONFIRM
    assert "Recycle Bin" in result


def test_write_move_rename_require_confirm(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_text("data", encoding="utf-8")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    assert "Требуется подтверждение." in _run(
        tmp_path,
        {"action": "write", "path": str(tmp_path / "new.txt"), "content": "x"},
    )
    assert not (tmp_path / "new.txt").exists()

    assert "Требуется подтверждение." in _run(
        tmp_path,
        {"action": "move", "path": str(source), "destination": str(dest_dir / "a.txt")},
    )
    assert source.exists()
    assert not (dest_dir / "a.txt").exists()

    assert "Требуется подтверждение." in _run(
        tmp_path,
        {"action": "rename", "path": str(source), "new_name": "b.txt"},
    )
    assert source.exists()
    assert not (tmp_path / "b.txt").exists()


def test_file_controller_works_with_injected_hooks(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    logs: list[str] = []
    created = file_controller(
        parameters={"action": "write", "path": str(target), "content": SECRET},
        player=None,
        allowlist=[tmp_path],
        confirmer=lambda decision: True,
        logger=logs.append,
    )
    assert target.exists()
    assert target.read_text(encoding="utf-8") == SECRET
    assert "Written:" in created
    assert logs
    assert str(target.resolve()) in logs[0]
    assert SECRET not in "".join(logs)

    read = file_controller(
        parameters={"action": "read", "path": str(target)},
        player=None,
        allowlist=[tmp_path],
        logger=logs.append,
    )
    assert SECRET in read
    assert SECRET not in "".join(logs)


def test_untrusted_source_does_not_mutate(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("keep", encoding="utf-8")
    result = _run(
        tmp_path,
        {"action": "delete", "path": str(target)},
        confirmer=lambda decision: True,
        trash=lambda path: path.unlink(),
        source="web",
    )
    assert target.exists()
    assert "denied" in result.lower() or "cannot start" in result.lower()


def test_undo_move_when_previous_path_available(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    source.write_text("data", encoding="utf-8")
    stack: list[dict[str, Path]] = []

    moved = _run(
        tmp_path,
        {"action": "move", "path": str(source), "destination": str(dest_dir / "a.txt")},
        confirmer=lambda decision: True,
        undo_stack=stack,
    )
    assert "Renamed:" in moved
    assert not source.exists()
    assert (dest_dir / "a.txt").read_text(encoding="utf-8") == "data"

    undone = _run(
        tmp_path,
        {"action": "undo"},
        confirmer=lambda decision: True,
        undo_stack=stack,
    )
    assert "deprecated" in undone.lower()
    # Undo is deprecated so the move remains in effect
