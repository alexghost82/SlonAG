"""Signed, short-lived and device-bound artifact transfers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from gateway.store import GatewayStore

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_TTL_SECONDS = 300.0
DEFAULT_MIME_TYPES = frozenset({
    "image/jpeg", "image/png", "audio/wav", "audio/mpeg",
    "application/pdf", "application/octet-stream", "text/plain",
})


class ArtifactTransferError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArtifactGrant:
    grant_id: str
    artifact_id: str
    operation: str
    mime_type: str
    max_bytes: int
    expires_at: float
    ticket: str


class ArtifactTransferService:
    def __init__(
        self, *, store: GatewayStore, root: str | Path, signing_key: bytes,
        clock: Callable[[], float] | None = None,
        allowed_mime_types: frozenset[str] = DEFAULT_MIME_TYPES,
    ) -> None:
        if not signing_key:
            raise ValueError("artifact signing key must be non-empty")
        self.store = store
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._key = signing_key
        self._clock = clock or time.time
        self.allowed_mime_types = allowed_mime_types

    def issue(
        self, *, device_id: str, workspace_id: str, operation: str,
        mime_type: str, max_bytes: int = DEFAULT_MAX_BYTES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        artifact_id: str | None = None,
    ) -> ArtifactGrant:
        if operation not in {"upload", "download"}:
            raise ArtifactTransferError("unsupported artifact operation")
        if mime_type not in self.allowed_mime_types:
            raise ArtifactTransferError("artifact MIME type is not allowed")
        if max_bytes <= 0 or max_bytes > DEFAULT_MAX_BYTES:
            raise ArtifactTransferError("artifact size limit is invalid")
        if ttl_seconds <= 0 or ttl_seconds > DEFAULT_TTL_SECONDS:
            raise ArtifactTransferError("artifact expiry is invalid")
        grant_id = str(uuid4())
        artifact_id = artifact_id or str(uuid4())
        expires_at = float(self._clock()) + ttl_seconds
        storage_name = f"{artifact_id}.bin"
        claims = {
            "gid": grant_id, "aid": artifact_id, "did": device_id,
            "wid": workspace_id, "op": operation, "mime": mime_type,
            "max": max_bytes, "exp": expires_at,
        }
        ticket = self._sign(claims)
        self.store.put_artifact_grant((
            grant_id, artifact_id, device_id, workspace_id, operation, mime_type,
            max_bytes, expires_at, 0, storage_name,
        ))
        return ArtifactGrant(
            grant_id, artifact_id, operation, mime_type, max_bytes, expires_at, ticket
        )

    def issue_download(
        self, *, artifact_id: str, device_id: str, workspace_id: str,
        mime_type: str, max_bytes: int = DEFAULT_MAX_BYTES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> ArtifactGrant:
        try:
            artifact_id = str(UUID(artifact_id))
        except (ValueError, AttributeError) as exc:
            raise ArtifactTransferError("artifact identifier is invalid") from exc
        artifact = self.store.artifact(artifact_id)
        if artifact is None:
            raise ArtifactTransferError("artifact is unavailable")
        if (artifact["device_id"] != device_id
                or artifact["workspace_id"] != workspace_id):
            raise ArtifactTransferError("artifact owner mismatch")
        if not self._storage_path(str(artifact["storage_name"])).is_file():
            raise ArtifactTransferError("artifact is unavailable")
        return self.issue(
            device_id=device_id, workspace_id=workspace_id, operation="download",
            mime_type=str(artifact["mime_type"]),
            max_bytes=min(max_bytes, int(artifact["size"])), ttl_seconds=ttl_seconds,
            artifact_id=artifact_id,
        )

    def upload(
        self, *, ticket: str, device_id: str, workspace_id: str,
        mime_type: str, data: bytes,
    ) -> dict[str, object]:
        record = self._verify(ticket, device_id, workspace_id, "upload")
        if mime_type != record["mime_type"]:
            raise ArtifactTransferError("artifact MIME type mismatch")
        if len(data) > int(record["max_bytes"]):
            raise ArtifactTransferError("artifact exceeds signed size limit")
        if not self.store.consume_artifact_grant(str(record["grant_id"])):
            raise ArtifactTransferError("artifact grant was already used")
        destination = self._storage_path(str(record["storage_name"]))
        temporary = destination.with_suffix(".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        digest = hashlib.sha256(data).hexdigest()
        self.store.put_artifact(
            artifact_id=str(record["artifact_id"]), device_id=device_id,
            workspace_id=workspace_id, mime_type=mime_type, size=len(data),
            sha256=digest, storage_name=str(record["storage_name"]),
            created_at=float(self._clock()),
        )
        return {
            "artifact_id": record["artifact_id"], "mime_type": mime_type,
            "size": len(data), "sha256": digest,
        }

    def download(
        self, *, ticket: str, device_id: str, workspace_id: str,
    ) -> tuple[bytes, str]:
        record = self._verify(ticket, device_id, workspace_id, "download")
        if not self.store.consume_artifact_grant(str(record["grant_id"])):
            raise ArtifactTransferError("artifact grant was already used")
        path = self._storage_path(str(record["storage_name"]))
        if path.stat().st_size > int(record["max_bytes"]):
            raise ArtifactTransferError("stored artifact exceeds signed size limit")
        data = path.read_bytes()
        if len(data) > int(record["max_bytes"]):
            raise ArtifactTransferError("stored artifact exceeds signed size limit")
        return data, str(record["mime_type"])

    def _storage_path(self, storage_name: str) -> Path:
        path = (self.root / storage_name).resolve()
        if path.parent != self.root:
            raise ArtifactTransferError("artifact storage path is invalid")
        return path

    def _verify(
        self, ticket: str, device_id: str, workspace_id: str, operation: str
    ):
        claims = self._parse(ticket)
        record = self.store.artifact_grant(str(claims.get("gid", "")))
        if record is None or bool(record["used"]):
            raise ArtifactTransferError("artifact grant is invalid")
        expected = {
            "gid": record["grant_id"], "aid": record["artifact_id"],
            "did": record["device_id"], "wid": record["workspace_id"],
            "op": record["operation"], "mime": record["mime_type"],
            "max": record["max_bytes"], "exp": record["expires_at"],
        }
        if claims != expected:
            raise ArtifactTransferError("artifact grant claims mismatch")
        if device_id != record["device_id"] or workspace_id != record["workspace_id"]:
            raise ArtifactTransferError("artifact grant owner mismatch")
        if operation != record["operation"]:
            raise ArtifactTransferError("artifact grant operation mismatch")
        if float(self._clock()) >= float(record["expires_at"]):
            raise ArtifactTransferError("artifact grant expired")
        return record

    def _sign(self, claims: dict[str, object]) -> str:
        raw = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
        payload = base64.urlsafe_b64encode(raw).rstrip(b"=")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        return payload.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    def _parse(self, ticket: str) -> dict[str, object]:
        try:
            payload, signature = ticket.split(".", 1)
            expected = hmac.new(self._key, payload.encode(), hashlib.sha256).digest()
            actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
            if not hmac.compare_digest(expected, actual):
                raise ArtifactTransferError("artifact signature rejected")
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            claims = json.loads(raw)
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactTransferError("artifact ticket is invalid") from exc
        if not isinstance(claims, dict):
            raise ArtifactTransferError("artifact ticket is invalid")
        return claims


__all__ = ["ArtifactGrant", "ArtifactTransferError", "ArtifactTransferService"]
