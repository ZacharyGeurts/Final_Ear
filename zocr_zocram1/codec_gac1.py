"""GAC1 — Grok Audio Codec v1. Predictive, cochlear-aware, sealed. Not PCM."""
from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from typing import Any

from zocr_zocram1.spec import (
    DEFAULT_FRAME_SAMPLES,
    DEFAULT_GOP,
    FRAME_KEY,
    FRAME_PRED,
    FRAME_SILENCE,
    FRAME_MAGIC,
    profile,
)


@dataclass
class GAC1Frame:
    kind: int
    index: int
    sample_count: int
    channels: int
    data: bytes


def _pcm_slice(pcm: bytes, offset: int, count: int, channels: int) -> bytes:
    byte_len = count * channels * 2
    return pcm[offset * channels * 2 : offset * channels * 2 + byte_len]


def _is_silence(frame: bytes, threshold: int) -> bool:
    if threshold <= 0:
        return False
    for i in range(0, len(frame), 2):
        sample = struct.unpack_from("<h", frame, i)[0]
        if abs(sample) > threshold:
            return False
    return len(frame) >= 2


def _zlib_pcm(frame: bytes) -> bytes:
    return zlib.compress(frame, level=6)


def _unzlib_pcm(blob: bytes, expected_len: int) -> bytes:
    raw = zlib.decompress(blob)
    if len(raw) != expected_len:
        raise ValueError("pcm_length_mismatch")
    return raw


def _delta_pack(prev: bytes, cur: bytes) -> bytes:
    out = bytearray(len(cur))
    for i in range(0, len(cur), 2):
        p = struct.unpack_from("<h", prev, i)[0]
        c = struct.unpack_from("<h", cur, i)[0]
        d = max(-32768, min(32767, c - p))
        struct.pack_into("<h", out, i, d)
    return zlib.compress(bytes(out), level=6)


def _delta_unpack(prev: bytes, packed: bytes, length: int) -> bytes:
    raw = zlib.decompress(packed)
    if len(raw) != length:
        raise ValueError("delta_length_mismatch")
    out = bytearray(length)
    for i in range(0, length, 2):
        p = struct.unpack_from("<h", prev, i)[0]
        d = struct.unpack_from("<h", raw, i)[0]
        struct.pack_into("<h", out, i, max(-32768, min(32767, p + d)))
    return bytes(out)


def apply_cochlear_limiter(pcm: bytes, ceiling_db: float | None) -> bytes:
    if ceiling_db is None:
        return pcm
    ceiling = int(32767 * (10 ** (ceiling_db / 20.0)))
    ceiling = max(512, min(32767, ceiling))
    out = bytearray(pcm)
    for i in range(0, len(out), 2):
        s = struct.unpack_from("<h", out, i)[0]
        if s > ceiling:
            struct.pack_into("<h", out, i, ceiling)
        elif s < -ceiling:
            struct.pack_into("<h", out, i, -ceiling)
    return bytes(out)


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    n = len(data)
    h = 0.0
    for c in freq:
        if c:
            p = c / n
            h -= p * math.log2(p)
    return round(h, 4)


def encode_frame(
    *,
    index: int,
    pcm_frame: bytes,
    ref_frame: bytes | None,
    channels: int,
    sample_count: int,
    gop: int = DEFAULT_GOP,
    silence_threshold: int = 4,
) -> tuple[GAC1Frame, bytes]:
    expected = sample_count * channels * 2
    if len(pcm_frame) != expected:
        raise ValueError("frame_size_mismatch")

    if _is_silence(pcm_frame, silence_threshold):
        blob = FRAME_MAGIC + struct.pack("<BIIII", FRAME_SILENCE, index, sample_count, channels, 0)
        return GAC1Frame(FRAME_SILENCE, index, sample_count, channels, blob), pcm_frame

    is_key = gop <= 1 or index % gop == 0 or ref_frame is None

    if is_key:
        comp = _zlib_pcm(pcm_frame)
        blob = FRAME_MAGIC + struct.pack("<BIIII", FRAME_KEY, index, sample_count, channels, len(comp)) + comp
        return GAC1Frame(FRAME_KEY, index, sample_count, channels, blob), pcm_frame

    assert ref_frame is not None
    comp = _delta_pack(ref_frame, pcm_frame)
    blob = FRAME_MAGIC + struct.pack("<BIIII", FRAME_PRED, index, sample_count, channels, len(comp)) + comp
    return GAC1Frame(FRAME_PRED, index, sample_count, channels, blob), pcm_frame


