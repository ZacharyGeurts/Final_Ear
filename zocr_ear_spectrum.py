"""Auditory spectrum analysis — FFT bins from desktop/monitor capture for panel visuals."""
from __future__ import annotations

import math
import struct
from datetime import datetime, timezone
from typing import Any

_ROOT = __import__("pathlib").Path(__file__).resolve().parent


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pcm_to_samples(pcm: bytes, channels: int = 2) -> list[float]:
    if len(pcm) < 2:
        return []
    n = len(pcm) // 2
    raw = struct.unpack(f"<{n}h", pcm[: n * 2])
    if channels > 1:
        left = [raw[i] / 32768.0 for i in range(0, len(raw), channels)]
        return left
    return [s / 32768.0 for s in raw]


def _dft_bins(samples: list[float], *, bins: int = 64, sample_rate: int = 48000) -> list[dict[str, Any]]:
    if not samples:
        return [{"hz": 0.0, "db": -72.0, "band": i} for i in range(bins)]
    n = min(len(samples), 4096)
    chunk = samples[:n]
    nyquist = sample_rate / 2
    out: list[dict[str, Any]] = []
    for b in range(bins):
        f = (b + 0.5) * nyquist / bins
        re = 0.0
        im = 0.0
        for i, x in enumerate(chunk):
            phase = -2.0 * math.pi * f * i / sample_rate
            re += x * math.cos(phase)
            im += x * math.sin(phase)
        mag = math.sqrt(re * re + im * im) / max(len(chunk), 1)
        db = round(20 * math.log10(max(mag, 1e-9)), 2)
        out.append({"hz": round(f, 1), "db": db, "band": b})
    return out


def analyze_pcm_spectrum(
    pcm: bytes,
    *,
    sample_rate: int = 48000,
    channels: int = 2,
    profile_id: str | None = None,
) -> dict[str, Any]:
    samples = _pcm_to_samples(pcm, channels)
    bins = _dft_bins(samples, sample_rate=sample_rate)
    peak = max(bins, key=lambda x: x["db"]) if bins else {}
    rms = 0.0
    if samples:
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    rms_db = round(20 * math.log10(max(rms, 1e-9)), 2)
    profile: dict[str, Any] = {}
    if profile_id:
        try:
            from zocr_ear import load_doctrine
            profile = (load_doctrine().get("profiles") or {}).get(profile_id, {})
        except ImportError:
            pass
    range_hz = profile.get("range_hz", [20, 20000])
    return {
        "ok": True,
        "schema": "zocr-auditory-spectrum-analyze/v1",
        "updated": _ts(),
        "profile": profile_id,
        "label": profile.get("label", profile_id or "live"),
        "range_hz": range_hz,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "rms_db": rms_db,
        "peak_hz": peak.get("hz"),
        "peak_db": peak.get("db"),
        "bins": bins,
        "band_count": len(bins),
    }


def capture_and_analyze(*, seconds: float = 0.5, profile_id: str | None = None) -> dict[str, Any]:
    try:
        from zocr_desktop_audio import capture_monitor_chunk, desktop_audio_status
        from zocr_ear import active_profile
    except ImportError as exc:
        return {"ok": False, "error": str(exc), "schema": "zocr-auditory-spectrum-analyze/v1"}
    pid = profile_id or active_profile()
    cap = capture_monitor_chunk(seconds=seconds)
    pcm_hex = cap.get("pcm_hex") or ""
    pcm = bytes.fromhex(pcm_hex) if pcm_hex else b""
    spec = analyze_pcm_spectrum(
        pcm,
        sample_rate=int(cap.get("sample_rate_hz") or 48000),
        channels=int(cap.get("channels") or 2),
        profile_id=pid,
    )
    desk = desktop_audio_status()
    spec["capture"] = {
        "captured": cap.get("captured"),
        "backend": cap.get("backend"),
        "level_db": cap.get("level_db"),
        "seconds": seconds,
    }
    spec["desktop"] = {
        "source_count": desk.get("source_count"),
        "sources": (desk.get("sources") or [])[:8],
    }
    return spec


def spectrum_doctrine() -> dict[str, Any]:
    try:
        from zocr_ear import load_doctrine, list_profiles, active_profile
    except ImportError:
        return {"schema": "zocr-auditory-spectrum/v1", "profiles": []}
    doc = load_doctrine()
    return {
        "schema": "zocr-auditory-spectrum-doctrine/v1",
        "title": "Auditory spectrum — cochlea engine",
        "engine": doc.get("engine", "cochlea_v1"),
        "doctrine": doc.get("doctrine"),
        "profiles": list_profiles(),
        "active": active_profile(),
    }