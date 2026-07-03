"""Signal intelligence — encoded carriers, interference, deceit, accurate identification."""
from __future__ import annotations

import math
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shannon(data: bytes) -> float:
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
    return h


def _pcm_stats(pcm: bytes, channels: int = 2) -> dict[str, Any]:
    if len(pcm) < 4:
        return {"samples": 0, "peak": 0, "rms": 0.0, "zcr": 0.0, "entropy": 0.0}
    samples: list[int] = []
    for i in range(0, len(pcm) - 1, 2):
        samples.append(struct.unpack_from("<h", pcm, i)[0])
    if not samples:
        return {"samples": 0, "peak": 0, "rms": 0.0, "zcr": 0.0, "entropy": 0.0}
    peak = max(abs(s) for s in samples)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    zcr = 0
    for a, b in zip(samples, samples[1:]):
        if (a >= 0) != (b >= 0):
            zcr += 1
    zcr_rate = zcr / max(len(samples) - 1, 1)
    left = samples[0::channels] if channels > 1 else samples
    right = samples[1::channels] if channels > 1 and len(samples) > 1 else samples
    phase_decoh = 0.0
    if channels > 1 and len(left) == len(right) and left:
        diffs = [abs(a - b) for a, b in zip(left, right)]
        phase_decoh = sum(diffs) / len(diffs) / 32768.0
    return {
        "samples": len(samples),
        "peak": peak,
        "peak_db": round(20 * math.log10(max(peak, 1) / 32768.0), 2),
        "rms": round(rms, 2),
        "zcr": round(zcr_rate, 4),
        "entropy": round(_shannon(pcm[: min(len(pcm), 8192)]), 4),
        "phase_decoherence": round(phase_decoh, 4),
    }


def score_encoded_signal(*, evidence: dict[str, Any], pcm: bytes | None = None) -> dict[str, Any]:
    """Detect steganographic / FSK / ultrasonic data carriers in audio lane."""
    ev = evidence or {}
    stats = _pcm_stats(pcm, int(ev.get("channels", 2))) if pcm else {}
    zcr = float(ev.get("zcr", stats.get("zcr", 0.0)))
    entropy = float(ev.get("entropy", stats.get("entropy", 0.0)))
    ultrasonic = bool(ev.get("ultrasonic_burst", zcr > 0.42 and entropy > 7.2))
    narrowband = bool(ev.get("narrowband_carrier", entropy < 4.5 and zcr < 0.08))
    fsk_hint = bool(ev.get("fsk_pattern", zcr > 0.28 and 5.5 < entropy < 7.5))
    score = 0.0
    markers: list[str] = []
    if ultrasonic:
        score += 0.35
        markers.append("ultrasonic_carrier")
    if narrowband:
        score += 0.25
        markers.append("narrowband_tone")
    if fsk_hint:
        score += 0.30
        markers.append("fsk_like")
    if ev.get("gac1_entropy_mean") and float(ev["gac1_entropy_mean"]) > 7.8:
        score += 0.15
        markers.append("high_packed_entropy")
    score = min(1.0, score)
    ok = score < 0.55
    return {
        "id": "encoded_signal",
        "score": round(score, 3),
        "ok": ok,
        "markers": markers,
        "stats": stats,
    }


def score_mixed_interference(*, evidence: dict[str, Any], sources: list[dict[str, Any]] | None = None, pcm: bytes | None = None) -> dict[str, Any]:
    """Mixed signals, RF bleed, duplicate ghosts, phase fighting."""
    ev = evidence or {}
    srcs = sources or []
    stats = _pcm_stats(pcm, int(ev.get("channels", 2))) if pcm else {}
    phase = float(ev.get("phase_decoherence", stats.get("phase_decoherence", 0.0)))
    snr = float(ev.get("snr_db", ev.get("snr", 18.0)))
    rf_bleed = bool(ev.get("rf_bleed", False))
    ghost = bool(ev.get("ghost_duplicate", len(srcs) >= 2 and all(s.get("level_db") for s in srcs)))
    score = 1.0
    markers: list[str] = []
    if phase > 0.35:
        score -= 0.25
        markers.append("phase_fight")
    if snr < 8.0:
        score -= 0.30
        markers.append("low_snr")
    if rf_bleed:
        score -= 0.20
        markers.append("rf_interference")
    if ghost:
        score -= 0.15
        markers.append("ghost_duplicate")
    if len(srcs) >= 3:
        bearings = [s.get("bearing_deg") for s in srcs if s.get("bearing_deg") is not None]
        if bearings and max(bearings) - min(bearings) > 120:
            score -= 0.20
            markers.append("incoherent_mix")
    score = max(0.0, min(1.0, score))
    ok = score >= 0.62
    return {
        "id": "mixed_interference",
        "score": round(score, 3),
        "ok": ok,
        "markers": markers,
        "snr_db": snr,
        "phase_decoherence": phase,
    }


