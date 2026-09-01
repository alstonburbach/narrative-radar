"""Owner-only phone discovery requests and mobile GitHub reports."""

import re
from collections.abc import Mapping
from math import isfinite
from typing import Any
from urllib.parse import urlparse

_SUPPORTED_CHAINS = {
    "auto",
    "unknown",
    "solana",
    "robinhood",
    "base",
    "ethereum",
    "bsc",
}
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
        raise ValueError(
            "Chain must be auto, solana, robinhood, base, ethereum, or bsc."
        )
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
    options = list(report.get("narrative_options") or [])
    provider = report.get("research_provider") or "unknown"
    requested_provider = report.get("research_provider_requested") or provider
    deep_research_active = bool(report.get("deep_research_active"))
    lines = [
        "<!-- narrative-radar-discovery-report -->",
        f"## Narrative Radar discovery: {_cell(report.get('topic'))}",
        "",
        "**Research leads only—not automatic buy signals.**",
        "",
        f"Observed: `{_cell(report.get('started_at'))}`",
        "",
        f"Research source: `{_cell(provider)}`",
        f"Requested mode: `{_cell(requested_provider)}`; deep web scan active: `{_cell(deep_research_active)}`",
        "",
        "| Check | Result |",
        "|---|---:|",
        f"| Run status | {_cell(report.get('status'))} |",
        f"| Evidence quality | {_cell(quality.get('quality_score'))}/100 ({_cell(quality.get('classification'))}) |",
        f"| Independent domains | {_cell(report.get('independent_domain_count'))} |",
        f"| Fresh evidence | {_cell(freshness.get('recent_count'))} |",
        f"| Research leads | {_cell(report.get('lead_count'))} |",
        f"| Cross-source candidates | {len(candidates)} |",
        f"| Researched watch options | {len(options)} |",
        f"| Scan durability | {_cell(history.get('state'))} across {_cell(history.get('run_count'))} run(s) |",
    ]
    if provider == "public_rss":
        lines.extend(
            [
                "",
                "The free fallback checks recent public crypto-news and official ecosystem feeds. Headlines remain unverified until their underlying claims are checked.",
            ]
        )

    if options:
        lines.extend(["", "### Automatic narrative watch options"])
        for option in options[:5]:
            status = str(option.get("status") or "insufficient_evidence").replace(
                "_", " "
            )
            lines.extend(
                [
                    f"{_cell(option.get('rank'))}. **{_cell(option.get('label'))}** — `{_cell(status)}`",
                    (
                        "   - Research basis: "
                        f"{_cell(len(option.get('independent_domains') or []))} domains, "
                        f"{_cell(len(option.get('positive_lenses') or []))} positive lenses, "
                        f"{_cell(option.get('recent_evidence_count'))} recent dated source(s)"
                    ),
                    (
                        "   - Scores: cross-source "
                        f"`{_cell(option.get('signal_score'))}/100`; option evidence "
                        f"`{_cell(option.get('evidence_quality_score'))}/100`"
                    ),
                    "   - Buy review: **blocked until an exact token contract passes security, liquidity, holder/LP, bundler, and counterevidence checks.**",
                ]
            )
            for caution in list(option.get("cautions") or [])[:3]:
                lines.append(f"   - Caution: {_cell(caution)}")
            links = []
            for value in option.get("evidence_urls") or []:
                url = _safe_url(value)
                if not url:
                    continue
                domain = (urlparse(url).hostname or "source").removeprefix("www.")
                links.append(f"[{_cell(domain)}]({url})")
            if links:
                lines.append(f"   - Evidence: {' · '.join(links[:5])}")
        lines.extend(
            [
                "",
                "**Next path:** identify the exact public contract → run **Scan a token** → resolve every contract-security and bundler warning → paper-track before considering real funds.",
            ]
        )

    lines.extend(["", "### Candidate themes"])
    if not candidates:
        lines.append(
            "- No supported theme repeated across at least two independent domains."
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
    options = list(report.get("narrative_options") or [])
    if report.get("status") not in {"complete", "partial"}:
        return {"notify": False, "reason": "discovery_failed"}
    if not candidates:
        return {"notify": False, "reason": "no_cross_source_candidates"}
    if options and not any(
        option.get("status") in {"research_next", "watch_for_confirmation"}
        for option in options
    ):
        return {"notify": False, "reason": "no_researched_watch_options"}
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
