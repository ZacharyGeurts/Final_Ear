#!/usr/bin/env pythong
"""Queen forge watch → Final_Ear live hearing (thin bridge)."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

_HANGUP_RE = re.compile(
    r"(loading|booting|please\s+wait|not\s+responding|hang|stuck|spinning|"
    r"initializing|sealing|hydrat|connecting|buffer)",
    re.I,
)


def _forge_posture() -> dict[str, Any]:
    zocr_root = os.environ.get("ZOCR_ROOT", "").strip()
    if zocr_root:
        zpath = Path(zocr_root)
        fc = zpath / "zocr_field_compiler.py"
        if fc.is_file():
            if str(zpath) not in sys.path:
                sys.path.insert(0, str(zpath))
            try:
                from zocr_field_compiler import forge_posture  # noqa: WPS433
                return forge_posture()
            except Exception:
                pass
    eye_root = os.environ.get("FINAL_EYE_ROOT", "").strip()
    if eye_root:
        epath = Path(eye_root)
        fc = epath / "zocr_field_compiler.py"
        if fc.is_file():
            if str(epath) not in sys.path:
                sys.path.insert(0, str(epath))
            try:
                from zocr_field_compiler import forge_posture  # noqa: WPS433
                return forge_posture()
            except Exception:
                pass
    queen = Path(os.environ.get("QUEEN_ROOT", ROOT.parent / "NewLatest" / "Queen"))
    log = queen / ".queen-forge.log"
    tail = ""
    if log.is_file():
        try:
            tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-18:])
        except OSError:
            pass
    stage = "idle"
    if re.search(r"FORGE END rtx ok=True", tail):
        stage = "rtx_done"
    elif re.search(r"FORGE END rtx ok=False|compile failed|CMake Error", tail):
        stage = "failed"
    elif re.search(r"=== forge:rtx_build|FORGE START rtx", tail):
        stage = "compiling"
    return {
        "stage": stage,
        "binary_ready": bool(re.search(r"QUEEN BINARY READY|FORGE END verify ok=True", tail)),
        "running": bool(re.search(r"FORGE START|cmake", tail)),
        "tail": tail,
        "forge_log_bytes": log.stat().st_size if log.is_file() else 0,
    }


def _ear_blob(*parts: Any) -> str:
    lines: list[str] = []
    for p in parts:
        if isinstance(p, dict):
            lines.append(json.dumps(p, default=str).lower())
        else:
            lines.append(str(p).lower())
    return "\n".join(lines)


def watch_once(*, label: str = "queen_forge_watch") -> dict[str, Any]:
    from zocr_ear import ear_status, final_ear_status  # noqa: WPS433
    from zocr_sound_tracker import tracker_status  # noqa: WPS433

    forge = _forge_posture()
    final = final_ear_status()
    tracker = tracker_status()
    ear = final.get("ear") or ear_status()
    blob = _ear_blob(final, tracker, forge)
    return {
        "ok": True,
        "source": "final_ear",
        "label": label,
        "forge": forge,
        "ear": ear,
        "tracker": tracker,
        "final_ear": final,
        "capture": {"ocr_text": blob, "kind": "ear_sense"},
    }


def _hangup_hint(out: dict, *, prev_stage: str, stage_stall: int) -> dict:
    forge = out.get("forge") or {}
    stage = str(forge.get("stage") or "")
    cap = out.get("capture") or {}
    ocr = str(cap.get("ocr_text") or "").lower()
    hung = False
    reasons: list[str] = []
    if stage == prev_stage and stage_stall >= 3 and stage not in ("binary_ready", "idle", "failed", "rtx_done"):
        hung = True
        reasons.append(f"stage_stall:{stage}")
    if _HANGUP_RE.search(ocr) and forge.get("running"):
        hung = True
        reasons.append("ear_loading_pattern")
    tracker = out.get("tracker") or {}
    if tracker.get("degraded") and forge.get("running"):
        hung = True
        reasons.append("ear_tracker_degraded")
    out["hangup"] = {"suspected": hung, "reasons": reasons, "stage": stage, "stage_stall": stage_stall}
    return out


def watch_loop() -> int:
    interval = float(os.environ.get("FINAL_EAR_POLL_INTERVAL", os.environ.get("QUEEN_WATCH_INTERVAL", "10")))
    loops = int(os.environ.get("FINAL_EAR_POLL_LOOPS", "0"))
    prev_stage = ""
    stage_stall = 0
    n = 0
    while True:
        n += 1
        out = watch_once(label=f"queen_forge_loop_{n}")
        forge = out.get("forge") or {}
        stage = str(forge.get("stage") or "")
        if stage == prev_stage:
            stage_stall += 1
        else:
            stage_stall = 0
            prev_stage = stage
        out = _hangup_hint(out, prev_stage=prev_stage, stage_stall=stage_stall)
        print(json.dumps({"loop": n, **out}, ensure_ascii=False), flush=True)
        if forge.get("binary_ready"):
            return 0
        if loops > 0 and n >= loops:
            return 0
        time.sleep(interval)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd in ("once", "watch", "snapshot", "poll"):
        out = watch_once(label=sys.argv[2] if len(sys.argv) > 2 else "queen_forge_watch")
        print(json.dumps(out, indent=2))
        return 0
    if cmd in ("loop", "monitor"):
        return watch_loop()
    if cmd == "status":
        out = watch_once(label="queen_forge_status")
        print(json.dumps({"snapshot": out.get("final_ear"), "tracker": out.get("tracker"), "forge": out.get("forge")}, indent=2))
        return 0
    print(json.dumps({"error": "usage: queen_forge_watch.py [once|loop|status|poll]"}, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())