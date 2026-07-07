"""ZOCRAM1 .zocr container — sealed GAC1 audio for the sovereign ear."""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zocr_zocram1.codec_gac1 import decode_chunks, encode_pcm, pcm_compression_ratio, shannon_entropy
from zocr_zocram1.envelope import seal_payload, unpack_envelope
from zocr_zocram1.spec import CODEC_ID, FLAG_COCHLEAR_SAFE, FLAG_SOVEREIGN_SEAL, FORMAT_ID, MAGIC

_HDR = struct.Struct("<4sBBHIIIIQII12s")
_IDX = struct.Struct("<IBBHHI I32s")


@dataclass
class Segment:
    segment_id: int
    kind: int  # 1=key 2=pred 3=silence 4=meta
    frame_start: int
    frame_count: int
    offset: int
    length: int
    digest: bytes
    payload: bytes = field(repr=False)
    entropy_h: float = 0.0


@dataclass
class ZOCRAMFile:
    sample_rate: int
    channels: int
    frame_samples: int
    frame_count: int
    meta: dict[str, Any]
    segments: list[Segment]

    @property
    def duration_s(self) -> float:
        return (self.frame_count * self.frame_samples) / max(self.sample_rate, 1)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _frame_kind(blob: bytes) -> int:
    if len(blob) < 5 or blob[:4] != b"GAC1":
        return 1
    return int(blob[4])


def _flags_from_profile(profile_name: str) -> int:
    flags = FLAG_SOVEREIGN_SEAL
    if profile_name in ("cochlear_safe", "binaural_safe", "patrol"):
        flags |= FLAG_COCHLEAR_SAFE
    return flags


