"""Unit tests for conservative files stub."""

from __future__ import annotations

from server.routes._common import DevicePrincipal
from server.routes.files import FilesHandler


def test_files_unauthenticated_returns_401() -> None:
    handler = FilesHandler(allowlist={"/workspace"})
    response = handler.list_entries(principal=None, path="/workspace")
    assert response.status_code == 401


def test_files_denies_path_outside_allowlist() -> None:
    handler = FilesHandler(allowlist={"/workspace"})
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.list_entries(principal=principal, path="/etc/passwd")
    assert response.status_code == 403


def test_files_allowlist_empty_listing_without_fs() -> None:
    handler = FilesHandler(allowlist={"/workspace"})
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.list_entries(principal=principal, path="/workspace/docs")
    assert response.status_code == 200
    assert response.body["path"] == "/workspace/docs"
    assert response.body["entries"] == []


def test_files_mutate_always_denied() -> None:
    handler = FilesHandler(allowlist={"/workspace"})
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.mutate_denied(principal=principal, body={"path": "/workspace"})
    assert response.status_code == 403
