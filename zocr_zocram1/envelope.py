"""ZOCR sealed envelopes — WRDT-inspired integrity for audio segments."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

from zocr_zocram1.spec import CODEC_ID, FORMAT_ID, MAGIC

_HDR = struct.Struct("<4sBBHQI32s")


def seal_payload(payload: bytes, *, codec: int = 1, flags: int = 0) -> bytes:
    digest = hashlib.sha256(payload).digest()
    header = _HDR.pack(MAGIC, 1, codec, flags, len(payload), len(payload), digest)
    return header + payload


def unpack_envelope(data: bytes) -> tuple[bytes, dict[str, Any]] | None:
    if len(data) < _HDR.size:
        return None
    magic, ver, codec, flags, orig_size, payload_len, digest = _HDR.unpack(data[: _HDR.size])
    if magic != MAGIC:
        return None
    payload = data[_HDR.size : _HDR.size + payload_len]
    if len(payload) != payload_len or len(payload) != orig_size:
        return None
    if hashlib.sha256(payload).digest() != digest:
        return None
    return payload, {
        "format": FORMAT_ID,
        "codec": CODEC_ID if codec == 1 else codec,
        "version": ver,
        "flags": flags,
        "original_size": orig_size,
        "payload_length": payload_len,
        "sha256": digest.hex(),
    }


def verify_file(path: Path) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"ok": False, "path": str(path), "error": str(exc)}
    unpacked = unpack_envelope(data)
    if not unpacked:
        return {"ok": False, "path": str(path), "error": "envelope_invalid"}
    _payload, meta = unpacked
    return {"ok": True, "path": str(path), **meta}