def write_zocram(
    path: Path,
    pcm: bytes,
    *,
    sample_rate: int = 48000,
    channels: int = 2,
    profile_name: str = "binaural_safe",
    frame_samples: int = 1024,
    provenance_weave: str | None = None,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks, meta = encode_pcm(
        pcm,
        sample_rate=sample_rate,
        channels=channels,
        profile_name=profile_name,
        frame_samples=frame_samples,
        sovereign_ts=_ts(),
        provenance_weave=provenance_weave,
    )
    meta.setdefault("sovereign_time", {})["sealed_ts"] = meta.get("sovereign_time", {}).get("sealed_ts") or _ts()
    if provenance_weave:
        meta["provenance_weave"] = provenance_weave
    else:
        meta["provenance_weave"] = hashlib.sha256(pcm[: min(len(pcm), 65536)]).hexdigest()[:16]

    segments: list[Segment] = []
    meta_blob = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    sealed_meta = seal_payload(meta_blob, codec=1, flags=1)
    segments.append(
        Segment(
            0, 4, 0, 0, 0, len(sealed_meta),
            hashlib.sha256(sealed_meta).digest(),
            sealed_meta,
            shannon_entropy(sealed_meta),
        )
    )

    for i, chunk in enumerate(chunks):
        sealed = seal_payload(chunk, codec=1, flags=0)
        kind = _frame_kind(chunk)
        segments.append(
            Segment(
                i + 1,
                kind,
                i,
                1,
                0,
                len(sealed),
                hashlib.sha256(sealed).digest(),
                sealed,
                shannon_entropy(sealed),
            )
        )

    header_size = _HDR.size
    index_size = _IDX.size * len(segments)
    payload_offset = header_size + index_size
    offset = payload_offset
    for seg in segments:
        seg.offset = offset
        offset += seg.length

    index = bytearray()
    for seg in segments:
        index.extend(
            _IDX.pack(
                seg.segment_id,
                seg.kind,
                0,
                seg.frame_start,
                seg.frame_count,
                seg.offset,
                seg.length,
                seg.digest,
            )
        )

    flags = _flags_from_profile(profile_name)
    header = _HDR.pack(
        MAGIC,
        1,
        1,
        flags,
        sample_rate,
        channels,
        frame_samples,
        len(chunks),
        len(sealed_meta),
        payload_offset,
        len(segments),
        b"\x00" * 12,
    )

    with path.open("wb") as f:
        f.write(header)
        f.write(index)
        for seg in segments:
            f.write(seg.payload)

    ratio = pcm_compression_ratio(pcm, chunks)
    return {
        "ok": True,
        "path": str(path),
        "format": FORMAT_ID,
        "codec": CODEC_ID,
        "profile": profile_name,
        "sample_rate": sample_rate,
        "channels": channels,
        "frame_count": len(chunks),
        "duration_s": round(len(chunks) * frame_samples / sample_rate, 3),
        "compression_vs_pcm": ratio,
        "entropy_mean": meta.get("entropy_mean"),
        "sovereign_time": meta.get("sovereign_time"),
        "provenance_weave": meta.get("provenance_weave"),
        "bytes": path.stat().st_size,
    }


def read_zocram(path: Path) -> ZOCRAMFile:
    data = path.read_bytes()
    if len(data) < _HDR.size:
        raise ValueError("zocram_truncated")
    magic, ver, codec, flags, sample_rate, channels, frame_samples, frame_count, meta_len, payload_off, seg_count, _rsv = _HDR.unpack(
        data[: _HDR.size]
    )
    if magic != MAGIC:
        raise ValueError("invalid_zocram_magic")

    index_start = _HDR.size
    index_end = index_start + _IDX.size * seg_count
    segments: list[Segment] = []
    for i in range(seg_count):
        off = index_start + i * _IDX.size
        seg_id, kind, _pad, frame_start, frame_count_seg, offset, length, digest = _IDX.unpack(data[off : off + _IDX.size])
        payload = data[offset : offset + length]
        segments.append(Segment(seg_id, kind, frame_start, frame_count_seg, offset, length, digest, payload))

    meta: dict[str, Any] = {}
    if segments and segments[0].kind == 4:
        unpacked = unpack_envelope(segments[0].payload)
        if unpacked:
            meta = json.loads(unpacked[0].decode("utf-8"))

    return ZOCRAMFile(sample_rate, channels, frame_samples, frame_count, meta, segments)


def decode_zocram(path: Path) -> tuple[bytes, dict[str, Any]]:
    zf = read_zocram(path)
    chunks: list[bytes] = []
    for seg in zf.segments:
        if seg.kind == 4:
            continue
        unpacked = unpack_envelope(seg.payload)
        if not unpacked:
            raise ValueError(f"segment_seal_failed:{seg.segment_id}")
        chunks.append(unpacked[0])
    pcm = decode_chunks(
        chunks,
        sample_rate=zf.sample_rate,
        channels=zf.channels,
        frame_samples=zf.frame_samples,
    )
    return pcm, zf.meta


def verify_zocram(path: Path) -> dict[str, Any]:
    try:
        zf = read_zocram(path)
    except (OSError, ValueError) as exc:
        return {"ok": False, "path": str(path), "error": str(exc)}

    chain_prev: str | None = None
    entropies: list[float] = []
    for seg in zf.segments:
        unpacked = unpack_envelope(seg.payload)
        if not unpacked:
            return {"ok": False, "path": str(path), "error": f"seal_invalid_segment_{seg.segment_id}"}
        _payload, env = unpacked
        if hashlib.sha256(seg.payload).digest() != seg.digest:
            return {"ok": False, "path": str(path), "error": f"index_digest_mismatch_{seg.segment_id}"}
        entropies.append(shannon_entropy(seg.payload))
        chain_prev = env.get("sha256")

    meta = zf.meta
    sovereign = meta.get("sovereign_time") or {}
    return {
        "ok": True,
        "path": str(path),
        "format": FORMAT_ID,
        "codec": CODEC_ID,
        "profile": meta.get("profile"),
        "frame_count": zf.frame_count,
        "duration_s": round(zf.duration_s, 3),
        "entropy_mean": meta.get("entropy_mean"),
        "entropy_verified_mean": round(sum(entropies) / max(len(entropies), 1), 4),
        "sovereign_time": sovereign,
        "provenance_weave": meta.get("provenance_weave"),
        "last_seal": chain_prev,
        "cochlear_limit_db": meta.get("cochlear_limit_db"),
    }


def pack_pcm_file(
    src: Path,
    dest: Path,
    *,
    sample_rate: int = 48000,
    channels: int = 2,
    profile_name: str = "binaural_safe",
) -> dict[str, Any]:
    pcm = src.read_bytes()
    return write_zocram(
        dest,
        pcm,
        sample_rate=sample_rate,
        channels=channels,
        profile_name=profile_name,
        provenance_weave=hashlib.sha256(pcm).hexdigest()[:24],
    )