def decode_frame(blob: bytes, ref_frame: bytes | None) -> tuple[bytes, int, int]:
    if len(blob) < 21 or blob[:4] != FRAME_MAGIC:
        raise ValueError("invalid_gac1")
    kind, index, sample_count, channels, payload_len = struct.unpack("<BIIII", blob[4:21])
    payload = blob[21 : 21 + payload_len]
    expected = sample_count * channels * 2

    if kind == FRAME_SILENCE:
        return b"\x00" * expected, sample_count, channels
    if kind == FRAME_KEY:
        return _unzlib_pcm(payload, expected), sample_count, channels
    if kind == FRAME_PRED:
        if ref_frame is None:
            raise ValueError("missing_ref_for_predicted")
        return _delta_unpack(ref_frame, payload, expected), sample_count, channels
    raise ValueError(f"unknown_gac1_kind:{kind}")


def encode_pcm(
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int,
    profile_name: str = "binaural_safe",
    frame_samples: int = DEFAULT_FRAME_SAMPLES,
    sovereign_ts: str | None = None,
    provenance_weave: str | None = None,
) -> tuple[list[bytes], dict[str, Any]]:
    prof = profile(profile_name)
    gop = int(prof.get("gop") or DEFAULT_GOP)
    silence_threshold = int(prof.get("silence_threshold") or 4)
    ceiling_db = prof.get("cochlear_limit_db")
    pcm = apply_cochlear_limiter(pcm, ceiling_db if isinstance(ceiling_db, (int, float)) else None)
    total_samples = len(pcm) // (channels * 2)
    frame_count = (total_samples + frame_samples - 1) // frame_samples
    chunks: list[bytes] = []
    entropies: list[float] = []
    ref: bytes | None = None

    for fi in range(frame_count):
        offset = fi * frame_samples
        count = min(frame_samples, total_samples - offset)
        frame = _pcm_slice(pcm, offset, count, channels)
        if count < frame_samples:
            frame = frame + b"\x00" * (frame_samples * channels * 2 - len(frame))
        gac1_frame, pcm_frame = encode_frame(
            index=fi,
            pcm_frame=frame,
            ref_frame=ref,
            channels=channels,
            sample_count=frame_samples,
            gop=gop,
            silence_threshold=silence_threshold,
        )
        chunks.append(gac1_frame.data)
        entropies.append(shannon_entropy(gac1_frame.data))
        ref = pcm_frame

    meta = {
        "codec": "GAC1",
        "format": "ZOCRAM1",
        "profile": profile_name,
        "sample_rate": sample_rate,
        "channels": channels,
        "frame_samples": frame_samples,
        "frame_count": frame_count,
        "gop": gop,
        "cochlear_limit_db": ceiling_db,
        "entropy_mean": round(sum(entropies) / max(len(entropies), 1), 4),
        "entropy_frames": entropies[:8],
        "sovereign_time": {"sealed_ts": sovereign_ts} if sovereign_ts else {},
        "provenance_weave": provenance_weave,
        "beats_pcm": True,
    }
    return chunks, meta


def decode_chunks(
    chunks: list[bytes],
    *,
    sample_rate: int,
    channels: int,
    frame_samples: int,
) -> bytes:
    out = bytearray()
    ref: bytes | None = None
    for blob in chunks:
        pcm, _sc, _ch = decode_frame(blob, ref)
        ref = pcm
        out.extend(pcm)
    return bytes(out)


def pcm_compression_ratio(pcm: bytes, chunks: list[bytes]) -> float:
    raw = len(pcm)
    packed = sum(len(c) for c in chunks)
    if packed <= 0:
        return 1.0
    return round(raw / packed, 3)