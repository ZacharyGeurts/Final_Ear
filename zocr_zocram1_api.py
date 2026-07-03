"""ZOCRAM1 API surface for Queen earball and stoard."""
from __future__ import annotations

import hashlib
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zocr_zocram1.container import decode_zocram, pack_pcm_file, verify_zocram, write_zocram
from zocr_zocram1.spec import CODEC_ID, FORMAT_ID, load_spec


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gac1_status() -> dict[str, Any]:
    spec = load_spec()
    return {
        "schema": "zocr-gac1-status/v1",
        "format": FORMAT_ID,
        "codec": CODEC_ID,
        "rule": spec.get("rule") or "Better than naked PCM",
        "beats_pcm": spec.get("beats_pcm") or [],
        "profiles": list((spec.get("profiles") or {}).keys()),
        "extension": spec.get("container_extension") or ".zocr",
        "bus_slots": spec.get("bus_slots") or [57, 58, 59],
    }


def pack_audio(
    *,
    pcm_path: str | None = None,
    dest_path: str | None = None,
    profile: str = "binaural_safe",
    sample_rate: int = 48000,
    channels: int = 2,
    pcm_hex: str | None = None,
) -> dict[str, Any]:
    if pcm_hex:
        pcm = bytes.fromhex(pcm_hex.replace(" ", ""))
        if not dest_path:
            return {"ok": False, "error": "missing_dest_path"}
        out = write_zocram(
            Path(dest_path),
            pcm,
            sample_rate=sample_rate,
            channels=channels,
            profile_name=profile,
            provenance_weave=hashlib.sha256(pcm).hexdigest()[:24],
        )
        out["schema"] = "zocr-pack-audio/v1"
        return out
    if not pcm_path or not dest_path:
        return {"ok": False, "error": "missing_pcm_or_dest", "schema": "zocr-pack-audio/v1"}
    out = pack_pcm_file(Path(pcm_path), Path(dest_path), sample_rate=sample_rate, channels=channels, profile_name=profile)
    out["schema"] = "zocr-pack-audio/v1"
    return out


def verify_audio(path: str) -> dict[str, Any]:
    out = verify_zocram(Path(path))
    out["schema"] = "zocr-verify-audio/v1"
    out["verified_at"] = _ts()
    return out


def unpack_audio(path: str, dest: str | None = None) -> dict[str, Any]:
    pcm, meta = decode_zocram(Path(path))
    result: dict[str, Any] = {
        "ok": True,
        "schema": "zocr-unpack-audio/v1",
        "bytes": len(pcm),
        "meta": meta,
        "sha256": hashlib.sha256(pcm).hexdigest(),
    }
    if dest:
        Path(dest).write_bytes(pcm)
        result["dest"] = dest
    else:
        result["pcm_hex_prefix"] = pcm[:64].hex()
    return result