"""Provider-neutral registry for canonical tool specifications."""

from __future__ import annotations

from mark.tools.contracts import ToolSpec
from mark.tools.errors import DuplicateToolError, UnknownToolError


class ToolRegistry:
    """Store and select canonical tools by their unique names."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Register ``spec``, rejecting an already registered name."""
        if not isinstance(spec, ToolSpec):
            raise TypeError("spec must be a ToolSpec")
        if spec.name in self._specs:
            raise DuplicateToolError(spec.name)
        self._specs[spec.name] = spec

    def unregister(self, name: str) -> None:
        """Remove ``name`` or raise when no such tool is registered."""
        if name not in self._specs:
            raise UnknownToolError(name)
        del self._specs[name]

    def get(self, name: str) -> ToolSpec:
        """Return the registered specification for ``name``."""
        try:
            return self._specs[name]
        except KeyError:
            raise UnknownToolError(name) from None

    def contains(self, name: str) -> bool:
        """Return whether ``name`` is registered."""
        return name in self._specs

    def list(self) -> tuple[ToolSpec, ...]:
        """Return all specifications ordered by canonical name."""
        return tuple(self._specs[name] for name in self.names())

    def names(self) -> tuple[str, ...]:
        """Return registered names in deterministic lexical order."""
        return tuple(sorted(self._specs))

    def select(
        self,
        *,
        capabilities: set[str] | None = None,
        scopes: set[str] | None = None,
    ) -> tuple[ToolSpec, ...]:
        """Return tools satisfying every requested capability and scope."""
        required_capabilities = capabilities or set()
        required_scopes = scopes or set()
        return tuple(
            spec
            for spec in self.list()
            if required_capabilities.issubset(spec.capabilities)
            and required_scopes.issubset(spec.scopes)
        )


__all__ = ["ToolRegistry"]
