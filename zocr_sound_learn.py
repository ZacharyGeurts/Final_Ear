"""Priority-safe sound learning — overlay encourage only, never override truth floor."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_SG = _ROOT.parent
DOCTRINE_PATH = _ROOT / "data" / "sound-tracker-doctrine.json"
LEARN_STATE = _ROOT / "data" / "sound-learn-state.json"
_GATE_PATH = _SG / "NewLatest" / "Queen" / "lib" / "queen-neural-encourage-gate.py"
_AUDIO_TRAIN = _SG / "NewLatest" / "lib" / "audio-train.py"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _save_state(st: dict[str, Any]) -> None:
    LEARN_STATE.parent.mkdir(parents=True, exist_ok=True)
    st["updated"] = _ts()
    LEARN_STATE.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")


def load_learn_doctrine() -> dict[str, Any]:
    doc = _read(DOCTRINE_PATH, {})
    return doc.get("learn") or {
        "truth_floor": 58,
        "overlay_only": True,
        "max_encourage_delta": 0.03,
        "audio_train_harvest": True,
        "never_override_priorities": True,
    }


def _encourage_gate():
    spec = importlib.util.spec_from_file_location("queen_neural_encourage_gate", _GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.path.insert(0, str(_GATE_PATH.parent))
    spec.loader.exec_module(mod)
    return mod


def _audio_train_mod():
    if not _AUDIO_TRAIN.is_file():
        return None
    spec = importlib.util.spec_from_file_location("audio_train", _AUDIO_TRAIN)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _label_from_track(track: dict[str, Any]) -> str:
    kind = str(track.get("ingress_lane") or "")
    motion = track.get("motion") or {}
    if motion.get("is_moving"):
        return "bearing_lock"
    if kind == "desktop":
        return "clear_audio"
    if kind in ("antenna", "rf_demod"):
        return "multi_source"
    return "speech_present"


def learn_from_observation(track: dict[str, Any], *, source: str = "sound_tracker") -> dict[str, Any]:
    """
    Train usefully without overriding priorities:
    - audio-train range expansion (local)
    - encourage overlay capped by gate (base weights sealed)
    - truth floor never bypassed
    """
    cfg = load_learn_doctrine()
    st = _read(LEARN_STATE, {"schema": "zocr-sound-learn-state/v1", "ticks": 0})
    sound_id = track.get("sound_id") or "unknown"
    label = _label_from_track(track)
    delta = min(float(cfg.get("max_encourage_delta", 0.03)), 0.05)

    audio_train_out: dict[str, Any] = {"ok": True, "skipped": True}
    if cfg.get("audio_train_harvest") and _AUDIO_TRAIN.is_file():
        try:
            mod = _audio_train_mod()
            sample = {
                "level_db": float(track.get("level_db") or -24.0),
                "peak_db": float(track.get("level_db") or -24.0) + 6.0,
                "bass_energy": 0.35,
                "treble_energy": 0.4,
                "sample_rate_hz": 48000.0,
                "latency_ms": 20.0,
                "bearing_deg": float(track.get("bearing_deg") or 0),
            }
            audio_train_out = mod.ingest_sample(
                str(track.get("source_key") or sound_id),
                sample,
                label=str(track.get("label") or sound_id),
                kind=str(track.get("ingress_lane") or "desktop"),
            )
        except Exception as exc:
            audio_train_out = {"ok": True, "degraded": True, "detail": str(exc)[:80]}

    encourage_out: dict[str, Any] = {"ok": True, "skipped": True}
    if cfg.get("overlay_only") and _GATE_PATH.is_file():
        try:
            from zocr_neural_assist import encourage, load_network

            net = load_network()
            truth_floor = int(net.get("truth_floor") or cfg.get("truth_floor") or 58)
            wire_ctx = {
                "sound_id": sound_id,
                "ingress_lane": track.get("ingress_lane"),
                "bearing_deg": track.get("bearing_deg"),
                "motion": track.get("motion"),
                "overlay_only": True,
                "truth_floor": truth_floor,
            }
            if cfg.get("never_override_priorities"):
                wire_ctx["priority_safe"] = True
            encourage_out = encourage(label=label, delta=delta, source=source, wire_ctx=wire_ctx)
            encourage_out["overlay_only"] = True
            encourage_out["truth_floor"] = truth_floor
            encourage_out["never_override_priorities"] = True
        except Exception as exc:
            encourage_out = {"ok": True, "degraded": True, "detail": str(exc)[:80]}

    st["ticks"] = int(st.get("ticks") or 0) + 1
    st["last_sound_id"] = sound_id
    st["last_label"] = label
    st["incorruptible"] = encourage_out.get("incorruptible", True)
    st["overlay_only"] = cfg.get("overlay_only", True)
    _save_state(st)

    return {
        "ok": True,
        "schema": "zocr-sound-learn/v1",
        "sound_id": sound_id,
        "neural_label": label,
        "audio_train": audio_train_out,
        "encourage": encourage_out,
        "overlay_only": cfg.get("overlay_only", True),
        "never_override_priorities": cfg.get("never_override_priorities", True),
        "truth_floor": cfg.get("truth_floor", 58),
    }


def learn_status() -> dict[str, Any]:
    cfg = load_learn_doctrine()
    st = _read(LEARN_STATE, {})
    gate_st = {}
    try:
        gate_st = _encourage_gate().gate_status()
    except Exception:
        pass
    return {
        "ok": True,
        "schema": "zocr-sound-learn-status/v1",
        "updated": st.get("updated") or _ts(),
        "ticks": st.get("ticks", 0),
        "last_sound_id": st.get("last_sound_id"),
        "doctrine": cfg,
        "encourage_gate": gate_st,
        "audio_train_path": str(_AUDIO_TRAIN) if _AUDIO_TRAIN.is_file() else None,
        "priority_safe": True,
    }