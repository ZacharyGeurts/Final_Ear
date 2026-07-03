#!/usr/bin/env pythong
"""Final_Ear smoke tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from zocr_ear import ear_status, final_ear_status, list_profiles
    from zocr_ear_truth import apply_truth_filters, truth_filter_status
    from zocr_ear_localize import localize_sources, correlate_existence
    from zocr_entity_ear import twin_ear_status, truth_forward
    from zocr_field_manual import field_manual_for_sense
    from zocr_virtual_ear import observe_virtual_ear, spawn_virtual_ear, virtual_ear_status
    from zocr_security import security_status
    from zocr_kill import kill_status
    from zocr_ear_stoard import stoard_status

    results: list[tuple[str, str]] = []

    def ok(cond: bool, msg: str) -> None:
        results.append(("PASS" if cond else "FAIL", msg))
        if not cond:
            raise AssertionError(msg)

    ok(ear_status().get("schema") == "zocr-ear-status/v1", "ear_status")
    ok(len(list_profiles()) >= 10, "equipment profiles")
    ok(final_ear_status().get("rule") is not None, "final_ear_status")
    ok(truth_filter_status().get("filters"), "truth filters")
    ok(apply_truth_filters(evidence={"mouth_correlation": 0.9}).get("ok"), "truth apply pass")
    loc = localize_sources(itd_us=80, level_db=-30)
    ok(loc.get("sources"), "localize")
    ok(correlate_existence(loc, sdf_entities=[{"bearing_deg": 5}]).get("correlation") is not None, "correlate")
    ok(twin_ear_status().get("living"), "twin ears")
    ok(truth_forward().get("ok"), "truth forward")
    manual = field_manual_for_sense("audio")
    ok(manual.get("ok") and manual.get("chapters"), "audio field manual")
    vision = field_manual_for_sense("vision")
    ok(vision.get("ok"), "vision field manual index")
    spawn = spawn_virtual_ear(mechanism="kinetic_eardrum", bearing_deg=30, distance_m=2, x_m=1, y_m=0.5, z_m=1)
    ok(spawn.get("ok"), "spawn kinetic eardrum")
    eid = (spawn.get("ear") or {}).get("id")
    ok(bool(eid), "virtual ear id")
    ok(observe_virtual_ear(eid).get("ok"), "observe virtual ear")
    ok(virtual_ear_status().get("count", 0) >= 1, "virtual ear count")
    ok(security_status().get("schema") == "zocr-ear-security-status/v1", "ear security status")
    ok(kill_status().get("schema") == "zocr-ear-kill-status/v1", "ear kill switches")
    ok(stoard_status().get("schema") == "zocr-ear-stoard-status/v1", "ear stoard status")
    from zocr_hardware_audio import hardware_audio_status, probe_hardware

    hw = hardware_audio_status()
    ok(hw.get("schema") == "zocr-hardware-audio-status/v1", "hardware audio status")
    probe = probe_hardware()
    ok(probe.get("schema") == "zocr-hardware-audio-probe/v1", "hardware audio probe")

    for s, m in results:
        print(f"  [{s}] {m}")
    print(f"\nFinal_Ear smoke: {sum(1 for s,_ in results if s=='PASS')} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())