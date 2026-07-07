"""Desktop audio ingress — PipeWire/Pulse monitor, zero-cost local capture."""
from __future__ import annotations

import math
import os
import re
import struct
import subprocess
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _volume_to_db(pct: float) -> float:
    pct = max(0.0, min(100.0, pct))
    if pct <= 0.01:
        return -72.0
    return round(20.0 * math.log10(pct / 100.0), 2)


def _rms_db_from_pcm(pcm: bytes) -> float:
    if len(pcm) < 4:
        return -60.0
    n = len(pcm) // 2
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    if not samples:
        return -60.0
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms <= 1.0:
        return -72.0
    return round(20.0 * math.log10(rms / 32768.0), 2)


def _classify_kind(label: str) -> str:
    blob = (label or "").lower()
    if any(x in blob for x in ("spotify", "vlc", "mpv", "rhythmbox", "music", "youtube")):
        return "music"
    if any(x in blob for x in ("firefox", "chrome", "chromium", "browser")):
        return "browser"
    if "pipewire" in blob or "wireplumber" in blob:
        return "pipewire"
    if "pulse" in blob:
        return "pulse"
    return "desktop"


def _bound_monitor_device() -> str | None:
    try:
        from zocr_hardware_audio import get_queen_monitor_device, is_dummy_sink, load_route_state

        route = load_route_state()
        if route.get("bound"):
            mon = get_queen_monitor_device()
            sink = str(route.get("sink_name") or "")
            if mon and not is_dummy_sink(sink):
                return mon
    except ImportError:
        pass
    return None


def _detect_backend() -> str:
    for cmd, name in (
        (["pw-cli", "--version"], "pipewire"),
        (["pactl", "--version"], "pulse"),
    ):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if proc.returncode == 0:
                return name
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "unavailable"


