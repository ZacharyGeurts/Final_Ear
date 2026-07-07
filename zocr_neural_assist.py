"""Encouragable neural assistance for Final_Ear — wired invincibly to Eye under Hostess 7."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_SG = _ROOT.parent
_GATE_PATH = _SG / "NewLatest" / "Queen" / "lib" / "queen-neural-encourage-gate.py"
NET_PATH = _ROOT / "data" / "ear-neural-assist.json"
SEAL_PATH = _ROOT / "data" / "ear-neural-seal.json"
ENCOURAGE_LOG = Path(os.environ.get("NEXUS_STATE_DIR", _ROOT / ".nexus-state")) / "ear-neural-encourage.jsonl"
STATE_PATH = _ROOT / "data" / "ear-neural-assist-state.json"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def load_network() -> dict[str, Any]:
    return _read(NET_PATH, {"schema": "zocr-ear-neural-assist/v1", "layers": []})


def _encourage_gate():
    spec = importlib.util.spec_from_file_location("queen_neural_encourage_gate", _GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.path.insert(0, str(_GATE_PATH.parent))
    spec.loader.exec_module(mod)
    return mod


def _relu(x: float) -> float:
    return max(0.0, x)


def _softmax(vals: list[float]) -> list[float]:
    m = max(vals) if vals else 0.0
    ex = [math.exp(v - m) for v in vals]
    s = sum(ex) or 1.0
    return [e / s for e in ex]


def _mat_vec(weights: list[list[float]], bias: list[float], x: list[float], activation: str) -> list[float]:
    out: list[float] = []
    for row, b in zip(weights, bias):
        v = sum(w * xi for w, xi in zip(row, x)) + b
        if activation == "relu":
            v = _relu(v)
        out.append(v)
    if activation == "softmax":
        return _softmax(out)
    return out


def _audio_features(ctx: dict[str, Any]) -> list[float]:
    ev = ctx.get("evidence") or {}
    loc = ctx.get("localization") or {}
    eye = ctx.get("eye_cross") or {}
    peak = float(ev.get("peak_db", -18.0))
    mouth = float(ev.get("mouth_correlation", 0.7))
    itd = min(1.0, abs(float(ev.get("itd_us", 0))) / 500.0)
    bearing = min(1.0, abs(float(loc.get("bearing_deg", 0))) / 180.0)
    assault = 1.0 if peak >= 0 else 0.0
    vent = 1.0 - mouth
    threat_eye = 1.0 if float(eye.get("threat_pattern", 0) or 0) > 0.3 else 0.0
    rf_lie = float(eye.get("rf_lie_score", 0) or 0)
    encoded = 0.0 if ctx.get("encoded_ok", True) else 1.0
    interference = 0.0 if ctx.get("interference_ok", True) else 1.0
    if eye.get("encoded_signal"):
        encoded = max(encoded, 0.85)
    if eye.get("interference_mix"):
        interference = max(interference, 0.85)
    existence = float(ctx.get("existence_correlation", 0.75))
    sovereign = 1.0 if ev.get("sovereign_time_ok", True) else 0.0
    return [mouth, vent, assault, itd, bearing, encoded, interference, threat_eye, rf_lie, existence, sovereign, peak / -60.0]


def _forward(features: list[float], net: dict[str, Any]) -> tuple[list[float], list[str]]:
    labels = net.get("labels") or ["unknown"]
    x = (features + [0.0] * 12)[:12]
    for layer in net.get("layers") or []:
        if layer.get("id") == "features":
            continue
        w, b = layer.get("weights", []), layer.get("bias", [])
        act = layer.get("activation", "identity")
        if w:
            x = _mat_vec(w, b, x, act)
        if layer.get("labels"):
            labels = layer["labels"]
    return x, labels


def neural_assist_status() -> dict[str, Any]:
    net = load_network()
    st = _read(STATE_PATH, {})
    seal = _read(SEAL_PATH, {})
    gate_st = {}
    try:
        gate_st = _encourage_gate().gate_status()
    except Exception:
        gate_st = {}
    return {
        "schema": "zocr-ear-neural-assist-status/v1",
        "updated": _ts(),
        "network_id": net.get("network_id"),
        "encourage": net.get("encourage", True),
        "truth_floor": net.get("truth_floor", 58),
        "sealed": bool(seal.get("sha256")),
        "encourage_count": st.get("encourage_count", 0),
        "incorruptible": st.get("incorruptible", gate_st.get("incorruptible")),
        "quarantine_count": gate_st.get("quarantine_count", 0),
        "cross_wire": net.get("cross_wire"),
        "labels": net.get("labels"),
    }


def analyze_audio(*, context: dict[str, Any] | None = None) -> dict[str, Any]:
    from zocr_sovereign_time import seal_ear_tick

    net = load_network()
    ctx = dict(context or {})
    tick = seal_ear_tick(reason="neural_analyze")
    ev = ctx.setdefault("evidence", {})
    ev.setdefault("sovereign_time_ok", tick.get("ok", True))
    ev.setdefault("sealed_mono_ns", tick.get("sealed_mono_ns"))
    feats = _audio_features(ctx)
    probs, labels = _forward(feats, net)
    st = _read(STATE_PATH, {})
    gate = _encourage_gate()
    seal = gate.verify_base_seal(sense="ear", net=net, seal_path=SEAL_PATH)
    base_sha = seal.get("payload_sha256") or gate._net_payload_hash(net)
    probs, overlay_meta = gate.apply_encouraged_bias(probs, labels, st, base_sha=base_sha)
    ranked = sorted(zip(labels, probs), key=lambda t: t[1], reverse=True)
    label_idx = {lb: i for i, lb in enumerate(labels)}
    if not ctx.get("encoded_ok", True) and "assault_hint" in label_idx:
        probs[label_idx["assault_hint"]] = min(1.0, probs[label_idx["assault_hint"]] + 0.12)
    if not ctx.get("interference_ok", True) and "multi_source" in label_idx:
        probs[label_idx["multi_source"]] = min(1.0, probs[label_idx["multi_source"]] + 0.15)
    if ctx.get("eye_cross", {}).get("ventriloquism") and "ventriloquism_hint" in label_idx:
        probs[label_idx["ventriloquism_hint"]] = min(1.0, probs[label_idx["ventriloquism_hint"]] + 0.18)
    total = sum(probs) or 1.0
    probs = [p / total for p in probs]
    ranked = sorted(zip(labels, probs), key=lambda t: t[1], reverse=True)
    top_label, top_p = ranked[0] if ranked else ("unknown", 0.0)
    from zocr_immesurable import immesurable_overlay, sanitize_score_map, strip_poison_fields

    heur = sanitize_score_map({lb: float(p) for lb, p in ranked})
    row = {
        "ok": True,
        "schema": "zocr-ear-neural-analyze/v1",
        "updated": _ts(),
        "top_label": top_label,
        "confidence": round(top_p, 4),
        "ranked": [{"label": lb, "p": round(p, 4)} for lb, p in ranked],
        "heuristic_overlay": immesurable_overlay(heuristic=heur, top_label=top_label, engine="ear_neural_assist"),
        "cross_wire_from_eye": bool(ctx.get("eye_cross")),
        "sovereign_time": tick,
        "secure_path": True,
        "incorruptible_overlay": overlay_meta,
        "immeasurable": True,
        "persist_forbidden": True,
    }
    return strip_poison_fields(row)


def encourage(
    *,
    label: str,
    delta: float = 0.02,
    source: str = "hostess7",
    wire_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Encourage correct ear NN — incorruptible gate; base weights never mutate."""
    net = load_network()
    labels = net.get("labels") or []
    return _encourage_gate().gate_encourage(
        sense="ear",
        label=label,
        delta=delta,
        source=source,
        labels=labels,
        net=net,
        state_path=STATE_PATH,
        wire_ctx=wire_ctx,
    )


def seal_network() -> dict[str, Any]:
    net = load_network()
    payload = json.dumps(net, sort_keys=True).encode()
    doc = {"schema": "zocr-ear-neural-seal/v1", "ts": _ts(), "sha256": hashlib.sha256(payload).hexdigest(), "network_id": net.get("network_id")}
    SEAL_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc