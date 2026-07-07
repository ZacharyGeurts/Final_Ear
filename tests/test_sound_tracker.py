#!/usr/bin/env pythong
"""Sound tracker — GPS heading, motion, registry, pursuit, learn overlay."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from zocr_sound_registry import fingerprint, permanent_sound_id, register_sound, registry_status, resolve_sound
    from zocr_sound_tracker import (
        apply_pursuit_policy,
        bearing_to_gps,
        ingest_observations,
        operator_gps,
        predict_motion,
        sense_all,
        set_pursuit_policy,
        tick_source,
        tracker_status,
    )
    from zocr_desktop_audio import desktop_audio_status, harvest_desktop_sources
    from zocr_sound_learn import learn_from_observation, learn_status

    results: list[tuple[str, str]] = []

    def ok(cond: bool, msg: str) -> None:
        results.append(("PASS" if cond else "FAIL", msg))
        if not cond:
            raise AssertionError(msg)

    op = operator_gps()
    ok(op.get("ok") is True and op.get("lat") is not None, "operator GPS never fails")

    gps = bearing_to_gps(lat=op["lat"], lon=op["lon"], bearing_deg=90.0, distance_m=10.0)
    ok(gps.get("lat") != op["lat"] or gps.get("lon") != op["lon"], "bearing offset GPS")

    fp = fingerprint({"ingress_lane": "desktop", "source_key": "pulse:1", "bearing_deg": 12})
    sid = permanent_sound_id(fp)
    ok(sid.startswith("snd_"), "permanent sound id prefix")

    with tempfile.TemporaryDirectory() as tmp:
        reg_path = Path(tmp) / "sound-registry.json"
        state_path = Path(tmp) / "sound-tracker-state.json"
        learn_path = Path(tmp) / "sound-learn-state.json"

        import zocr_sound_registry as reg_mod
        import zocr_sound_tracker as tr_mod
        import zocr_sound_learn as learn_mod

        reg_mod.REGISTRY_PATH = reg_path
        tr_mod.STATE_PATH = state_path
        learn_mod.LEARN_STATE = learn_path

        obs = {
            "ingress_lane": "desktop",
            "source_key": "pulse:test",
            "label": "Test App",
            "kind": "browser",
            "bearing_deg": 30.0,
            "level_db": -18.0,
            "itd_us": 80.0,
        }
        reg = register_sound(obs)
        ok(reg.get("ok") is True and reg.get("sound_id"), "register sound")

        tick = tick_source(obs, learn=False)
        ok(tick.get("ok") is True, "tick source")
        track = tick.get("track") or {}
        ok(track.get("gps_heading", {}).get("lat") is not None, "GPS heading on sound")
        ok(track.get("heading_deg") is not None, "heading on track")
        ok(track.get("permanent") is True, "permanent flag")

        hist = [
            {"bearing_deg": 10, "distance_m": 5},
            {"bearing_deg": 14, "distance_m": 4.5},
            {"bearing_deg": 18, "distance_m": 4.0},
        ]
        motion = predict_motion(hist, cfg={"motion": {"moving_speed_mps": 0.2, "history_ticks": 12}})
        ok("is_moving" in motion and "direction_deg" in motion, "motion prediction")

        pursuit = apply_pursuit_policy({**track, "motion": motion}, policy="chase")
        ok(pursuit.get("action") == "pursue", "chase policy")

        avoid = apply_pursuit_policy(track, policy="avoid")
        ok(avoid.get("action") == "steer_away", "avoid policy")

        tr_mod._save_state({"schema": "zocr-sound-tracker-state/v1", "tracks": {track["sound_id"]: track}})
        pol = set_pursuit_policy(track["sound_id"], "shadow")
        ok(pol.get("ok") is True and pol.get("policy") == "shadow", "set pursuit policy")

        ingest = ingest_observations([obs, {**obs, "source_key": "pulse:other", "bearing_deg": -20}], learn=False)
        ok(ingest.get("count") == 2, "ingest multiple")

        st = registry_status()
        ok(st.get("stats", {}).get("total", 0) >= 1, "registry stats")

        resolved = resolve_sound(track["sound_id"])
        ok(resolved.get("ok") is True, "resolve permanent id")

    desk = desktop_audio_status()
    ok(desk.get("ok") is True and desk.get("never_fail") is True, "desktop status never fails")
    sources = harvest_desktop_sources()
    ok(len(sources) >= 1, "desktop harvest sources")

    all_sense = sense_all(learn=False)
    ok(all_sense.get("ok") is True and all_sense.get("ingress_total", 0) >= 1, "sense all lanes")

    learn_st = learn_status()
    ok(learn_st.get("priority_safe") is True, "learn priority safe")

    fake_track = {
        "sound_id": "snd_testlearn",
        "ingress_lane": "desktop",
        "source_key": "pulse:learn",
        "label": "Learn Test",
        "bearing_deg": 5,
        "level_db": -20,
        "motion": {"is_moving": False},
    }
    learn_out = learn_from_observation(fake_track)
    ok(learn_out.get("overlay_only") is True, "overlay only learn")
    ok(learn_out.get("never_override_priorities") is True, "never override priorities")

    tr_status = tracker_status()
    ok(tr_status.get("never_fail") is True and tr_status.get("zero_cost") is True, "tracker posture")

    for s, m in results:
        print(f"  [{s}] {m}")
    print(f"\nSound tracker tests: {sum(1 for s, _ in results if s == 'PASS')} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())