def harvest_desktop_sources() -> list[dict[str, Any]]:
    """Enumerate active desktop audio sources — never raises."""
    rows: list[dict[str, Any]] = []
    backend = _detect_backend()
    try:
        if backend == "pulse":
            proc = subprocess.run(
                ["pactl", "list", "sink-inputs"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout:
                for block in (proc.stdout or "").split("Sink Input #")[1:]:
                    app = ""
                    m = re.search(r'application\.name = "([^"]+)"', block)
                    if m:
                        app = m.group(1)
                    m2 = re.search(r"Volume:.*?(\d+)%", block)
                    vol = float(m2.group(1)) if m2 else 50.0
                    sid_m = re.search(r"^(\d+)", block.strip())
                    sid = f"pulse:{sid_m.group(1) if sid_m else app or 'sink'}"
                    level = _volume_to_db(vol)
                    rows.append({
                        "ingress_lane": "desktop",
                        "source_key": sid,
                        "label": app or sid,
                        "kind": _classify_kind(app),
                        "backend": "pulse",
                        "level_db": level,
                        "peak_db": min(-1.0, level + 6.0),
                        "bearing_deg": 0.0,
                        "itd_us": 0.0,
                        "sample_rate_hz": 48000,
                        "channels": 2,
                    })
        elif backend == "pipewire":
            proc = subprocess.run(
                ["pw-cli", "ls", "Node"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout:
                for block in re.split(r"\nid \d+, type", proc.stdout or ""):
                    if "node.name" not in block:
                        continue
                    name_m = re.search(r'node\.name = "([^"]+)"', block)
                    desc_m = re.search(r'application\.name = "([^"]+)"', block)
                    name = (desc_m.group(1) if desc_m else None) or (name_m.group(1) if name_m else "pipewire")
                    sid = f"pipewire:{name}"
                    rows.append({
                        "ingress_lane": "desktop",
                        "source_key": sid,
                        "label": name,
                        "kind": _classify_kind(name),
                        "backend": "pipewire",
                        "level_db": -24.0,
                        "peak_db": -12.0,
                        "bearing_deg": 0.0,
                        "itd_us": 0.0,
                        "sample_rate_hz": 48000,
                        "channels": 2,
                    })
    except (OSError, subprocess.TimeoutExpired):
        pass

    if not rows:
        rows.append({
            "ingress_lane": "desktop",
            "source_key": "desktop:monitor",
            "label": "System monitor (synthetic)",
            "kind": "desktop",
            "backend": backend,
            "level_db": -36.0,
            "peak_db": -28.0,
            "bearing_deg": 0.0,
            "itd_us": 0.0,
            "sample_rate_hz": 48000,
            "channels": 2,
            "synthetic": True,
        })
    return rows


def capture_monitor_chunk(*, seconds: float = 2.0, sample_rate: int = 48000) -> dict[str, Any]:
    """Capture desktop monitor audio — graceful degrade to silence envelope."""
    frames = int(sample_rate * max(0.25, min(seconds, 12.0)))
    pcm = b""
    backend = _detect_backend()
    captured = False
    wav_path: str | None = None

    tmp = Path(os.environ.get("NEXUS_STATE_DIR", _ROOT / ".nexus-state")) / "desktop-monitor-capture.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)

    monitor = _bound_monitor_device() or "@DEFAULT_MONITOR@"
    sink_target = monitor.replace(".monitor", "") if monitor.endswith(".monitor") else "@DEFAULT_AUDIO_SINK@"
    capture_cmds: list[list[str]] = [
        ["parec", f"--device={monitor}", f"--rate={sample_rate}", "--channels=2", "--format=s16le", "-d", str(int(seconds))],
        ["pw-record", "--target", sink_target, "-P", "buffer.latency=512", str(tmp)],
    ]
    if monitor != "@DEFAULT_MONITOR@":
        capture_cmds.append(
            ["parec", "--device=@DEFAULT_MONITOR@", f"--rate={sample_rate}", "--channels=2", "--format=s16le", "-d", str(int(seconds))],
        )

    for cmd in capture_cmds:
        try:
            if cmd[0] == "pw-record":
                proc = subprocess.run(cmd, capture_output=True, timeout=int(seconds) + 8)
                if proc.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 44:
                    with wave.open(str(tmp), "rb") as wf:
                        pcm = wf.readframes(wf.getnframes())
                    captured = True
                    wav_path = str(tmp)
                    break
            else:
                proc = subprocess.run(cmd, capture_output=True, timeout=int(seconds) + 6)
                if proc.returncode == 0 and proc.stdout:
                    pcm = proc.stdout[: frames * 4]
                    captured = True
                    break
        except (OSError, subprocess.TimeoutExpired):
            continue

    if not pcm:
        pcm = b"\x00\x00" * (frames * 2)

    level_db = _rms_db_from_pcm(pcm)
    return {
        "ok": True,
        "schema": "zocr-desktop-audio-capture/v1",
        "updated": _ts(),
        "captured": captured,
        "backend": backend,
        "monitor_device": monitor,
        "hardware_bound": monitor != "@DEFAULT_MONITOR@",
        "ingress_lane": "hardware" if monitor != "@DEFAULT_MONITOR@" else "desktop",
        "sample_rate_hz": sample_rate,
        "channels": 2,
        "seconds": seconds,
        "level_db": level_db,
        "peak_db": min(-1.0, level_db + 8.0),
        "pcm_hex": pcm.hex(),
        "pcm_bytes": len(pcm),
        "wav_path": wav_path,
        "never_fail": True,
    }


def desktop_audio_status() -> dict[str, Any]:
    sources = harvest_desktop_sources()
    backend = _detect_backend()
    monitor = _bound_monitor_device()
    hardware: dict[str, Any] = {}
    try:
        from zocr_hardware_audio import hardware_audio_status

        hardware = hardware_audio_status()
    except ImportError:
        hardware = {"ok": False, "degraded": True}
    return {
        "ok": True,
        "schema": "zocr-desktop-audio-status/v1",
        "updated": _ts(),
        "backend": backend,
        "ingress_lane": "hardware" if monitor else "desktop",
        "monitor_device": monitor or "@DEFAULT_MONITOR@",
        "hardware_bound": bool(monitor),
        "hardware_route": hardware.get("route"),
        "zero_cost": True,
        "never_fail": True,
        "source_count": len(sources),
        "sources": sources,
        "capture_cmds": [
            f"parec {monitor or '@DEFAULT_MONITOR@'}",
            f"pw-record {monitor.replace('.monitor', '') if monitor else '@DEFAULT_AUDIO_SINK@'}",
        ],
    }


def follow_user_desktop(*, learn: bool = True) -> dict[str, Any]:
    """Harvest desktop sources and register with tracker — follows active apps."""
    from zocr_sound_tracker import ingest_observations

    sources = harvest_desktop_sources()
    cap = capture_monitor_chunk(seconds=1.5)
    if cap.get("level_db") is not None:
        for src in sources:
            if not src.get("synthetic"):
                src["level_db"] = cap["level_db"]
                src["peak_db"] = cap.get("peak_db", src.get("peak_db"))
    obs = ingest_observations(sources, learn=learn)
    obs["desktop_capture"] = {"captured": cap.get("captured"), "level_db": cap.get("level_db")}
    obs["ingress_lane"] = "desktop"
    return obs