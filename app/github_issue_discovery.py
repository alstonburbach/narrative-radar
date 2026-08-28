"""Owner-only phone discovery requests and mobile GitHub reports."""

import re
from collections.abc import Mapping
from math import isfinite
from typing import Any
from urllib.parse import urlparse

_SUPPORTED_CHAINS = {"auto", "unknown", "solana", "base", "ethereum", "bsc"}
_NO_RESPONSE_VALUES = {"", "_no response_", "no response", "none", "n/a"}


def _heading_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _sections(body: str) -> dict[str, str]:
    parts = re.split(r"(?m)^###\s+(.+?)\s*$", str(body or ""))
    sections = {}
    for index in range(1, len(parts), 2):
        heading = _heading_key(parts[index])
        value = parts[index + 1].strip() if index + 1 < len(parts) else ""
        sections[heading] = value
    return sections


def _section_value(sections: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = str(sections.get(_heading_key(name), "")).strip()
        if value.lower() not in _NO_RESPONSE_VALUES:
            return value
    return None


def parse_discovery_request(body: str) -> dict:
    """Parse and bound the stable headings from the discovery issue form."""
    sections = _sections(body)
    topic = re.sub(
        r"\s+",
        " ",
        str(_section_value(sections, "Topic or theme") or "crypto narratives"),
    ).strip()
    if len(topic) < 3 or len(topic) > 120:
        raise ValueError("Topic or theme must contain 3 to 120 characters.")
    if any(ord(character) < 32 for character in topic):
        raise ValueError("Topic or theme contains unsupported control characters.")

    chain = str(_section_value(sections, "Chain") or "auto").strip().lower()
    if chain not in _SUPPORTED_CHAINS:
        raise ValueError("Chain must be auto, solana, base, ethereum, or bsc.")
    normalized_chain = "unknown" if chain in {"auto", "unknown"} else chain

    limit_text = str(_section_value(sections, "Results per research lens") or "5")
    try:
        limit_number = float(limit_text.strip())
    except ValueError:
        raise ValueError("Results per research lens must be a whole number.") from None
    if not isfinite(limit_number) or not limit_number.is_integer():
        raise ValueError("Results per research lens must be a whole number.")
    limit = int(limit_number)
    if not 1 <= limit <= 10:
        raise ValueError("Results per research lens must be between 1 and 10.")

    return {"topic": topic, "chain": normalized_chain, "limit": limit}


def validate_owner_discovery_event(event: Mapping[str, Any]) -> dict:
    """Fail closed unless the repository owner submitted a discovery issue."""
    issue = event.get("issue") or {}
    repository = event.get("repository") or {}
    requester = str((issue.get("user") or {}).get("login") or "").strip()
    owner = str((repository.get("owner") or {}).get("login") or "").strip()
    title = str(issue.get("title") or "").strip()
    if not requester or not owner or requester.casefold() != owner.casefold():
        raise ValueError("Only the repository owner can submit discovery research.")
    if not title.upper().startswith("[RADAR DISCOVERY]"):
        raise ValueError("Issue title must start with [RADAR DISCOVERY].")
    return parse_discovery_request(str(issue.get("body") or ""))


def _cell(value: Any, limit: int = 240) -> str:
    text = str(value if value is not None else "n/a")
    text = (
        text.replace("\n", " ")
        .replace("@", "@\u200b")
        .replace("`", "'")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    text = re.sub(r"([\\[\]])", r"\\\1", text)
    return text.replace("|", "\\|")[:limit]


def _safe_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if any(character.isspace() or character in "()<>" for character in url):
        return None
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _lead_label(item: Mapping[str, Any]) -> str:
    claim = str(item.get("claim") or "Research lead")
    claim = re.sub(r"^Public search result references .*?:\s*", "", claim)
    return _cell(claim, limit=160)


def render_discovery_error(message: str) -> str:
    return "\n".join(
        [
            "<!-- narrative-radar-discovery-report -->",
            "## Narrative Radar discovery could not run",
            "",
            str(message).strip() or "The request was invalid.",
            "",
            "Edit the issue using the discovery form. No trade signal or order was created.",
        ]
    )


def render_discovery_report(report: Mapping[str, Any]) -> str:
    """Render discovery evidence and candidates for a phone-sized GitHub view."""
    quality = report.get("quality") or {}
    freshness = quality.get("freshness") or {}
    history = report.get("discovery_history") or {}
    candidates = list(report.get("candidate_signals") or [])
    provider = report.get("research_provider") or "unknown"
    lines = [
        "<!-- narrative-radar-discovery-report -->",
        f"## Narrative Radar discovery: {_cell(report.get('topic'))}",
        "",
        "**Research leads only—not automatic buy signals.**",
        "",
        f"Research source: `{_cell(provider)}`",
        "",
        "| Check | Result |",
        "|---|---:|",
        f"| Run status | {_cell(report.get('status'))} |",
        f"| Evidence quality | {_cell(quality.get('quality_score'))}/100 ({_cell(quality.get('classification'))}) |",
        f"| Independent domains | {_cell(report.get('independent_domain_count'))} |",
        f"| Fresh evidence | {_cell(freshness.get('recent_count'))} |",
        f"| Research leads | {_cell(report.get('lead_count'))} |",
        f"| Cross-source candidates | {len(candidates)} |",
        f"| Scan durability | {_cell(history.get('state'))} across {_cell(history.get('run_count'))} run(s) |",
    ]
    if provider == "public_rss":
        lines.extend(
            [
                "",
                "The free fallback checks recent public crypto-news and official ecosystem feeds. Headlines remain unverified until their underlying claims are checked.",
            ]
        )

    lines.extend(["", "### Candidate themes"])
    if not candidates:
        lines.append(
            "- No term repeated across at least two independent domains and two positive research lenses."
        )
    for index, candidate in enumerate(candidates[:8], start=1):
        domains = list(candidate.get("independent_domains") or [])
        lenses = list(candidate.get("positive_lenses") or candidate.get("lenses") or [])
        lines.extend(
            [
                f"{index}. **{_cell(candidate.get('label'))}** — classification score `{_cell(candidate.get('signal_score'))}/100`",
                f"   - Domains: {_cell(', '.join(domains))}",
                f"   - Positive lenses: {_cell(', '.join(lenses))}",
            ]
        )
        links = []
        for value in candidate.get("evidence_urls") or []:
            url = _safe_url(value)
            if not url:
                continue
            domain = (urlparse(url).hostname or "source").removeprefix("www.")
            links.append(f"[{_cell(domain)}]({url})")
        if links:
            lines.append(f"   - Evidence: {' · '.join(links[:5])}")

    evidence = []
    seen_urls = set()
    for item in report.get("evidence") or []:
        url = _safe_url(item.get("source_url"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        evidence.append((item, url))
    if evidence:
        lines.extend(["", "### Recent evidence leads"])
        for item, url in evidence[:8]:
            lines.append(
                f"- [{_lead_label(item)}]({url}) — `{_cell(item.get('research_lens'))}`"
            )

    warnings = list(quality.get("warnings") or [])
    warnings.extend(report.get("provider_warnings") or [])
    if warnings:
        lines.extend(["", "### Warnings"])
        lines.extend(f"- {_cell(warning)}" for warning in warnings[:8])

    lines.extend(
        [
            "",
            "---",
            "Discovery identifies leads to investigate. It does not verify a token contract, predict returns, or place an order.",
        ]
    )
    return "\n".join(lines)


def discovery_notification_state(report: Mapping[str, Any]) -> dict:
    """Notify only for fresh cross-source candidates or material strengthening."""
    candidates = list(report.get("candidate_signals") or [])
    freshness = (report.get("quality") or {}).get("freshness") or {}
    history = report.get("discovery_history") or {}
    if report.get("status") not in {"complete", "partial"}:
        return {"notify": False, "reason": "discovery_failed"}
    if not candidates:
        return {"notify": False, "reason": "no_cross_source_candidates"}
    if not freshness.get("recent_count"):
        return {"notify": False, "reason": "no_recent_evidence"}
    if int(history.get("run_count") or 0) <= 1:
        return {"notify": True, "reason": "first_cross_source_candidates"}
    if history.get("new_since_previous"):
        return {
            "notify": True,
            "reason": "new_candidates",
            "signals": list(history["new_since_previous"]),
        }
    quality_change = history.get("quality_score_since_previous") or {}
    domain_change = history.get("independent_domain_count_since_previous") or {}
    strengthened_since_previous = (
        quality_change.get("available") and (quality_change.get("delta") or 0) >= 10
    ) or (domain_change.get("available") and (domain_change.get("delta") or 0) > 0)
    if strengthened_since_previous and history.get("persisted_since_previous"):
        return {
            "notify": True,
            "reason": "strengthening_candidates",
            "signals": list(history["persisted_since_previous"]),
        }
    return {"notify": False, "reason": "no_material_change"}
