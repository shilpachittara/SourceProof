#!/usr/bin/env python3
"""Render the SourceProof detailed code-flow architecture diagram (black & white).

Reproducible asset for docs/Contract-Source-Verification-Service.md.
Monochrome: white background, black boxes, black ink. Shows the real end-to-end
flow as implemented in api/app/* (write/verify path and read/lookup path).

Run:  python scripts/gen_architecture.py [output.jpg]
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl-"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Polygon, Rectangle

BLACK = "#000000"
WHITE = "#ffffff"


def main(out_path: str) -> None:
    fig, ax = plt.subplots(figsize=(18.5, 21.5), dpi=175)
    ax.set_xlim(0, 16.8)
    ax.set_ylim(0, 20.2)
    ax.axis("off")

    # ---- helpers --------------------------------------------------------
    def node(x0, top, w, h, title, lines=None, lw=1.4, title_size=11.0, body_size=9.2):
        ax.add_patch(
            Rectangle((x0, top - h), w, h, facecolor=WHITE, edgecolor=BLACK, linewidth=lw, zorder=2)
        )
        ax.text(
            x0 + 0.16, top - 0.27, title, ha="left", va="top",
            fontsize=title_size, fontweight="bold", color=BLACK, zorder=3,
        )
        if lines:
            ax.text(
                x0 + 0.2, top - 0.62, "\n".join(lines), ha="left", va="top",
                fontsize=body_size, family="monospace", color=BLACK, zorder=3, linespacing=1.5,
            )
        return {"cx": x0 + w / 2, "top": top, "bottom": top - h, "x0": x0, "w": w}

    def diamond(cx, cy, w, h, text):
        pts = [(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)]
        ax.add_patch(Polygon(pts, closed=True, facecolor=WHITE, edgecolor=BLACK, linewidth=1.5, zorder=2))
        ax.text(cx, cy, text, ha="center", va="center", fontsize=10.0, fontweight="bold", color=BLACK, zorder=3)
        return {"cx": cx, "top": cy + h / 2, "bottom": cy - h / 2}

    def arrow(a, b, dashed=False, label=None, lw=1.2):
        p1 = (a["cx"], a["bottom"])
        p2 = (b["cx"], b["top"])
        ax.add_patch(
            FancyArrowPatch(
                p1, p2, arrowstyle="-|>", mutation_scale=16, color=BLACK,
                linewidth=lw + 0.4, linestyle="--" if dashed else "-", zorder=1,
            )
        )
        if label:
            ax.text(
                (p1[0] + p2[0]) / 2 + 0.12, (p1[1] + p2[1]) / 2, label, ha="left", va="center",
                fontsize=8.6, fontstyle="italic", color=BLACK,
                bbox=dict(boxstyle="square,pad=0.1", fc=WHITE, ec="none"), zorder=4,
            )

    # ---- title ----------------------------------------------------------
    ax.text(0.3, 19.85, "SourceProof — Detailed Verification Flow (as implemented in api/app/*)",
            fontsize=18.0, fontweight="bold", color=BLACK)
    ax.text(0.3, 19.42,
            "Tags [STORE] [DB] [IMG] [CHAIN] reference the shared data stores (bottom-right). "
            "Solid = control flow; dashed = store/chain access.",
            fontsize=11.0, color=BLACK)

    # ===================== WRITE / VERIFY PATH (left) ====================
    LX, LW = 0.6, 7.6
    ax.text(LX, 19.0, "WRITE PATH  —  POST /v1/verify  (rebuild → compare → persist)",
            fontsize=13.0, fontweight="bold", color=BLACK)

    w1 = node(LX, 18.55, LW, 1.0,
              "CLIENT  —  developer · sourceproof CLI · demo UI",
              ["POST /v1/verify  (multipart/form-data):",
               "network · contract_id|wasm_hash · source|github_url|tarball_url|tarball_sha256 · bldopt"])
    w2 = node(LX, 17.1, LW, 1.2,
              "submit_verification()                              [main.py]",
              ["_enforce_rate_limit() -> RateLimiter.allow(ip)   => 429 + Retry-After  [ratelimit.py]",
               "validate network in rpc_urls · require contract_id OR wasm_hash"])
    d3 = diamond(LX + LW / 2, 15.0, 3.2, 1.05, "source mode?")
    w4 = node(LX, 13.95, LW, 1.62,
              "SEP-58 source resolver  ->  one normalized tarball   [sources.py]",
              ["github_url/source_repo -> fetch_from_github()   origin=github",
               "tarball_url -> fetch_hosted_tarball()  (HTTPS/ipfs:// + verify sha256)  origin=url/ipfs",
               "source file -> UploadFile.read()   origin=upload",
               "tarball_sha256 -> fetch_content_addressed()   origin=content-addressed"])
    w5 = node(LX, 12.0, LW, 1.0,
              "validate_and_store_tarball()        [storage.py]      -> [STORE]",
              ["safe paths · size cap · content_hash = sha256(bytes) · write {hash}.tar.gz"])
    w6 = node(LX, 10.55, LW, 1.15,
              "fetch_wasm_hash(network, contract_id, wasm_hash)   [rpc.py]   -> [CHAIN]",
              ["wasm_hash given? use it : RPC getContractWasm  (fallback: `stellar contract fetch`)",
               "=> expected_hash + onchain_wasm bytes"])
    w7 = node(LX, 9.0, LW, 1.2,
              "parse_wasm_metadata(onchain_wasm)     [wasm_meta.py]    -> [IMG]",
              ["read rsver · rssdkver · bldimg  ·  declared_build_image()",
               "chosen_image = bldimg if allowlist.is_allowed() else settings.builder_image",
               "declared-but-not-allowlisted -> onchain_meta.bldimg_allowlisted = false"])
    w8 = node(LX, 7.35, LW, 1.2,
              "INSERT Verification(status=pending)    [database.py]    -> [DB]",
              ["trust_level=sep58_rebuild · tarball_content_hash · builder_image=chosen",
               "onchain_meta · verifier_instance_id",
               "=> HTTP 202 { verification_id, status=pending, poll_url }"])
    w9 = node(LX, 5.7, LW, 0.95,
              "background_tasks -> process_verification()    [worker.py]",
              ["extract_tarball(stored_path -> source_dir)        -> [STORE]"])
    w10 = node(LX, 4.3, LW, 1.3,
               "build_contract(source_dir, output_dir, image)    [builder.py]   -> [IMG]",
               ["docker run --network none  <pinned builder image>",
                "`stellar contract build` -> .wasm   (BuildError -> status=FAILED)",
                "metadata: rustc · stellar-cli · soroban-sdk · image digest"])
    d11 = diamond(LX + LW / 2, 2.35, 4.6, 1.05, "built_hash == expected_hash ?")
    w12 = node(LX, 1.25, LW, 1.15,
               "UPDATE Verification    [database.py]    -> [DB]",
               ["VERIFIED (match)  ·  MISMATCH (+ _explain_mismatch)  ·  FAILED",
                "built_wasm_hash · build_metadata · verified_at · rmtree(workdir)"])

    for a, b in [(w1, w2), (w2, d3), (d3, w4), (w4, w5), (w5, w6), (w6, w7),
                 (w7, w8), (w8, w9), (w9, w10), (w10, d11), (d11, w12)]:
        arrow(a, b)

    # ===================== READ / LOOKUP PATH (right top) ================
    RX, RW = 8.9, 7.3
    ax.text(RX, 19.0, "READ PATH  —  lookup (verify once, read many)",
            fontsize=13.0, fontweight="bold", color=BLACK)

    r1 = node(RX, 18.55, RW, 0.95,
              "CONSUMERS  —  explorers · wallets · Stellar Lab · CLI", [])
    r2 = node(RX, 17.2, RW, 1.45,
              "READ endpoints                                   [main.py]",
              ["GET /v1/{network}/contracts/{id}",
               "GET /v1/wasm/{hash}",
               "GET /v1/verifications[/{id}]",
               "GET /v1/source/{hash}[/files|/file]"])
    r3 = node(RX, 15.35, RW, 0.85,
              "query Verification rows        [database.py]   -> [DB]",
              ["filter by (network, contract_id) or wasm_hash"])
    r4 = node(RX, 14.1, RW, 1.05,
              "fetch_wasm_bytes() live        [rpc.py]   -> [CHAIN]",
              ["current_wasm_hash -> freshness = current | superseded"])
    r5 = node(RX, 12.65, RW, 1.2,
              "aggregate_verifiers(records, current)    [database.py]",
              ["latest result per verifier_instance_id -> consensus:",
               "verified | divergent | mismatch | pending | mixed",
               "per-verifier signal  [v] Verified by X  /  [!] Mismatching by Y"])
    r6 = node(RX, 11.05, RW, 1.45,
              "serialize_verification()       [database.py]",
              ["sep58 block: mode · channel · bldimg · builder_image_used ·",
               "source_repo · source_rev · tarball_url · tarball_sha256 · source_artifact_url",
               "build_image = evaluate_build_image()   [allowlist.py]  -> [IMG]",
               "freshness (current/superseded)"])
    r7 = node(RX, 9.2, RW, 1.0,
              "JSON response",
              ["{ consensus, verifier_count, verifiers[], verifications[] }"])
    r8 = node(RX, 7.75, RW, 1.0,
              "source browse / download       [storage.py]   -> [STORE]",
              ["list_tarball_entries · read_source_file · read_source_tarball"])

    for a, b in [(r1, r2), (r2, r3), (r3, r4), (r4, r5), (r5, r6), (r6, r7), (r7, r8)]:
        arrow(a, b)

    # ===================== SHARED DATA STORES (right bottom) =============
    ax.text(RX, 6.35, "SHARED RESOURCES / DATA STORES", fontsize=13.0, fontweight="bold", color=BLACK)
    sw, sh, sgap = 3.5, 1.25, 0.3
    sx2 = RX + sw + sgap
    s_store = node(RX, 5.9, sw, sh,
                   "[STORE] source",
                   ["content-addressed", "{sha256}.tar.gz", "tamper-evident · deduped"], lw=2.3, title_size=10.5)
    s_db = node(sx2, 5.9, sw, sh,
                "[DB] metadata",
                ["Postgres / PGlite", "append-only Verification rows", "status · trust · sep58 · meta"], lw=2.3, title_size=10.5)
    s_img = node(RX, 4.35, sw, sh,
                 "[IMG] builder + allowlist",
                 ["pinned Docker image (digest)", "allowlist.py: is_allowed,", "revoked / deprecated_after"], lw=2.3, title_size=10.5)
    s_chain = node(sx2, 4.35, sw, sh,
                   "[CHAIN] Stellar RPC / ledger",
                   ["getContractWasm (CLI fallback)", "contractmetav0: rsver,", "rssdkver, bldimg"], lw=2.3, title_size=10.5)

    # footer (placed under the shared stores on the right, clear of the write column)
    ax.text(RX, 2.82,
            "Proof:  build(submitted_source, pinned_env)  ==  wasm_deployed_at(contract_id, network).",
            fontsize=10.4, fontweight="bold", color=BLACK)
    ax.text(RX, 2.49,
            "Reproducible via scripts/gen_architecture.py.",
            fontsize=9.4, fontstyle="italic", color=BLACK)

    # ---- compact legend (bottom-right) ----------------------------------
    lx, ltop, lw_, lh = RX, 2.25, 7.3, 1.95
    ax.add_patch(Rectangle((lx, ltop - lh), lw_, lh, facecolor=WHITE, edgecolor=BLACK, linewidth=1.2, zorder=2))
    ax.text(lx + 0.16, ltop - 0.26, "LEGEND", ha="left", va="top", fontsize=11.0, fontweight="bold", color=BLACK)

    def _icon_label(icx, iy, kind, label):
        if kind == "proc":
            ax.add_patch(Rectangle((icx, iy - 0.13), 0.5, 0.26, facecolor=WHITE, edgecolor=BLACK, linewidth=1.3, zorder=3))
        elif kind == "store":
            ax.add_patch(Rectangle((icx, iy - 0.13), 0.5, 0.26, facecolor=WHITE, edgecolor=BLACK, linewidth=2.3, zorder=3))
        elif kind == "dec":
            c = icx + 0.25
            ax.add_patch(Polygon([(c, iy + 0.16), (c + 0.3, iy), (c, iy - 0.16), (c - 0.3, iy)],
                                 closed=True, facecolor=WHITE, edgecolor=BLACK, linewidth=1.3, zorder=3))
        elif kind in ("solid", "dashed"):
            ax.add_patch(FancyArrowPatch((icx, iy), (icx + 0.5, iy), arrowstyle="-|>", mutation_scale=11,
                                         color=BLACK, linewidth=1.3,
                                         linestyle="--" if kind == "dashed" else "-", zorder=3))
        ax.text(icx + 0.68, iy, label, ha="left", va="center", fontsize=9.4, color=BLACK, zorder=3)

    colA, colB = lx + 0.25, lx + 3.95
    _icon_label(colA, ltop - 0.72, "proc", "process / function call")
    _icon_label(colA, ltop - 1.18, "dec", "decision / branch")
    _icon_label(colA, ltop - 1.64, "store", "[TAG] shared store / external")
    _icon_label(colB, ltop - 0.72, "solid", "control flow")
    _icon_label(colB, ltop - 1.18, "dashed", "store / chain access")
    ax.text(colB, ltop - 1.64, "code refs:  [main.py] [worker.py] ...", ha="left", va="center",
            fontsize=9.0, fontstyle="italic", color=BLACK, zorder=3)

    fig.savefig(out_path, format="jpg", bbox_inches="tight", pad_inches=0.25, facecolor=WHITE)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "architecture.jpg"
    main(out)
