from __future__ import annotations

from app.wasm_meta import WasmMeta, wasm_meta_to_storage_dict


def test_storage_dict_preserves_repeating_sep58_keys() -> None:
    parsed = WasmMeta(
        scalars={"rsver": "1.89.0", "source_repo": "https://github.com/example/repo"},
        bldopt=["--package=token", "--optimize"],
        bldarg=["contract", "build", "--package=token"],
    )
    stored = wasm_meta_to_storage_dict(parsed)
    assert stored["bldopt_list"] == ["--package=token", "--optimize"]
    assert stored["bldarg_list"] == ["contract", "build", "--package=token"]
    assert stored["bldopt"] == "--optimize"
    assert stored["bldarg"] == "--package=token"
