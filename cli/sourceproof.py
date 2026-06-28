#!/usr/bin/env python3
"""sourceproof — developer CLI for the SourceProof verification API.

Stdlib-only (no pip installs) so it drops into any environment and is easy to
wire into stellar-cli workflows. Mirrors the SEP-58 source modes.

Examples
  # Upload a tarball and wait for the result
  sourceproof verify --network testnet \\
    --contract-id CB4I... --source ./demo-contract-source.tar.gz --wait

  # Public repo (SEP-58 source_repo + source_rev)
  sourceproof verify --network testnet --contract-id CB4I... \\
    --source-repo https://github.com/owner/repo --source-rev <sha> --wait

  # Hosted tarball / IPFS (SEP-58 tarball_url + tarball_sha256)
  sourceproof verify --network mainnet --contract-id CC... \\
    --tarball-url ipfs://<cid> --tarball-sha256 <hex> --wait

  # Content-addressed (already-uploaded source)
  sourceproof verify --network testnet --contract-id CB4I... --tarball-sha256 <hex>

  sourceproof status <verification_id>
  sourceproof lookup testnet CB4I...
  sourceproof wasm <wasm_hash>
  sourceproof wasm-contracts <wasm_hash>
  sourceproof badge testnet CB4I... [--format json|svg]
  sourceproof list [--network testnet] [--status verified]
  sourceproof info
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_API = os.environ.get("SOURCEPROOF_API", "http://127.0.0.1:8080")


def _format_api_error(data: dict) -> str:
    detail = data.get("detail")
    if isinstance(detail, dict):
        code = detail.get("code", "error")
        message = detail.get("message", detail)
        return f"{code}: {message}"
    return str(detail or data)


def _encode_multipart(fields: dict[str, str], file_field: str | None, file_path: str | None):
    boundary = f"----sourceproof{uuid.uuid4().hex}"
    crlf = b"\r\n"
    body = bytearray()
    for name, value in fields.items():
        if value is None:
            continue
        body += b"--" + boundary.encode() + crlf
        body += f'Content-Disposition: form-data; name="{name}"'.encode() + crlf + crlf
        body += str(value).encode() + crlf
    if file_field and file_path:
        fname = os.path.basename(file_path)
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        with open(file_path, "rb") as fh:
            data = fh.read()
        body += b"--" + boundary.encode() + crlf
        body += (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{fname}"'.encode()
            + crlf
        )
        body += f"Content-Type: {ctype}".encode() + crlf + crlf
        body += data + crlf
    body += b"--" + boundary.encode() + b"--" + crlf
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _request(method: str, url: str, *, body=None, content_type=None):
    req = urllib.request.Request(url, data=body, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except Exception:
            return exc.code, {"detail": exc.reason}
    except urllib.error.URLError as exc:
        print(f"error: cannot reach {url}: {exc.reason}", file=sys.stderr)
        sys.exit(2)


def cmd_verify(args: argparse.Namespace) -> int:
    fields = {
        "network": args.network,
        "contract_id": args.contract_id,
        "wasm_hash": args.wasm_hash,
        "source_repo": args.source_repo,
        "source_rev": args.source_rev,
        "tarball_url": args.tarball_url,
        "tarball_sha256": args.tarball_sha256,
        "bldopt": args.bldopt,
    }
    body, ctype = _encode_multipart(
        fields, "source" if args.source else None, args.source
    )
    status, data = _request("POST", f"{args.api}/v1/verify", body=body, content_type=ctype)
    if status >= 400:
        print(f"submit failed ({status}): {_format_api_error(data)}", file=sys.stderr)
        return 1
    vid = data.get("verification_id")
    if data.get("idempotent"):
        print(f"existing job: {vid}  ({data.get('source_origin')})")
    else:
        print(f"queued: {vid}  ({data.get('source_origin')})")
    if not args.wait:
        print(f"poll: {args.api}/v1/verifications/{vid}")
        return 0
    return _poll(args.api, vid, args.timeout)


def _poll(api: str, vid: str, timeout: int) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _s, data = _request("GET", f"{api}/v1/verifications/{vid}")
        st = data.get("status")
        if st and st != "pending":
            print(json.dumps(data, indent=2))
            return 0 if st == "verified" else 1
        time.sleep(3)
    print("timed out waiting for verification", file=sys.stderr)
    return 1


def cmd_status(args: argparse.Namespace) -> int:
    status, data = _request("GET", f"{args.api}/v1/verifications/{args.verification_id}")
    print(json.dumps(data, indent=2))
    return 0 if status < 400 else 1


def cmd_lookup(args: argparse.Namespace) -> int:
    status, data = _request("GET", f"{args.api}/v1/{args.network}/contracts/{args.contract_id}")
    if status >= 400:
        print(_format_api_error(data), file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


def cmd_badge(args: argparse.Namespace) -> int:
    base = f"{args.api}/v1/{args.network}/contracts/{args.contract_id}/badge"
    if args.format == "svg":
        url = f"{base}.svg"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as resp:
                sys.stdout.buffer.write(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read().decode() or "{}")
                print(_format_api_error(data), file=sys.stderr)
            except Exception:
                print(exc.reason, file=sys.stderr)
            return 1
        return 0
    status, data = _request("GET", f"{base}.json")
    if status >= 400:
        print(_format_api_error(data), file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


def cmd_wasm(args: argparse.Namespace) -> int:
    status, data = _request("GET", f"{args.api}/v1/wasm/{args.wasm_hash}")
    if status >= 400:
        print(_format_api_error(data), file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


def cmd_wasm_contracts(args: argparse.Namespace) -> int:
    status, data = _request("GET", f"{args.api}/v1/wasm/{args.wasm_hash}/contracts")
    if status >= 400:
        print(_format_api_error(data), file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    params = []
    if args.network:
        params.append(f"network={args.network}")
    if args.status:
        params.append(f"status={args.status}")
    if args.contract_id:
        params.append(f"contract_id={args.contract_id}")
    if args.wasm_hash:
        params.append(f"wasm_hash={args.wasm_hash}")
    if args.limit:
        params.append(f"limit={args.limit}")
    query = f"?{'&'.join(params)}" if params else ""
    status, data = _request("GET", f"{args.api}/v1/verifications{query}")
    if status >= 400:
        print(_format_api_error(data), file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    status, data = _request("GET", f"{args.api}/v1/info")
    if status >= 400:
        print(_format_api_error(data), file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sourceproof", description="SourceProof verification CLI")
    p.add_argument("--api", default=DEFAULT_API, help=f"API base URL (default {DEFAULT_API})")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("verify", help="submit a source for verification")
    v.add_argument("--network", required=True, choices=["testnet", "mainnet", "futurenet"])
    v.add_argument("--contract-id", help="contract id (on-chain source_repo auto-resolve when no source)")
    v.add_argument("--wasm-hash")
    v.add_argument("--source", help="path to a .tar.gz source archive")
    v.add_argument("--source-repo", help="SEP-58 public repo URL")
    v.add_argument("--source-rev", help="SEP-58 commit / tag / ref")
    v.add_argument("--tarball-url", help="SEP-58 hosted tarball URL (https:// or ipfs://)")
    v.add_argument("--tarball-sha256", help="SEP-58 expected tarball sha256")
    v.add_argument("--bldopt", help="SEP-58 build options string")
    v.add_argument("--wait", action="store_true", help="poll until the result is ready")
    v.add_argument("--timeout", type=int, default=300)
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("status", help="get a verification by id")
    s.add_argument("verification_id")
    s.set_defaults(func=cmd_status)

    lk = sub.add_parser("lookup", help="query verification status by contract id")
    lk.add_argument("network", choices=["testnet", "mainnet", "futurenet"])
    lk.add_argument("contract_id")
    lk.set_defaults(func=cmd_lookup)

    w = sub.add_parser("wasm", help="query verification status by wasm hash")
    w.add_argument("wasm_hash")
    w.set_defaults(func=cmd_wasm)

    wc = sub.add_parser("wasm-contracts", help="list contracts sharing a wasm hash")
    wc.add_argument("wasm_hash")
    wc.set_defaults(func=cmd_wasm_contracts)

    b = sub.add_parser("badge", help="fetch embeddable verification badge")
    b.add_argument("network", choices=["testnet", "mainnet", "futurenet"])
    b.add_argument("contract_id")
    b.add_argument("--format", choices=["json", "svg"], default="json")
    b.set_defaults(func=cmd_badge)

    ls = sub.add_parser("list", help="list recent verifications")
    ls.add_argument("--network", choices=["testnet", "mainnet", "futurenet"])
    ls.add_argument("--status", choices=["pending", "verified", "mismatch", "failed"])
    ls.add_argument("--contract-id")
    ls.add_argument("--wasm-hash")
    ls.add_argument("--limit", type=int, default=50)
    ls.set_defaults(func=cmd_list)

    i = sub.add_parser("info", help="show API capabilities and limits")
    i.set_defaults(func=cmd_info)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify" and not (args.contract_id or args.wasm_hash):
        print("error: provide --contract-id or --wasm-hash", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
