"""Secure eye↔ear fusion — sovereign time, neural path, accurate identification."""
from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_SG = _ROOT.parent


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_eye_neural():
    fe = Path(os.environ.get("FINAL_EYE_ROOT", _SG / "Final_Eye"))
    spec = importlib.util.spec_from_file_location("eye_neural", fe / "zocr_neural_assist.py")
    if not spec or not spec.loader:
        raise ImportError("eye_neural_missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def secure_neural_path(
    *,
    evidence: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    existence: dict[str, Any] | None = None,
    localization: dict[str, Any] | None = None,
    pcm_hex: str | None = None,
    image_path: str | None = None,
    require_sync: bool = True,
) -> dict[str, Any]:
    """
    Full secure path: sovereign time → sync → signal intel → truth → ear NN → eye NN → quorum.
    Never desync: fusion fails closed when eye/ear mono_ns diverge.
    """
    from zocr_sovereign_time import load_eye_sovereign_mono, seal_ear_tick, sovereign_time_status, verify_eye_ear_sync
    from zocr_ear_signal_intel import identify_sound
    from zocr_ear_truth import apply_truth_filters
    from zocr_neural_assist import analyze_audio, neural_assist_status

    ear_tick = seal_ear_tick(reason="secure_identify")
    ear_mono = ear_tick.get("sealed_mono_ns")
    eye_mono = load_eye_sovereign_mono()

    sync = verify_eye_ear_sync(eye_mono_ns=eye_mono, ear_mono_ns=ear_mono)
    if require_sync and not sync.get("ok"):
        return {
            "ok": False,
            "schema": "zocr-secure-neural-path/v1",
            "error": "sovereign_desync",
            "sync": sync,
            "ear_tick": ear_tick,
            "speak": sync.get("speak"),
        }

    ev = dict(evidence or {})
    ev["sovereign_time_ok"] = ear_tick.get("ok", True)
    ev["sealed_mono_ns"] = ear_mono
    ev["sealed_ts"] = ear_tick.get("sealed_ts")

    signal_id = identify_sound(
        evidence=ev,
        sources=sources,
        existence=existence,
        pcm_hex=pcm_hex,
    )

    truth = apply_truth_filters(
        evidence=ev,
        sources=sources,
        peak_db=ev.get("peak_db"),
        existence=existence,
    )

    ear_ctx = {
        "evidence": ev,
        "localization": localization or {},
        "sources": sources or [],
        "existence_correlation": (existence or {}).get("correlation", 0.8),
        "signal_identification": signal_id.get("identification"),
        "encoded_ok": (signal_id.get("encoded_signal") or {}).get("ok"),
        "interference_ok": (signal_id.get("mixed_interference") or {}).get("ok"),
    }

    eye_cross: dict[str, Any] = {}
    eye_out: dict[str, Any] = {"ok": False, "note": "eye_unavailable"}
    try:
        eye_mod = _load_eye_neural()
        eye_st = eye_mod.neural_assist_status()
        if eye_st.get("seal_ok") is not False:
            ear_ctx["eye_cross"] = {}
            ear_first = analyze_audio(context=ear_ctx)
            eye_ctx = {
                "bearing_deg": (localization or {}).get("bearing_deg"),
                "mouth_viseme": ev.get("mouth_correlation", 0.8),
                "ear_cross": {
                    "assault_burst": ear_first.get("top_label") == "assault_hint",
                    "ventriloquism": ear_first.get("top_label") == "ventriloquism_hint",
                    "bearing_deg": (localization or {}).get("bearing_deg"),
                    "encoded_signal": signal_id.get("identification") == "encoded_signal_detected",
                    "interference_mix": signal_id.get("identification") == "interference_mix",
                },
            }
            eye_out = eye_mod.analyze_wired(context=eye_ctx, image_path=image_path)
            eye_cross = eye_out.get("to_ear") or {}
            ear_ctx["eye_cross"] = eye_cross
    except Exception as exc:
        eye_out = {"ok": False, "error": str(exc)[:120]}

    ear_refined = analyze_audio(context=ear_ctx)
    neural_st = neural_assist_status()

    identification = signal_id.get("identification")
    if ear_refined.get("top_label") in ("ventriloquism_hint", "assault_hint", "multi_source"):
        identification = ear_refined["top_label"]
    if eye_out.get("top_label") == "threat_pattern" and signal_id.get("ok"):
        identification = "threat_corroborated"

    cross_agree = True
    if ear_refined.get("top_label") == "ventriloquism_hint":
        cross_agree = eye_out.get("top_label") != "clear_field" or float(eye_out.get("confidence", 0)) < 0.65
    if signal_id.get("identification") == "encoded_signal_detected":
        cross_agree = cross_agree and (
            float(eye_cross.get("rf_lie_score", 0)) >= 0.3
            or ear_refined.get("top_label") != "clear_audio"
        )
    if signal_id.get("identification") == "interference_mix":
        cross_agree = cross_agree and (len(sources or []) >= 2 or eye_out.get("top_label") == "threat_pattern")

    quorum = (
        signal_id.get("ok")
        and truth.get("ok")
        and ear_refined.get("ok")
        and sync.get("ok")
        and cross_agree
    )

    from zocr_immesurable import wrap_nested_response

    out = {
        "ok": quorum,
        "schema": "zocr-secure-neural-path/v1",
        "updated": _ts(),
        "sovereign_time": {
            "ear": ear_tick,
            "eye_mono_ns": eye_mono,
            "sync": sync,
            "never_desync": sync.get("ok"),
        },
        "identification": identification,
        "confidence": max(
            float(signal_id.get("confidence", 0)),
            float(ear_refined.get("confidence", 0)),
            float(eye_out.get("confidence", 0) if eye_out.get("ok") else 0),
        ),
        "signal_intel": signal_id,
        "truth_filter": truth,
        "ear_neural": ear_refined,
        "eye_neural": eye_out,
        "eye_cross": eye_cross,
        "neural_status": neural_st,
        "cross_agree": cross_agree,
        "invincible_quorum": quorum,
        "accurate_identification": quorum and signal_id.get("accurate"),
        "forward": quorum,
        "speak": "Eye↔Ear quorum — identification accurate" if quorum else "Veritas holds — woven quorum failed",
        "immeasurable": True,
        "persist_forbidden": True,
    }
    return wrap_nested_response(out)