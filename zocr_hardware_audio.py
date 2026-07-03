"""Hardware audio probe and secure bind — mobo/card → PipeWire monitor → Queen."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
POLICY_PATH = _ROOT / "data" / "hardware-audio-policy.json"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_dir() -> Path:
    env = os.environ.get("NEXUS_STATE_DIR", "").strip()
    if env:
        return Path(env)
    return _ROOT / ".nexus-state"


def _route_path() -> Path:
    return _state_dir() / "queen-audio-route.json"


def _run(cmd: list[str], *, timeout: float = 8.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _load_policy() -> dict[str, Any]:
    try:
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "denylist_sinks": ["auto_null", "null", "dummy"],
            "denylist_patterns": ["dummy", "auto_null", "speech-dispatcher"],
            "priority_keywords": {
                "mobo_hda": ["realtek", "alc", "hda intel", "snd_hda", "onboard"],
                "usb_card": ["usb", "focusrite", "scarlett"],
                "hdmi": ["hdmi", "nvidia", "displayport"],
            },
            "remediation": [],
        }


def is_dummy_sink(name: str, description: str = "") -> bool:
    policy = _load_policy()
    blob = f"{name} {description}".lower()
    deny = {s.lower() for s in policy.get("denylist_sinks", [])}
    if name.lower() in deny:
        return True
    for pat in policy.get("denylist_patterns", []):
        if pat.lower() in blob:
            return True
    return False


def _score_sink(sink: dict[str, Any]) -> int:
    policy = _load_policy()
    name = str(sink.get("name") or "")
    desc = str(sink.get("description") or "")
    if is_dummy_sink(name, desc):
        return -1000
    blob = f"{name} {desc}".lower()
    score = 0
    kw = policy.get("priority_keywords") or {}
    for key in kw.get("mobo_hda", []):
        if key.lower() in blob:
            score += 100
            break
    for key in kw.get("usb_card", []):
        if key.lower() in blob:
            score += 80
            break
    for key in kw.get("hdmi", []):
        if key.lower() in blob:
            score += 30
            break
    if str(sink.get("state", "")).upper() == "RUNNING":
        score += 10
    if not sink.get("muted"):
        score += 5
    if sink.get("alsa_card"):
        score += 15
    return score


def probe_pci_audio() -> list[dict[str, str]]:
    code, out = _run(["lspci", "-nn"])
    if code != 0:
        return []
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        low = line.lower()
        if "audio" not in low and "multimedia" not in low and "sound" not in low:
            continue
        slot = line.split()[0] if line.split() else ""
        rows.append({"pci_slot": slot, "description": line.strip(), "kind": "pci"})
    return rows


def probe_alsa_cards() -> list[dict[str, Any]]:
    snd = Path("/dev/snd")
    proc_cards = Path("/proc/asound/cards")
    cards: list[dict[str, Any]] = []
    if proc_cards.is_file():
        for line in proc_cards.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*(\d+)\s+\[([^\]]+)\]\s*:\s*(.+)", line)
            if m:
                cards.append({
                    "id": m.group(1),
                    "name": m.group(2),
                    "description": m.group(3).strip(),
                    "backend": "proc",
                })
    code, out = _run(["aplay", "-l"])
    if code == 0:
        for line in out.splitlines():
            m = re.match(r"card (\d+): ([^\s]+) \[(.+)\]", line)
            if m and not any(c["id"] == m.group(1) for c in cards):
                cards.append({
                    "id": m.group(1),
                    "name": m.group(2),
                    "description": m.group(3),
                    "backend": "aplay",
                })
    return cards


def probe_pipewire_sinks() -> list[dict[str, Any]]:
    code, out = _run(["pactl", "list", "sinks", "short"])
    if code != 0:
        return []
    sinks: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        idx, name = parts[0], parts[1]
        driver = parts[2] if len(parts) > 2 else ""
        fmt = parts[3] if len(parts) > 3 else ""
        state = parts[4] if len(parts) > 4 else ""
        desc = parts[5] if len(parts) > 5 else name
        sinks.append({
            "index": idx,
            "name": name,
            "driver": driver,
            "format": fmt,
            "state": state,
            "description": desc,
            "dummy": is_dummy_sink(name, desc),
            "score": 0,
        })
    code2, detail = _run(["pactl", "list", "sinks"])
    if code2 == 0:
        blocks = re.split(r"^Sink #\d+", detail, flags=re.MULTILINE)
        for sink in sinks:
            for block in blocks:
                if f"Name: {sink['name']}" not in block:
                    continue
                sink["muted"] = "Mute: yes" in block
                vm = re.search(r"Volume:.*?(\d+)%", block)
                if vm:
                    sink["volume_percent"] = int(vm.group(1))
                for key in ("device.class", "device.name", "alsa.card", "node.name"):
                    m = re.search(rf"{re.escape(key)} = \"([^\"]+)\"", block)
                    if m:
                        sink[key.replace(".", "_")] = m.group(1)
                if sink.get("alsa_card"):
                    sink["alsa_card"] = int(sink["alsa_card"]) if str(sink["alsa_card"]).isdigit() else sink["alsa_card"]
                break
            sink["score"] = _score_sink(sink)
    else:
        for sink in sinks:
            sink["score"] = _score_sink(sink)
    return sinks


def select_preferred_sink(sinks: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    rows = sinks if sinks is not None else probe_pipewire_sinks()
    candidates = [s for s in rows if s.get("score", -1000) > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s.get("score", 0), s.get("volume_percent", 0)))


def _secure_gate(*, client_host: str | None = None) -> dict[str, Any]:
    try:
        from zocr_security import mandate_enforce
        return mandate_enforce("hardware_bind", client_host=client_host, require_seal=False)
    except ImportError:
        return {"ok": True, "degraded": True, "reason": "security_module_missing"}


def load_route_state() -> dict[str, Any]:
    path = _route_path()
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return doc
        except (OSError, json.JSONDecodeError):
            pass
    return {"schema": "queen-audio-route/v1", "bound": False}


def save_route_state(doc: dict[str, Any]) -> dict[str, Any]:
    path = _route_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updated"] = _ts()
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def get_queen_monitor_device() -> str:
    route = load_route_state()
    if route.get("bound") and route.get("monitor_source"):
        return str(route["monitor_source"])
    sink = route.get("sink_name") or ""
    if sink and not is_dummy_sink(sink):
        return f"{sink}.monitor"
    preferred = select_preferred_sink()
    if preferred and preferred.get("name"):
        return f"{preferred['name']}.monitor"
    return "@DEFAULT_MONITOR@"


def _remediation(*, pci: list, alsa: list, sinks: list) -> list[str]:
    policy = _load_policy()
    hints = list(policy.get("remediation") or [])
    if not Path("/dev/snd").exists():
        hints.insert(0, "No /dev/snd — ALSA kernel sound not loaded in this session")
    if pci and not alsa:
        hints.insert(0, f"PCI audio present ({len(pci)} device(s)) but no ALSA cards — driver not bound")
    dummy = [s for s in sinks if s.get("dummy")]
    if dummy and not any(not s.get("dummy") for s in sinks):
        hints.insert(0, "Only dummy PipeWire sinks (auto_null) — hardware not exposed to session")
    return hints[:8]


def probe_hardware() -> dict[str, Any]:
    pci = probe_pci_audio()
    alsa = probe_alsa_cards()
    sinks = probe_pipewire_sinks()
    preferred = select_preferred_sink(sinks)
    default_code, default_sink = _run(["pactl", "get-default-sink"])
    default_sink = default_sink if default_code == 0 else ""
    route = load_route_state()
    return {
        "ok": True,
        "schema": "zocr-hardware-audio-probe/v1",
        "updated": _ts(),
        "pci_audio": pci,
        "alsa_cards": alsa,
        "sinks": sinks,
        "sink_count": len(sinks),
        "hardware_sink_count": sum(1 for s in sinks if not s.get("dummy")),
        "default_sink": default_sink,
        "default_is_dummy": is_dummy_sink(default_sink),
        "preferred_sink": preferred,
        "route": route,
        "snd_dev_present": Path("/dev/snd").exists(),
        "remediation": _remediation(pci=pci, alsa=alsa, sinks=sinks),
        "never_fail": True,
    }


def bind_hardware_route(
    *,
    sink_name: str | None = None,
    force: bool = False,
    client_host: str | None = None,
) -> dict[str, Any]:
    gate = _secure_gate(client_host=client_host)
    if not gate.get("ok"):
        return {"ok": False, "schema": "zocr-hardware-audio-bind/v1", "error": "secure_gate", **gate}

    sinks = probe_pipewire_sinks()
    if sink_name:
        target = next((s for s in sinks if s.get("name") == sink_name), None)
        if not target:
            return {
                "ok": False,
                "schema": "zocr-hardware-audio-bind/v1",
                "error": "sink_not_found",
                "sink_name": sink_name,
            }
        if target.get("dummy") and not force:
            return {
                "ok": False,
                "schema": "zocr-hardware-audio-bind/v1",
                "error": "dummy_sink_denied",
                "sink_name": sink_name,
                "hint": "Use force=1 only for diagnostics — never for Queen production bind",
            }
    else:
        target = select_preferred_sink(sinks)

    if not target:
        probe = probe_hardware()
        return {
            "ok": False,
            "schema": "zocr-hardware-audio-bind/v1",
            "error": "no_hardware_sink",
            "bound": False,
            "remediation": probe.get("remediation"),
            "pci_audio": probe.get("pci_audio"),
            "alsa_cards": probe.get("alsa_cards"),
            "never_fail": True,
        }

    name = str(target["name"])
    monitor = f"{name}.monitor"
    steps: list[dict[str, Any]] = []

    code, _ = _run(["pactl", "set-default-sink", name])
    steps.append({"op": "set-default-sink", "target": name, "ok": code == 0})

    code, _ = _run(["pactl", "set-sink-mute", name, "0"])
    steps.append({"op": "unmute", "target": name, "ok": code == 0})

    vol = max(50, min(100, int(target.get("volume_percent") or 85)))
    if vol < 50:
        code, _ = _run(["pactl", "set-sink-volume", name, f"{vol}%"])
        steps.append({"op": "set-volume", "target": name, "percent": vol, "ok": code == 0})

    route_doc = {
        "schema": "queen-audio-route/v1",
        "bound": True,
        "sink_name": name,
        "monitor_source": monitor,
        "sink_description": target.get("description"),
        "sink_score": target.get("score"),
        "ingress_lane": "hardware",
        "secure_gate": gate,
        "bind_steps": steps,
        "pci_audio": probe_pci_audio(),
        "alsa_cards": probe_alsa_cards(),
    }
    save_route_state(route_doc)

    settings_path = _state_dir() / "field-audio-settings.json"
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["default_sink"] = name
            settings["sink_muted"] = False
            settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "ok": True,
        "schema": "zocr-hardware-audio-bind/v1",
        "updated": _ts(),
        "bound": True,
        "sink_name": name,
        "monitor_source": monitor,
        "sink_score": target.get("score"),
        "steps": steps,
        "route": route_doc,
        "secure_gate": gate,
        "never_fail": True,
    }


def hardware_audio_status() -> dict[str, Any]:
    probe = probe_hardware()
    route = load_route_state()
    monitor = get_queen_monitor_device()
    return {
        "ok": True,
        "schema": "zocr-hardware-audio-status/v1",
        "updated": _ts(),
        "bound": bool(route.get("bound")),
        "monitor_source": monitor,
        "route": route,
        "probe": probe,
        "ingress_lane": "hardware" if route.get("bound") else "degraded",
        "never_fail": True,
    }


def main() -> int:
    import sys

    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").strip()
    if cmd in ("status", "json"):
        print(json.dumps(hardware_audio_status(), ensure_ascii=False))
        return 0
    if cmd == "probe":
        print(json.dumps(probe_hardware(), ensure_ascii=False))
        return 0
    if cmd == "bind":
        sink = sys.argv[2] if len(sys.argv) > 2 else None
        force = "--force" in sys.argv
        print(json.dumps(bind_hardware_route(sink_name=sink, force=force), ensure_ascii=False))
        return 0
    if cmd == "monitor":
        print(json.dumps({"monitor_source": get_queen_monitor_device()}, ensure_ascii=False))
        return 0
    print(json.dumps({"error": "usage: zocr_hardware_audio.py [status|probe|bind [SINK]|monitor]"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())