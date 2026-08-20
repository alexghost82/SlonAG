"""Bounded RFC 6455 frame codec for the Gateway socket adapter."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gateway.contracts import MAX_ENVELOPE_BYTES, GatewayProtocolError


@dataclass(frozen=True)
class WebSocketFrame:
    opcode: int
    payload: bytes


def decode_client_frame(raw: bytes) -> WebSocketFrame:
    if len(raw) < 2:
        raise GatewayProtocolError("malformed_frame", "Incomplete WebSocket frame.")
    first, second = raw[0], raw[1]
    if not first & 0x80:
        raise GatewayProtocolError("malformed_frame", "Fragmented frames are unsupported.")
    opcode = first & 0x0F
    if opcode not in {0x1, 0x8, 0x9, 0xA}:
        raise GatewayProtocolError("malformed_frame", "Unsupported WebSocket opcode.")
    if not second & 0x80:
        raise GatewayProtocolError("malformed_frame", "Client frames must be masked.")
    length, offset = second & 0x7F, 2
    if length == 126:
        if len(raw) < 4:
            raise GatewayProtocolError("malformed_frame", "Incomplete frame length.")
        length, offset = struct.unpack("!H", raw[2:4])[0], 4
    elif length == 127:
        if len(raw) < 10:
            raise GatewayProtocolError("malformed_frame", "Incomplete frame length.")
        length, offset = struct.unpack("!Q", raw[2:10])[0], 10
    if opcode in {0x8, 0x9, 0xA} and length > 125:
        raise GatewayProtocolError("malformed_frame", "WebSocket control frame is too large.")
    if length > MAX_ENVELOPE_BYTES:
        raise GatewayProtocolError("oversized_frame", "WebSocket frame is too large.")
    end = offset + 4 + length
    if len(raw) != end:
        raise GatewayProtocolError("malformed_frame", "WebSocket frame size mismatch.")
    mask = raw[offset : offset + 4]
    payload = bytes(
        value ^ mask[index % 4]
        for index, value in enumerate(raw[offset + 4 : end])
    )
    return WebSocketFrame(opcode, payload)


def encode_server_frame(payload: bytes, *, opcode: int = 0x1) -> bytes:
    if opcode in {0x8, 0x9, 0xA} and len(payload) > 125:
        raise GatewayProtocolError("malformed_frame", "WebSocket control frame is too large.")
    if len(payload) > MAX_ENVELOPE_BYTES:
        raise GatewayProtocolError("oversized_frame", "WebSocket frame is too large.")
    header = bytearray([0x80 | opcode])
    if len(payload) < 126:
        header.append(len(payload))
    elif len(payload) <= 0xFFFF:
        header.extend((126, *struct.pack("!H", len(payload))))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", len(payload)))
    return bytes(header) + payload


__all__ = ["WebSocketFrame", "decode_client_frame", "encode_server_frame"]
