"""Ear truth filters — ventriloquism, multi-source, assault, existence correlation."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
FILTER_PATH = _ROOT / "data" / "ear-truth-filter.json"
LEDGER = _ROOT / "data" / "truth-forward-audio-ledger.jsonl"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_truth_doctrine() -> dict[str, Any]:
    try:
        return json.loads(FILTER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "zocr-ear-truth-filter/v1", "filters": {}}


def _append_ledger(row: dict[str, Any]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def truth_filter_status() -> dict[str, Any]:
    doc = load_truth_doctrine()
    return {
        "schema": "zocr-ear-truth-status/v1",
        "updated": _ts(),
        "rule": doc.get("rule"),
        "filters": list((doc.get("filters") or {}).keys()),
        "lie_markers": doc.get("lie_markers", []),
        "vigilance": doc.get("vigilance"),
    }


def _score_ventriloquism(evidence: dict[str, Any]) -> float:
    mouth = float(evidence.get("mouth_correlation", 0.5))
    tdoa = float(evidence.get("lip_tdoa_ms", 0.0))
    phantom = bool(evidence.get("phantom_bearing", False))
    score = mouth
    if abs(tdoa) > 40:
        score *= 0.6
    if phantom:
        score *= 0.3
    return max(0.0, min(1.0, score))


def _score_multi_source(sources: list[dict[str, Any]]) -> float:
    if len(sources) < 2:
        return 1.0
    bearings = [s.get("bearing_deg") for s in sources if s.get("bearing_deg") is not None]
    if len(bearings) < 2:
        return 0.85
    spread = max(bearings) - min(bearings)
    if spread > 90 and len(sources) == 2:
        return 0.55
    return 0.9


def apply_truth_filters(
    *,
    evidence: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    peak_db: float | None = None,
    existence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc = load_truth_doctrine()
    filters = doc.get("filters") or {}
    ev = evidence or {}
    srcs = sources or []
    ex = existence or {}
    results: list[dict[str, Any]] = []
    lies: list[str] = []
    actions: list[str] = []

    vent = filters.get("ventriloquism", {})
    v_score = _score_ventriloquism(ev)
    v_ok = v_score >= float(vent.get("threshold", 0.72))
    results.append({"id": "ventriloquism", "score": round(v_score, 3), "ok": v_ok})
    if not v_ok:
        lies.append("ventriloquism")
        actions.append(vent.get("action", "reject_lie"))

    multi = filters.get("multi_source_decoherence", {})
    m_score = _score_multi_source(srcs)
    m_ok = m_score >= float(multi.get("threshold", 0.68))
    results.append({"id": "multi_source_decoherence", "score": round(m_score, 3), "ok": m_ok})
    if not m_ok:
        lies.append("incoherent_beam")
        actions.append(multi.get("action", "quorum_sources"))

    assault = filters.get("hostile_assault", {})
    peak = peak_db if peak_db is not None else float(ev.get("peak_db", -12.0))
    a_ok = peak < 0.0
    results.append({"id": "hostile_assault", "peak_db": peak, "ok": a_ok})
    if not a_ok:
        lies.append("assault_burst")
        actions.append(assault.get("action", "kill_switch"))

    exist_f = filters.get("existence_correlation", {})
    e_score = float(ex.get("correlation", ev.get("existence_correlation", 0.8)))
    e_ok = e_score >= float(exist_f.get("threshold", 0.65))
    results.append({"id": "existence_correlation", "score": round(e_score, 3), "ok": e_ok})
    if not e_ok:
        lies.append("mouth_mismatch")
        actions.append(exist_f.get("action", "correlate_or_hold"))

    spoof_f = filters.get("speaker_spoof", {})
    if spoof_f:
        prov_ok = ev.get("provenance_weave_ok", True) is not False
        sov_ok = ev.get("sovereign_time_ok", True) is not False
        replay = bool(ev.get("replay_detected", False))
        s_score = (0.4 if prov_ok else 0.0) + (0.35 if sov_ok else 0.0) + (0.25 if not replay else 0.0)
        s_ok = s_score >= float(spoof_f.get("threshold", 0.75))
        results.append({"id": "speaker_spoof", "score": round(s_score, 3), "ok": s_ok})
        if not s_ok:
            lies.append("foreign_weave" if not prov_ok else "replay_spoof")
            actions.append(spoof_f.get("action", "reject_lie"))

    enc_f = filters.get("encoded_signal", {})
    if enc_f:
        try:
            from zocr_ear_signal_intel import score_encoded_signal
            enc = score_encoded_signal(evidence=ev)
            e_enc_ok = enc.get("ok", True)
            results.append({"id": "encoded_signal", "score": enc.get("score"), "ok": e_enc_ok, "markers": enc.get("markers")})
            if not e_enc_ok:
                lies.append("encoded_carrier")
                actions.append(enc_f.get("action", "reject_lie"))
        except ImportError:
            pass

    mix_f = filters.get("mixed_interference", {})
    if mix_f:
        try:
            from zocr_ear_signal_intel import score_mixed_interference
            mix = score_mixed_interference(evidence=ev, sources=srcs)
            m_mix_ok = mix.get("ok", True)
            results.append({"id": "mixed_interference", "score": mix.get("score"), "ok": m_mix_ok, "markers": mix.get("markers")})
            if not m_mix_ok:
                lies.append("ghost_duplicate" if "ghost_duplicate" in (mix.get("markers") or []) else "incoherent_beam")
                actions.append(mix_f.get("action", "quorum_sources"))
        except ImportError:
            pass

    ok = all(r.get("ok") for r in results)
    out = {
        "ok": ok,
        "schema": "zocr-ear-truth-apply/v1",
        "updated": _ts(),
        "results": results,
        "lies_detected": lies,
        "actions": actions,
        "forward": ok,
        "speak": "Truth affirmed" if ok else "Veritas holds — " + ", ".join(lies),
    }
    _append_ledger(out)
    return out