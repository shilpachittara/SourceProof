"""Run Soroban builds inside the pinned builder Docker image."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.storage import sha256_hex

logger = logging.getLogger(__name__)


class BuildError(RuntimeError):
    pass


@dataclass
class BuildResult:
    wasm_bytes: bytes
    wasm_hash: str
    build_metadata: dict[str, str]


def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "version"],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _inspect_image_digest(image: str) -> str:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Id}}", image],
            check=True,
            capture_output=True,
            text=True,
        )
        digest = result.stdout.strip()
        return digest or settings.docker_image_digest
    except subprocess.CalledProcessError:
        return settings.docker_image_digest


def _stellar_cli_version(image: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "stellar", image or settings.builder_image, "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return settings.stellar_cli_version


def _rustc_version(image: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "rustc", image or settings.builder_image, "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def _soroban_sdk_version(lock_path: Path) -> str | None:
    """Best-effort parse of soroban-sdk version from a Cargo.lock file."""
    if not lock_path.is_file():
        return None
    try:
        in_package = False
        for line in lock_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "[[package]]":
                in_package = False
                continue
            if stripped == 'name = "soroban-sdk"':
                in_package = True
                continue
            if in_package and stripped.startswith("version = "):
                return stripped.split("=", 1)[1].strip().strip('"')
    except OSError:
        return None
    return None


def build_contract(
    source_dir: Path,
    output_dir: Path,
    image: str | None = None,
    bldopt: str | None = None,
) -> BuildResult:
    if not _docker_available():
        raise BuildError("Docker is not available. Install Docker and build the builder image.")

    builder_image = image or settings.builder_image

    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()

    # When the API runs in a container talking to the host Docker daemon, the -v
    # mount paths must be host paths, not this container's paths.
    host_source = settings.host_path_for(str(source_dir))
    host_output = settings.host_path_for(str(output_dir))

    cmd = ["docker", "run", "--rm"]
    if settings.builder_network_disabled:
        cmd.extend(["--network", "none"])
    if bldopt:
        cmd.extend(["-e", f"BLDOPT={bldopt}"])
    cmd.extend(
        [
            "-v",
            f"{host_source}:/source:ro",
            "-v",
            f"{host_output}:/output",
            builder_image,
        ]
    )

    logger.info("Running builder container: %s", " ".join(cmd))
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=settings.build_timeout_seconds,
    )

    if completed.returncode != 0:
        details = completed.stderr or completed.stdout or "unknown build failure"
        raise BuildError(details.strip())

    wasm_path = output_dir / "contract.wasm"
    if not wasm_path.exists():
        raise BuildError("Builder did not produce /output/contract.wasm")

    wasm_bytes = wasm_path.read_bytes()
    sdk_version = _soroban_sdk_version(output_dir / "Cargo.lock") or _soroban_sdk_version(
        source_dir / "Cargo.lock"
    )
    metadata = {
        "docker_image": builder_image,
        "docker_image_digest": _inspect_image_digest(builder_image),
        "stellar_cli_version": _stellar_cli_version(builder_image),
        "rustc_version": _rustc_version(builder_image),
        "build_profile": "release",
        "verifier_instance_id": settings.verifier_instance_id,
    }
    if bldopt:
        metadata["applied_bldopt"] = bldopt
    if sdk_version:
        metadata["soroban_sdk_version"] = sdk_version
    return BuildResult(
        wasm_bytes=wasm_bytes,
        wasm_hash=sha256_hex(wasm_bytes),
        build_metadata=metadata,
    )


def build_contract_local(source_dir: Path, output_dir: Path) -> BuildResult:
    """Fallback when stellar-cli is installed on the host (dev without Docker rebuild)."""
    if not shutil.which("stellar"):
        raise BuildError(
            "Local build requested (use_docker=false) but the 'stellar' CLI is not "
            "installed in this environment. Either submit with use_docker=true and run "
            "`make builder` (recommended), or install the Stellar CLI on the host."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            ["stellar", "contract", "build"],
            cwd=source_dir,
            capture_output=True,
            text=True,
            timeout=settings.build_timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise BuildError(
            "Local build requested (use_docker=false) but the 'stellar' CLI is not "
            "installed. Submit with use_docker=true and run `make builder`, or install "
            "the Stellar CLI."
        ) from exc
    if completed.returncode != 0:
        raise BuildError((completed.stderr or completed.stdout).strip())

    candidates = list((source_dir / "target/wasm32v1-none/release").glob("*.wasm"))
    if not candidates:
        raise BuildError("No wasm artifact found after local build")

    wasm_bytes = candidates[0].read_bytes()
    (output_dir / "contract.wasm").write_bytes(wasm_bytes)
    metadata = {
        "docker_image": "host-stellar-cli",
        "docker_image_digest": "host",
        "stellar_cli_version": _host_stellar_version(),
        "rustc_version": _host_rustc_version(),
        "build_profile": "release",
        "verifier_instance_id": settings.verifier_instance_id,
    }
    return BuildResult(
        wasm_bytes=wasm_bytes,
        wasm_hash=sha256_hex(wasm_bytes),
        build_metadata=metadata,
    )


def _host_stellar_version() -> str:
    try:
        result = subprocess.run(["stellar", "--version"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _host_rustc_version() -> str:
    try:
        result = subprocess.run(["rustc", "--version"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
