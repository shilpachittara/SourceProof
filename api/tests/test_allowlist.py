from __future__ import annotations

from datetime import date

from app import allowlist
from app.config import settings


def test_configured_builder_image_is_allowlisted() -> None:
    assert allowlist.is_allowed(settings.builder_image)


def test_unknown_image_not_allowed() -> None:
    assert not allowlist.is_allowed("evil/image:latest")
    assert not allowlist.is_allowed(None)


def test_active_images_excludes_deprecated() -> None:
    after_deprecation = date(2027, 1, 1)
    active = allowlist.active_images(today=after_deprecation)
    names = {img.name for img in active}
    assert "stellar/stellar-cli:22.0.0" not in names  # deprecated 2026-09-01
    assert settings.builder_image in names


def test_evaluate_build_image_allowlisted() -> None:
    meta = {"docker_image": settings.builder_image, "docker_image_digest": "local"}
    info = allowlist.evaluate_build_image(meta)
    assert info is not None
    assert info["allowlisted"] is True
    assert info["sdf_trusted"] is True


def test_evaluate_build_image_not_allowlisted() -> None:
    meta = {"docker_image": "random/image:1.0", "docker_image_digest": "sha256:dead"}
    info = allowlist.evaluate_build_image(meta)
    assert info is not None
    assert info["allowlisted"] is False


def test_evaluate_build_image_none_when_no_metadata() -> None:
    assert allowlist.evaluate_build_image(None) is None
