"""Embeddable verification badge assets for explorers and READMEs."""

from __future__ import annotations

from typing import Any


def badge_json(
    *,
    network: str,
    contract_id: str,
    consensus: str,
    freshness: str | None,
    verifier_count: int,
) -> dict[str, Any]:
    verified = consensus == "verified" and freshness != "superseded"
    label = "Source verified" if verified else consensus.replace("_", " ").title()
    if freshness == "superseded":
        label = "Verification superseded"
    return {
        "network": network,
        "contract_id": contract_id,
        "consensus": consensus,
        "freshness": freshness,
        "verified": verified,
        "label": label,
        "verifier_count": verifier_count,
    }


def badge_svg(
    *,
    label: str,
    consensus: str,
    verified: bool,
) -> str:
    fill = "#16a34a" if verified else "#ca8a04" if consensus == "divergent" else "#6b7280"
    if consensus == "mismatch":
        fill = "#dc2626"
    text = label.replace("&", "&amp;").replace("<", "&lt;")
    width = max(140, 10 * len(label) + 24)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="{text}">
  <rect width="{width}" height="20" rx="3" fill="{fill}"/>
  <text x="8" y="14" fill="#fff" font-family="system-ui,sans-serif" font-size="11">{text}</text>
</svg>"""
