#!/usr/bin/env pythong
"""GAC1 / ZOCRAM1 round-trip and seal tests."""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _tone(seconds: float = 1.0, rate: int = 48000, ch: int = 2) -> bytes:
    import math

    n = int(rate * seconds)
    out = bytearray()
    for i in range(n):
        s = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
        for _ in range(ch):
            out.extend(struct.pack("<h", s))
    return bytes(out)


def _silence(seconds: float = 0.5, rate: int = 48000, ch: int = 2) -> bytes:
    return b"\x00" * int(rate * seconds * ch * 2)


def main() -> int:
    from zocr_zocram1.container import decode_zocram, verify_zocram, write_zocram
    from zocr_zocram1.codec_gac1 import pcm_compression_ratio
    from zocr_zocram1.spec import CODEC_ID, FORMAT_ID, load_spec

    results: list[tuple[str, str]] = []

    def ok(cond: bool, msg: str) -> None:
        results.append(("PASS" if cond else "FAIL", msg))
        if not cond:
            raise AssertionError(msg)

    spec = load_spec()
    ok(spec.get("codec_id") == "GAC1", "spec codec")
    ok(FORMAT_ID == "ZOCRAM1" and CODEC_ID == "GAC1", "constants")

    pcm = _tone(1.0) + _silence(0.5) + _tone(0.5, rate=48000)

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "test.zocr"

        info = write_zocram(path, pcm, sample_rate=48000, channels=2, profile_name="lossless")
        ok(info.get("ok") is True, "write lossless")
        ok(path.is_file(), "file exists")
        ok(info.get("compression_vs_pcm", 0) >= 1.0, "compression ratio reported")

        v = verify_zocram(path)
        ok(v.get("ok") is True, "verify seals")
        ok(v.get("sovereign_time"), "sovereign time in meta")

        decoded, meta = decode_zocram(path)
        ok(len(decoded) >= len(pcm), "decode length")
        ok(decoded[: len(pcm)] == pcm, "lossless round trip")

        fast_path = Path(td) / "fast.zocr"
        finfo = write_zocram(fast_path, pcm, profile_name="fast")
        ok(finfo.get("compression_vs_pcm", 0) >= 1.5, "fast profile compresses vs pcm")

        cochlear_path = Path(td) / "cochlear.zocr"
        write_zocram(cochlear_path, pcm, profile_name="cochlear_safe")
        cmeta = verify_zocram(cochlear_path)
        ok(cmeta.get("cochlear_limit_db") == -3.0, "cochlear profile meta")

    for s, m in results:
        print(f"  [{s}] {m}")
    print(f"\nGAC1 tests: {sum(1 for s, _ in results if s == 'PASS')} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())