#!/usr/bin/env pythong
"""Secure neural path — sovereign time, signal intel, eye-ear fusion."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from zocr_sovereign_time import seal_ear_tick, sovereign_time_status, verify_eye_ear_sync
    from zocr_ear_signal_intel import identify_sound, score_encoded_signal, score_mixed_interference
    from zocr_eye_ear_fusion import secure_neural_path
    from zocr_ear_truth import apply_truth_filters, truth_filter_status

    results: list[tuple[str, str]] = []

    def ok(cond: bool, msg: str) -> None:
        results.append(("PASS" if cond else "FAIL", msg))
        if not cond:
            raise AssertionError(msg)

    tick = seal_ear_tick(reason="test")
    ok(tick.get("sealed_mono_ns") is not None, "seal ear tick")
    st = sovereign_time_status(seal=False)
    ok(st.get("always") is True, "sovereign always on")

    sync = verify_eye_ear_sync(eye_mono_ns=tick["sealed_mono_ns"], ear_mono_ns=tick["sealed_mono_ns"])
    ok(sync.get("ok") is True, "sync same mono")

    bad_sync = verify_eye_ear_sync(eye_mono_ns=1, ear_mono_ns=10_000_000_000)
    ok(bad_sync.get("desync") is True, "desync detected")

    enc = score_encoded_signal(evidence={"zcr": 0.5, "entropy": 7.5, "fsk_pattern": True})
    ok(enc.get("ok") is False, "encoded signal trip")

    mix = score_mixed_interference(evidence={"snr_db": 4.0, "phase_decoherence": 0.5}, sources=[{}, {}])
    ok(mix.get("ok") is False, "interference trip")

    clear = identify_sound(evidence={"mouth_correlation": 0.9, "speech_present": True, "rms": 1200, "zcr": 0.1, "sovereign_time_ok": True, "provenance_weave_ok": True})
    ok(clear.get("accurate") is True, "clear identification")

    tf = truth_filter_status()
    ok("encoded_signal" in (tf.get("filters") or []), "encoded filter listed")

    truth = apply_truth_filters(evidence={"sovereign_time_ok": True, "provenance_weave_ok": True, "mouth_correlation": 0.9}, existence={"correlation": 0.85})
    ok(truth.get("ok") is True, "truth pass")

    fusion = secure_neural_path(
        evidence={"mouth_correlation": 0.88, "speech_present": True, "rms": 1500, "zcr": 0.08, "sovereign_time_ok": True, "provenance_weave_ok": True},
        existence={"correlation": 0.82},
        localization={"bearing_deg": 15},
        require_sync=True,
    )
    ok(fusion.get("schema") == "zocr-secure-neural-path/v1", "fusion schema")
    ok(fusion.get("sovereign_time", {}).get("never_desync") is True, "never desync flag")
    ok("identification" in fusion, "fusion identification")

    for s, m in results:
        print(f"  [{s}] {m}")
    print(f"\nSecure path tests: {sum(1 for s, _ in results if s == 'PASS')} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())