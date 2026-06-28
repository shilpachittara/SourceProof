"""SEP-58 build argument normalization (bldarg / bldopt) for reproducible replay."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Optional

_PACKAGE_FLAG = re.compile(r"^--package(?:=|\s)")
_MANIFEST_FLAG = re.compile(r"^--manifest-path(?:=|\s)")


class BuildMetaError(ValueError):
    """Invalid or incomplete SEP-58 build metadata."""


def bldopt_string_to_args(bldopt: str) -> list[str]:
    """Split a legacy single-string bldopt into shell-style arguments."""
    return shlex.split(bldopt.strip())


def bldopt_list_to_bldarg(bldopt_values: list[str]) -> list[str]:
    """Translate repeating SEP-58 bldopt entries to an ordered bldarg replay list."""
    flags: list[str] = []
    for value in bldopt_values:
        flags.extend(bldopt_string_to_args(value))
    if not flags:
        return []
    if flags[0] in ("contract", "stellar", "cargo"):
        return flags
    return ["contract", "build", *flags]


def resolve_bldarg(
    *,
    bldarg_values: Optional[list[str]] = None,
    bldopt_values: Optional[list[str]] = None,
    bldopt: Optional[str] = None,
) -> list[str]:
    """Pick the best available ordered build argument list for replay."""
    if bldarg_values:
        return list(bldarg_values)
    if bldopt_values:
        return bldopt_list_to_bldarg(bldopt_values)
    if bldopt:
        return bldopt_list_to_bldarg([bldopt])
    return ["contract", "build"]


def bldarg_to_bldopt_string(bldarg: list[str]) -> Optional[str]:
    """Compact legacy bldopt string for storage/display (flags only)."""
    if not bldarg:
        return None
    if bldarg[:2] == ["contract", "build"]:
        flags = bldarg[2:]
    elif bldarg and bldarg[0] == "contract":
        flags = bldarg[1:]
    else:
        flags = bldarg
    return " ".join(flags) if flags else None


def parse_source_identity_from_args(args: list[str]) -> Optional[dict[str, str]]:
    """Extract cargo package / manifest identity from build arguments."""
    out: dict[str, str] = {}
    for arg in args:
        if arg.startswith("--package="):
            out["package"] = arg.split("=", 1)[1]
        elif arg == "--package" or arg.startswith("--package "):
            continue
        elif arg.startswith("--manifest-path="):
            out["manifest_path"] = arg.split("=", 1)[1]
    # Also accept `--package foo` split across argv entries.
    for idx, arg in enumerate(args):
        if arg == "--package" and idx + 1 < len(args):
            out.setdefault("package", args[idx + 1])
        if arg == "--manifest-path" and idx + 1 < len(args):
            out.setdefault("manifest_path", args[idx + 1])
    return out or None


def has_package_selector(args: list[str]) -> bool:
    return any(_PACKAGE_FLAG.match(a) or _MANIFEST_FLAG.match(a) for a in args)


def count_workspace_crates(source_dir: Path) -> int:
    """Count workspace member crates (1 for a single-crate repo)."""
    root_cargo = source_dir / "Cargo.toml"
    if not root_cargo.is_file():
        return 0
    text = root_cargo.read_text(encoding="utf-8")
    if "[workspace]" not in text:
        return 1
    members = re.findall(r"members\s*=\s*\[([^\]]+)\]", text, re.DOTALL)
    if not members:
        return 1
    paths = re.findall(r'"([^"]+)"', members[0])
    return max(len(paths), 1)


def require_package_selector(source_dir: Path, bldarg: list[str]) -> None:
    """Enforce fnando/ethanfrey guidance: monorepos must declare --package or --manifest-path."""
    if has_package_selector(bldarg):
        return
    if count_workspace_crates(source_dir) <= 1:
        return
    raise BuildMetaError(
        "Monorepo source requires --package or --manifest-path in SEP-58 build metadata"
    )


def meta_lists_from_onchain(onchain_meta: Optional[dict]) -> tuple[list[str], list[str]]:
    if not onchain_meta:
        return [], []
    bldarg = list(onchain_meta.get("bldarg_list") or [])
    bldopt = list(onchain_meta.get("bldopt_list") or [])
    return bldarg, bldopt
