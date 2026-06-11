"""Resolve external source inputs (GitHub repo @ commit) into a stored tarball.

The platform never builds directly from a live repo. Any external input is
snapshotted into our content-addressed tarball store at submission time, so the
verified artifact is immutable even if the upstream repo is changed or deleted.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings
from app.storage import load_tarball_by_hash

logger = logging.getLogger(__name__)

_GITHUB_URL = re.compile(
    r"^(?:https?://)?github\.com/(?P<owner>[\w.\-]+)/(?P<repo>[\w.\-]+?)(?:\.git)?/?$"
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

# IPFS is a first-tier retrieval channel: try multiple public gateways and fall
# back on failure. The required tarball_sha256 makes any gateway untrusted-but-usable.
IPFS_GATEWAYS = (
    "https://ipfs.io/ipfs/",
    "https://dweb.link/ipfs/",
    "https://cloudflare-ipfs.com/ipfs/",
)


def _normalize_sha256(value: str) -> str:
    cleaned = value.lower().strip().removeprefix("sha256:")
    if len(cleaned) != 64 or any(ch not in "0123456789abcdef" for ch in cleaned):
        raise SourceFetchError("tarball_sha256 must be a 64-character hex SHA-256 digest")
    return cleaned


class SourceFetchError(ValueError):
    pass


@dataclass
class FetchedSource:
    tarball_bytes: bytes
    origin: str
    repo_url: Optional[str] = None
    commit_sha: Optional[str] = None


def parse_github_url(url: str) -> tuple[str, str]:
    match = _GITHUB_URL.match(url.strip())
    if not match:
        raise SourceFetchError(
            "Expected a GitHub repo URL like https://github.com/owner/repo"
        )
    return match.group("owner"), match.group("repo")


async def _resolve_commit(owner: str, repo: str, ref: str) -> str:
    if _SHA_RE.match(ref) and len(ref) == 40:
        return ref.lower()

    api = f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}"
    headers = {"Accept": "application/vnd.github.sha"}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(api, headers=headers)
        if resp.status_code == 200 and _SHA_RE.match(resp.text.strip()):
            return resp.text.strip().lower()
        # Fallback to JSON commit API
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}",
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code != 200:
            raise SourceFetchError(
                f"Could not resolve ref '{ref}' for {owner}/{repo} (HTTP {resp.status_code})"
            )
        sha = resp.json().get("sha")
        if not sha:
            raise SourceFetchError(f"No commit SHA found for ref '{ref}'")
        return sha.lower()


async def _download_archive(owner: str, repo: str, commit: str) -> bytes:
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{commit}"
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise SourceFetchError(
                f"Failed to download archive for {owner}/{repo}@{commit[:7]} "
                f"(HTTP {resp.status_code})"
            )
        data = resp.content
    if len(data) > settings.max_tarball_bytes:
        raise SourceFetchError("Downloaded archive exceeds size limit")
    return data


def _repack_strip_toplevel(archive_bytes: bytes) -> bytes:
    """GitHub archives wrap everything in a `repo-sha/` directory.

    Re-tar with that wrapper stripped so the project root sits at the tarball
    root, matching what `stellar contract build` expects.
    """
    out = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as src:
        members = src.getmembers()
        if not members:
            raise SourceFetchError("Downloaded archive is empty")

        top = members[0].name.split("/")[0]
        prefix = f"{top}/"

        with tarfile.open(fileobj=out, mode="w:gz", format=tarfile.GNU_FORMAT) as dst:
            for member in members:
                if member.name == top:
                    continue
                if not member.name.startswith(prefix):
                    continue
                new_name = member.name[len(prefix):]
                if not new_name:
                    continue

                new_member = tarfile.TarInfo(name=new_name)
                new_member.size = member.size
                new_member.mode = member.mode
                new_member.type = member.type
                new_member.mtime = 0  # deterministic
                new_member.uid = new_member.gid = 0
                new_member.uname = new_member.gname = ""

                if member.isfile():
                    extracted = src.extractfile(member)
                    payload = extracted.read() if extracted else b""
                    dst.addfile(new_member, io.BytesIO(payload))
                elif member.isdir():
                    dst.addfile(new_member)
    return out.getvalue()


async def fetch_from_github(repo_url: str, ref: str) -> FetchedSource:
    owner, repo = parse_github_url(repo_url)
    commit = await _resolve_commit(owner, repo, ref or "HEAD")
    archive = await _download_archive(owner, repo, commit)
    tarball = _repack_strip_toplevel(archive)
    return FetchedSource(
        tarball_bytes=tarball,
        origin="github",
        repo_url=f"https://github.com/{owner}/{repo}",
        commit_sha=commit,
    )


def _candidate_urls(tarball_url: str) -> list[str]:
    if tarball_url.startswith("ipfs://"):
        cid = tarball_url[len("ipfs://"):].lstrip("/")
        if not cid:
            raise SourceFetchError("ipfs:// URL is missing a CID")
        return [gateway + cid for gateway in IPFS_GATEWAYS]
    return [tarball_url]


async def fetch_hosted_tarball(tarball_url: str, expected_sha256: Optional[str]) -> FetchedSource:
    """Fetch a hosted tarball over HTTPS or IPFS and verify its hash before use."""
    if not expected_sha256:
        # A hosted fetch is only trustworthy when pinned to a hash.
        raise SourceFetchError("tarball_url requires tarball_sha256 to be tamper-evident")
    expected = _normalize_sha256(expected_sha256)
    is_ipfs = tarball_url.startswith("ipfs://")

    last_error: Optional[Exception] = None
    for url in _candidate_urls(tarball_url):
        try:
            async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                last_error = SourceFetchError(f"{url} -> HTTP {resp.status_code}")
                continue
            data = resp.content
            if len(data) > settings.max_tarball_bytes:
                raise SourceFetchError("Hosted tarball exceeds size limit")

            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise SourceFetchError(
                    f"tarball_sha256 mismatch: expected sha256:{expected}, got sha256:{actual}"
                )
            return FetchedSource(
                tarball_bytes=data,
                origin="ipfs" if is_ipfs else "url",
                repo_url=tarball_url,
            )
        except httpx.HTTPError as exc:
            last_error = exc  # gateway/host down -> try the next candidate

    raise SourceFetchError(f"Could not fetch {tarball_url}: {last_error}")


def fetch_content_addressed(tarball_sha256: str) -> FetchedSource:
    """Resolve a hash-only submission from our content store (auditor-mediated)."""
    digest = _normalize_sha256(tarball_sha256)
    data = load_tarball_by_hash(digest)
    if data is None:
        raise SourceFetchError(
            f"No source on record for sha256:{digest}. "
            "Submit the tarball once before hash-only verification."
        )
    return FetchedSource(tarball_bytes=data, origin="content-addressed")
