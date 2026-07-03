"""ZOCRAM1 + GAC1 — sovereign audio format for Final_Ear."""
from zocr_zocram1.codec_gac1 import decode_chunks, encode_pcm, pcm_compression_ratio, shannon_entropy
from zocr_zocram1.container import decode_zocram, pack_pcm_file, read_zocram, verify_zocram, write_zocram
from zocr_zocram1.spec import CODEC_ID, FORMAT_ID

__all__ = [
    "CODEC_ID",
    "FORMAT_ID",
    "decode_chunks",
    "decode_zocram",
    "encode_pcm",
    "pack_pcm_file",
    "pcm_compression_ratio",
    "read_zocram",
    "shannon_entropy",
    "verify_zocram",
    "write_zocram",
]