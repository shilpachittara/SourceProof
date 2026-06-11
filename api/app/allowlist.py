"""SDF builder-image allowlist and build-environment trust evaluation.

The service never infers the toolchain from the deployed Wasm. It rebuilds in a
known, digest-pinned, SDF-allowlisted image and checks for a byte-match. This
module is the source of truth for which images are trusted, and is used both to
pick a build environment and to annotate a verification with its trust status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.config import settings


@dataclass(frozen=True)
class BuilderImage:
    name: str  # e.g. "stellar/stellar-cli:23.1.0"
    digest: str  # immutable: "sha256:..." (or "local" for the demo image)
    stellar_cli_version: str
    sdf_trusted: bool = True
    deprecated_after: Optional[date] = None  # still usable until this date
    revoked: bool = False  # security incident -> never use


# Seeded from the SDF-published image list. In production this is managed in a
# public, reviewed repo with SDF veto on additions. The demo's local builder
# image is included so the demo can show an "allowlisted" verification.
ALLOWLIST: dict[str, BuilderImage] = {
    settings.builder_image: BuilderImage(
        name=settings.builder_image,
        digest=settings.docker_image_digest,
        stellar_cli_version=settings.stellar_cli_version,
    ),
    "stellar/stellar-cli:23.1.0": BuilderImage(
        name="stellar/stellar-cli:23.1.0",
        digest="sha256:23a1c0de23a1c0de23a1c0de23a1c0de23a1c0de23a1c0de23a1c0de23a1c0de",
        stellar_cli_version="23.1.0",
    ),
    "stellar/stellar-cli:22.0.0": BuilderImage(
        name="stellar/stellar-cli:22.0.0",
        digest="sha256:2200c0de2200c0de2200c0de2200c0de2200c0de2200c0de2200c0de2200c0de",
        stellar_cli_version="22.0.0",
        deprecated_after=date(2026, 9, 1),
    ),
}


def lookup(name_or_digest: Optional[str]) -> Optional[BuilderImage]:
    """Resolve an image by its name (tag) or by its digest."""
    if not name_or_digest:
        return None
    if name_or_digest in ALLOWLIST:
        return ALLOWLIST[name_or_digest]
    for image in ALLOWLIST.values():
        if image.digest == name_or_digest:
            return image
    return None


def is_allowed(name_or_digest: Optional[str]) -> bool:
    image = lookup(name_or_digest)
    return bool(image and not image.revoked)


def active_images(today: Optional[date] = None) -> list[BuilderImage]:
    """Images we will try for a rebuild, newest CLI first, excluding revoked/deprecated."""
    today = today or date.today()
    usable = [
        img
        for img in ALLOWLIST.values()
        if not img.revoked
        and (img.deprecated_after is None or today <= img.deprecated_after)
    ]
    return sorted(usable, key=lambda i: i.stellar_cli_version, reverse=True)


def evaluate_build_image(build_metadata: Optional[dict]) -> Optional[dict]:
    """Derive an allowlist/trust descriptor for a completed build's metadata.

    Returns None if there is no build metadata yet (e.g. pending verification).
    """
    if not build_metadata:
        return None

    name = build_metadata.get("docker_image") or build_metadata.get("matched_image")
    digest = build_metadata.get("docker_image_digest")
    image = lookup(name) or lookup(digest)

    if image is None:
        return {
            "name": name,
            "digest": digest,
            "allowlisted": False,
            "sdf_trusted": False,
            "revoked": False,
        }
    return {
        "name": image.name,
        "digest": image.digest,
        "allowlisted": not image.revoked,
        "sdf_trusted": image.sdf_trusted,
        "revoked": image.revoked,
        "deprecated_after": image.deprecated_after.isoformat() if image.deprecated_after else None,
    }
