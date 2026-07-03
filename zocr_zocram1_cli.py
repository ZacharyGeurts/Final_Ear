#!/usr/bin/env pythong
"""CLI — pack, unpack, verify ZOCRAM1/GAC1 audio."""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _sine_pcm(*, sample_rate: int, channels: int, seconds: float, freq: float) -> bytes:
    import math

    n = int(sample_rate * seconds)
    out = bytearray()
    for i in range(n):
        s = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
        for _ in range(channels):
            out.extend(struct.pack("<h", s))
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="ZOCRAM1 / GAC1 sovereign audio")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pack = sub.add_parser("pack", help="Pack raw int16 PCM into .zocr")
    p_pack.add_argument("src")
    p_pack.add_argument("dest")
    p_pack.add_argument("--rate", type=int, default=48000)
    p_pack.add_argument("--channels", type=int, default=2)
    p_pack.add_argument("--profile", default="binaural_safe")

    p_demo = sub.add_parser("demo", help="Write demo tone .zocr")
    p_demo.add_argument("dest")
    p_demo.add_argument("--profile", default="cochlear_safe")

    p_unpack = sub.add_parser("unpack", help="Decode .zocr to raw PCM")
    p_unpack.add_argument("src")
    p_unpack.add_argument("dest")

    p_verify = sub.add_parser("verify", help="Verify seals and meta")
    p_verify.add_argument("src")

    args = parser.parse_args()
    from zocr_zocram1.container import decode_zocram, pack_pcm_file, verify_zocram, write_zocram

    if args.cmd == "pack":
        out = pack_pcm_file(Path(args.src), Path(args.dest), sample_rate=args.rate, channels=args.channels, profile_name=args.profile)
    elif args.cmd == "demo":
        pcm = _sine_pcm(sample_rate=48000, channels=2, seconds=2.0, freq=440.0)
        out = write_zocram(Path(args.dest), pcm, sample_rate=48000, channels=2, profile_name=args.profile)
    elif args.cmd == "unpack":
        pcm, meta = decode_zocram(Path(args.src))
        Path(args.dest).write_bytes(pcm)
        out = {"ok": True, "bytes": len(pcm), "meta": meta}
    else:
        out = verify_zocram(Path(args.src))

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())