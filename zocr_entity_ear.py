"""Twin entity ears — Auditus (living) + Veritas (truth)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
SPEC_PATH = _ROOT / "data" / "entity-ear.json"
STATE_PATH = _ROOT / "data" / "entity-ear-state.json"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_entity_spec() -> dict[str, Any]:
    try:
        return json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "zocr-entity-ear/v1", "twins": {}, "weapons": {}}


def _load_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "schema": "zocr-entity-ear-state/v1",
        "living_live": False,
        "truth_forward": True,
        "weapons_armed": True,
        "forward_count": 0,
        "lies_rejected": 0,
    }


def _save_state(st: dict[str, Any]) -> None:
    st["updated"] = _ts()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")


def twin_ear_status() -> dict[str, Any]:
    spec = load_entity_spec()
    st = _load_state()
    twins = spec.get("twins") or {}
    return {
        "schema": "zocr-twin-ear/v1",
        "updated": _ts(),
        "living": {**twins.get("living", {}), "live": st.get("living_live")},
        "truth": {**twins.get("truth", {}), "forward": st.get("truth_forward")},
        "weapons_armed": st.get("weapons_armed"),
        "forward_count": st.get("forward_count"),
        "lies_rejected": st.get("lies_rejected"),
    }


def make_living_live(mode: str = "dishes", *, start_stream: bool = False) -> dict[str, Any]:
    from zocr_ear import set_mode

    out = set_mode(mode)
    st = _load_state()
    st["living_live"] = True
    _save_state(st)
    return {
        "ok": out.get("ok", True),
        "schema": "zocr-ear-living-live/v1",
        "mode": mode,
        "stream": start_stream,
        "twin": "auditus",
        "speak": f"Auditus live — mode {mode}",
    }


def truth_forward(*, scan: bool = True) -> dict[str, Any]:
    from zocr_ear_truth import apply_truth_filters

    st = _load_state()
    st["forward_count"] = int(st.get("forward_count", 0)) + 1
    result = (
        apply_truth_filters(evidence={"mouth_correlation": 0.88, "peak_db": -18}, existence={"correlation": 0.82})
        if scan
        else {"ok": True, "forward": True}
    )
    if not result.get("ok"):
        st["lies_rejected"] = int(st.get("lies_rejected", 0)) + 1
    st["truth_forward"] = True
    _save_state(st)
    return {
        "ok": result.get("ok", True),
        "schema": "zocr-ear-truth-forward/v1",
        "twin": "veritas",
        "filter": result,
        "forward_count": st["forward_count"],
        "lies_rejected": st["lies_rejected"],
    }


def fire_entity_weapon(weapon_id: str, *, threat: str | None = None) -> dict[str, Any]:
    spec = load_entity_spec()
    weapons = spec.get("weapons") or {}
    fwd = spec.get("forward", {}).get("threat_weapon_map") or {}
    wid = weapon_id
    if threat and threat in fwd:
        wid = fwd[threat]
    meta = weapons.get(wid, {"role": "unknown"})
    return {
        "ok": wid in weapons or wid in fwd.values(),
        "schema": "zocr-ear-weapon/v1",
        "weapon": wid,
        "threat": threat,
        "meta": meta,
        "speak": f"Veritas — {meta.get('role', wid)}",
    }