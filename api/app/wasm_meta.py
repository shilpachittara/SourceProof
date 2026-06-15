"""Read Soroban contract metadata embedded in on-chain Wasm.

`stellar contract build` records metadata in a Wasm custom section named
`contractmetav0` as a stream of XDR `SCMetaEntry` (key/value strings). Standard
keys include:
  - rsver     : rustc version used to build the contract
  - rssdkver  : soroban-sdk version (+ git hash)
  - bldimg    : (SEP-58) the builder image the deployer declares was used

We use this for two things:
  1. Explain mismatches ("on-chain built with rustc 1.90; verifier uses 1.89").
  2. Honor a declared `bldimg` when selecting the build environment.

This is best-effort: any parse error returns an empty dict and never blocks
verification (the byte-for-byte hash comparison is the source of truth).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_WASM_MAGIC = b"\x00asm"
META_SECTION = "contractmetav0"
ENV_META_SECTION = "contractenvmetav0"


def _read_uleb128(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated LEB128")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, pos


def _iter_custom_sections(wasm: bytes):
    """Yield (name, content_bytes) for each Wasm custom section (id 0)."""
    if wasm[:4] != _WASM_MAGIC:
        return
    pos = 8  # skip magic (4) + version (4)
    n = len(wasm)
    while pos < n:
        section_id = wasm[pos]
        pos += 1
        size, pos = _read_uleb128(wasm, pos)
        end = pos + size
        if end > n:
            break
        if section_id == 0:  # custom section
            name_len, name_pos = _read_uleb128(wasm, pos)
            name = wasm[name_pos:name_pos + name_len].decode("utf-8", "replace")
            content = wasm[name_pos + name_len:end]
            yield name, content
        pos = end


def _decode_meta_entries(content: bytes) -> dict[str, str]:
    """Decode a stream of XDR SCMetaEntry (SC_META_V0 key/val strings)."""
    out: dict[str, str] = {}
    try:
        from xdrlib3 import Unpacker
        from stellar_sdk.xdr import SCMetaEntry

        up = Unpacker(content)
        while up.get_position() < len(content):
            entry = SCMetaEntry.unpack(up)
            v0 = getattr(entry, "v0", None)
            if v0 is None:
                continue
            key = v0.key
            val = v0.val
            key_s = key.decode("utf-8", "replace") if isinstance(key, (bytes, bytearray)) else str(key)
            val_s = val.decode("utf-8", "replace") if isinstance(val, (bytes, bytearray)) else str(val)
            out[key_s] = val_s
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.debug("Could not decode contract meta entries: %s", exc)
    return out


def parse_wasm_metadata(wasm_bytes: Optional[bytes]) -> dict[str, str]:
    """Return a dict of on-chain contract metadata (rsver, rssdkver, bldimg, …).

    Empty dict when there is no metadata or it cannot be parsed.
    """
    if not wasm_bytes:
        return {}
    try:
        meta: dict[str, str] = {}
        for name, content in _iter_custom_sections(wasm_bytes):
            if name == META_SECTION:
                meta.update(_decode_meta_entries(content))
        return meta
    except Exception as exc:  # noqa: BLE001
        logger.debug("Wasm metadata parse failed: %s", exc)
        return {}


def declared_build_image(meta: dict[str, str]) -> Optional[str]:
    """Return the SEP-58 declared builder image (`bldimg`) if present."""
    if not meta:
        return None
    for key in ("bldimg", "build_image", "buildimg"):
        if meta.get(key):
            return meta[key]
    return None


def declared_bldopt(meta: dict[str, str]) -> Optional[str]:
    if not meta:
        return None
    return meta.get("bldopt")


def declared_source_repo(meta: dict[str, str]) -> Optional[str]:
    if not meta:
        return None
    for key in ("source_repo", "sourcerepo"):
        if meta.get(key):
            return meta[key]
    return None


def declared_source_rev(meta: dict[str, str]) -> Optional[str]:
    if not meta:
        return None
    for key in ("source_rev", "sourcerev", "source_commit"):
        if meta.get(key):
            return meta[key]
    return None