def score_deceit(*, evidence: dict[str, Any], existence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Composite deceit — ventriloquism + spoof + provenance mismatch."""
    ev = evidence or {}
    ex = existence or {}
    mouth = float(ev.get("mouth_correlation", 0.75))
    provenance_ok = ev.get("provenance_weave_ok", True) is not False
    sovereign_ok = ev.get("sovereign_time_ok", True) is not False
    replay = bool(ev.get("replay_detected", False))
    existence_corr = float(ex.get("correlation", ev.get("existence_correlation", 0.8)))
    score = mouth * 0.35 + existence_corr * 0.35
    if provenance_ok:
        score += 0.15
    if sovereign_ok:
        score += 0.15
    if replay:
        score *= 0.4
    markers: list[str] = []
    if mouth < 0.55:
        markers.append("mouth_deceit")
    if not provenance_ok:
        markers.append("provenance_lie")
    if not sovereign_ok:
        markers.append("time_desync")
    if replay:
        markers.append("replay_spoof")
    if existence_corr < 0.6:
        markers.append("existence_mismatch")
    ok = score >= 0.68 and not replay and provenance_ok and sovereign_ok
    return {
        "id": "deceit_composite",
        "score": round(min(1.0, score), 3),
        "ok": ok,
        "markers": markers,
    }


def identify_sound(
    *,
    evidence: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    existence: dict[str, Any] | None = None,
    pcm: bytes | None = None,
    pcm_hex: str | None = None,
) -> dict[str, Any]:
    """Accurate sound identification with encoded/interference/deceit gates."""
    ev = dict(evidence or {})
    if pcm_hex and not pcm:
        pcm = bytes.fromhex(pcm_hex.replace(" ", ""))
    if pcm and "peak_db" not in ev:
        ev.update(_pcm_stats(pcm, int(ev.get("channels", 2))))

    encoded = score_encoded_signal(evidence=ev, pcm=pcm)
    mixed = score_mixed_interference(evidence=ev, sources=sources, pcm=pcm)
    deceit = score_deceit(evidence=ev, existence=existence)

    label = "unknown"
    confidence = 0.5
    if encoded["ok"] and mixed["ok"] and deceit["ok"]:
        if ev.get("speech_present") or (ev.get("rms", 0) > 800 and ev.get("zcr", 0) < 0.2):
            label, confidence = "speech_verified", 0.82
        elif ev.get("zcr", 0) < 0.05 and ev.get("peak", 0) < 500:
            label, confidence = "ambient_quiet", 0.78
        elif len(sources or []) >= 2 and mixed["score"] > 0.8:
            label, confidence = "multi_source_resolved", 0.75
        else:
            label, confidence = "clear_audio", 0.72
    elif not encoded["ok"]:
        label, confidence = "encoded_signal_detected", encoded["score"]
    elif not mixed["ok"]:
        label, confidence = "interference_mix", 1.0 - mixed["score"]
    elif not deceit["ok"]:
        label, confidence = "deceit_pattern", 1.0 - deceit["score"]

    ok = encoded["ok"] and mixed["ok"] and deceit["ok"]
    return {
        "ok": ok,
        "schema": "zocr-ear-signal-identify/v1",
        "updated": _ts(),
        "identification": label,
        "confidence": round(confidence, 4),
        "encoded_signal": encoded,
        "mixed_interference": mixed,
        "deceit": deceit,
        "accurate": ok,
        "forward": ok,
        "speak": f"Identified: {label}" if ok else f"Veritas holds — {label}",
    }