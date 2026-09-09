"""Authenticated Slon Gateway — the only remote security boundary for first-party iOS.

``server/*`` is the local desktop Control API (legacy ``/v1`` listener). It must
stay loopback/LAN and is not a substitute for this Gateway. Do not weaken
TLS, pairing, Ed25519 proofs, pinning, authz, workspace isolation, rate
limits, replay, nonce, or sequence checks here.
"""

from gateway.contracts import GatewayEnvelope, GatewayProtocolError

__all__ = ["GatewayEnvelope", "GatewayProtocolError"]
