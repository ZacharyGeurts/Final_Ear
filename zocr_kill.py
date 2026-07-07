"""Final Ear kill switches — hearing, ingest, stream, offense, egress."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
KILL_PATH = _ROOT / "data" / "kill-state.json"
_SWITCHES = ("hearing", "listen", "capture", "stream", "offense", "egress")
_OP_MAP = {
    "listen": "listen",
    "analyze_audio": "listen",
    "audio_offense": "offense",
    "countermeasure": "offense",
    "virtual_observe": "capture",
    "stoard_write": "capture",
    "hardware_bind": "capture",
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    if KILL_PATH.is_file():
        try:
            return json.loads(KILL_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "schema": "zocr-ear-kill-state/v1",
        "tripped": {s: False for s in _SWITCHES},
        "ears_protect": True,
        "last_trip": None,
    }


def _save(st: dict[str, Any]) -> None:
    st["updated"] = _ts()
    KILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    KILL_PATH.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")


def _apply_env(st: dict[str, Any]) -> dict[str, Any]:
    for env, switch in (
        ("ZOCR_KILL_HEARING", "hearing"),
        ("ZOCR_KILL_LISTEN", "listen"),
        ("ZOCR_KILL_CAPTURE", "capture"),
        ("ZOCR_KILL_STREAM", "stream"),
        ("ZOCR_KILL_OFFENSE", "offense"),
        ("ZOCR_KILL_EGRESS", "egress"),
        ("ZOCR_KILL_ALL", None),
    ):
        if os.environ.get(env, "").strip().lower() in ("1", "true", "yes"):
            if switch is None:
                for s in _SWITCHES:
                    st["tripped"][s] = True
            else:
                st["tripped"][switch] = True
    return st


def is_tripped(switch: str) -> bool:
    st = _apply_env(_load())
    return bool(st.get("tripped", {}).get(switch, False))


def check(operation: str) -> dict[str, Any]:
    st = _apply_env(_load())
    switch = _OP_MAP.get(operation, operation)
    if switch in _SWITCHES and st.get("tripped", {}).get(switch):
        return {"ok": False, "error": "kill_switch", "switch": switch, "operation": operation}
    if operation in _SWITCHES and st.get("tripped", {}).get(operation):
        return {"ok": False, "error": "kill_switch", "switch": operation, "operation": operation}
    return {"ok": True, "operation": operation}


def kill_status() -> dict[str, Any]:
    st = _apply_env(_load())
    return {**st, "schema": "zocr-ear-kill-status/v1", "updated": _ts()}