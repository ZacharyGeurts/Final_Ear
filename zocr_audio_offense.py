"""Audio offense — equipment protection and countermeasures through lethal tier."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
SPEC_PATH = _ROOT / "data" / "audio-offense.json"
PROT_PATH = _ROOT / "data" / "ear-equipment-protection.json"
LEDGER = _ROOT / "data" / "audio-offense-ledger.jsonl"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def audio_offense_status() -> dict[str, Any]:
    spec = _read(SPEC_PATH)
    prot = _read(PROT_PATH)
    return {
        "schema": "zocr-audio-offense-status/v1",
        "updated": _ts(),
        "rule": spec.get("rule"),
        "countermeasures": list((spec.get("countermeasures") or {}).keys()),
        "lethal": spec.get("lethal"),
        "equipment": prot.get("equipment"),
        "protection_tiers": prot.get("countermeasures"),
    }


def countermeasure_for(threat: str, *, hostess_ok: bool = True, eye_ear_quorum: bool = True) -> dict[str, Any]:
    try:
        from zocr_security import mandate_enforce
        gate = mandate_enforce("countermeasure")
        if not gate.get("ok"):
            return {"ok": False, "error": gate.get("error", "mandate"), **gate}
    except ImportError:
        pass
    spec = _read(SPEC_PATH)
    cm = (spec.get("countermeasures") or {}).get(threat, {})
    tier = cm.get("tier", "offense")
    lethal = spec.get("lethal") or {}
    permitted = True
    if tier == "lethal":
        permitted = (
            hostess_ok
            and eye_ear_quorum
            and lethal.get("hostess7_corroborate")
            and lethal.get("eye_ear_quorum")
        )
    out = {
        "ok": True,
        "threat": threat,
        "tier": tier,
        "strike": cm.get("strike"),
        "offense": cm.get("offense"),
        "severity": cm.get("severity"),
        "lethal_permitted": permitted if tier == "lethal" else False,
        "humans_cannot_override": lethal.get("humans_cannot_override", True),
    }
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**out, "ts": _ts()}, ensure_ascii=False) + "\n")
    return out