from __future__ import annotations

from pathlib import Path

import pytest

from app.build_meta import (
    BuildMetaError,
    bldopt_list_to_bldarg,
    bldopt_string_to_args,
    count_workspace_crates,
    parse_source_identity_from_args,
    require_package_selector,
    resolve_bldarg,
)


def test_bldopt_list_becomes_ordered_bldarg() -> None:
    args = bldopt_list_to_bldarg(["--package=token", "--optimize"])
    assert args == ["contract", "build", "--package=token", "--optimize"]


def test_bldarg_passthrough() -> None:
    raw = ["contract", "build", "--package=counter"]
    assert resolve_bldarg(bldarg_values=raw) == raw


def test_parse_source_identity_from_bldarg() -> None:
    identity = parse_source_identity_from_args(
        ["contract", "build", "--package=token", "--manifest-path=contracts/token/Cargo.toml"]
    )
    assert identity == {
        "package": "token",
        "manifest_path": "contracts/token/Cargo.toml",
    }


def test_require_package_selector_in_monorepo(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["contracts/a", "contracts/b"]\n',
        encoding="utf-8",
    )
    with pytest.raises(BuildMetaError, match="Monorepo"):
        require_package_selector(root, ["contract", "build"])


def test_single_crate_skips_package_requirement(tmp_path: Path) -> None:
    root = tmp_path / "single"
    root.mkdir()
    (root / "Cargo.toml").write_text('[package]\nname = "demo"\n', encoding="utf-8")
    require_package_selector(root, ["contract", "build"])
    assert count_workspace_crates(root) == 1


def test_bldopt_string_split() -> None:
    assert bldopt_string_to_args("--package foo --optimize") == [
        "--package",
        "foo",
        "--optimize",
    ]
