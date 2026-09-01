"""Parse owner-only GitHub issue scan requests and render phone-friendly reports."""

import re
from collections.abc import Mapping
from math import isfinite
from typing import Any
from urllib.parse import urlparse

_EVM_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
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


def _positive_amount(value: str | None, field: str) -> float | None:
    if value is None:
        return None
    try:
        amount = float(value.replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a positive number.") from None
    if not isfinite(amount) or amount <= 0 or amount > 100_000:
        raise ValueError(f"{field} must be greater than 0 and no more than 100,000.")
    return round(amount, 2)


def _validated_contract(value: str | None, chain: str) -> str:
    contract = str(value or "").strip().strip("`").strip()
    if not contract or any(character.isspace() for character in contract):
        raise ValueError("A single token contract address is required.")
    is_evm = bool(_EVM_ADDRESS.fullmatch(contract))
    is_solana = bool(_SOLANA_ADDRESS.fullmatch(contract))
    if not is_evm and not is_solana:
        raise ValueError(
            "Contract must be a valid EVM 0x address or Solana mint address."
        )
    if chain == "solana" and not is_solana:
        raise ValueError("The Solana chain selection requires a Solana mint address.")
    if chain in {"robinhood", "base", "ethereum", "bsc"} and not is_evm:
        raise ValueError(f"The {chain} chain selection requires an EVM 0x address.")
    return contract


def parse_issue_scan_request(body: str) -> dict:
    """Parse the stable headings emitted by the GitHub issue form."""
    sections = _sections(body)
    chain = (_section_value(sections, "Chain") or "auto").strip().lower()
    if chain not in _SUPPORTED_CHAINS:
        raise ValueError(
            "Chain must be auto, solana, robinhood, base, ethereum, or bsc."
        )
    requested_chain = "unknown" if chain in {"auto", "unknown"} else chain
    contract = _validated_contract(
        _section_value(sections, "Contract address", "Token contract"),
        requested_chain,
    )
    paper_usd = _positive_amount(
        _section_value(sections, "Paper position size USD"),
        "Paper position size",
    )
    order_preview_usd = _positive_amount(
        _section_value(sections, "Manual review order size USD"),
        "Manual-review order size",
    )
    return {
        "contract_address": contract,
        "chain": requested_chain,
        "paper_usd": paper_usd,
        "order_preview_usd": order_preview_usd,
        "order_side": "buy",
    }


def validate_owner_event(event: Mapping[str, Any]) -> dict:
    """Fail closed unless the repository owner submitted a radar issue."""
    issue = event.get("issue") or {}
    repository = event.get("repository") or {}
    requester = str((issue.get("user") or {}).get("login") or "").strip()
    owner = str((repository.get("owner") or {}).get("login") or "").strip()
    title = str(issue.get("title") or "").strip()
    if not requester or not owner or requester.casefold() != owner.casefold():
        raise ValueError("Only the repository owner can submit a Narrative Radar scan.")
    if not title.upper().startswith("[RADAR SCAN]"):
        raise ValueError("Issue title must start with [RADAR SCAN].")
    return parse_issue_scan_request(str(issue.get("body") or ""))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _money(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "n/a"
    if abs(number) >= 1_000_000:
        return f"${number / 1_000_000:,.2f}M"
    if abs(number) >= 1_000:
        return f"${number / 1_000:,.1f}K"
    if abs(number) >= 0.01:
        return f"${number:,.2f}"
    return f"${number:,.8f}"


def _cell(value: Any) -> str:
    text = str(value if value is not None else "n/a")
    text = (
        text.replace("\n", " ")
        .replace("@", "@\u200b")
        .replace("`", "'")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    text = re.sub(r"([\\[\]])", r"\\\1", text)
    return text.replace("|", "\\|")


def _safe_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if any(character.isspace() or character in "()<>" for character in url):
        return None
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _gate_label(value: Any) -> str:
    return str(value or "not_evaluated").replace("_", " ").title()


def render_issue_error(message: str) -> str:
    return "\n".join(
        [
            "<!-- narrative-radar-report -->",
            "## Narrative Radar scan could not run",
            "",
            str(message).strip() or "The request was invalid.",
            "",
            "Edit the issue using the scan form and keep private keys or seed phrases out of GitHub.",
            "",
            "No transaction was created, signed, or submitted.",
        ]
    )


def render_issue_report(report: Mapping[str, Any]) -> str:
    """Render the live analysis as a concise GitHub/mobile report."""
    market = report.get("market") or {}
    score = report.get("score") or {}
    quality = report.get("narrative_quality") or {}
    risk = report.get("red_team") or {}
    gate = report.get("decision_gate") or {}
    preview = report.get("order_preview") or {}
    research = report.get("research") or {}
    onchain = report.get("onchain_activity") or {}
    security = report.get("token_security") or {}
    token_name = market.get("token_name") or "Unknown token"
    token_symbol = market.get("token_symbol") or "unknown"

    lines = [
        "<!-- narrative-radar-report -->",
        f"## Narrative Radar: {_cell(token_name)} ({_cell(token_symbol)})",
        "",
        f"**Result: {_gate_label(gate.get('status'))}.** This is a research result, not an automatic buy signal.",
        "",
        f"Research source: `{_cell(research.get('provider') or 'not configured')}`",
        "",
        "| Check | Result |",
        "|---|---:|",
        f"| Chain / DEX | {_cell(market.get('chain'))} / {_cell(market.get('dex'))} |",
        f"| Market cap | {_money(market.get('market_cap'))} |",
        f"| Liquidity | {_money(market.get('liquidity_usd'))} |",
        f"| 24h volume | {_money(market.get('volume_24h'))} |",
        f"| Radar score | {_cell(score.get('radar_score'))}/100 ({_cell(score.get('rating'))}) |",
        f"| Narrative evidence | {_cell(quality.get('quality_score'))}/100 ({_cell(quality.get('classification'))}) |",
        f"| Independent domains | {_cell(quality.get('independent_domain_count'))} |",
        f"| Risk | {_cell(risk.get('risk_level'))} |",
        f"| Token security | {_cell(security.get('status'))} / {_cell(security.get('risk_level'))} |",
        f"| Security blockers | {_cell(len(security.get('hard_blockers') or []))} |",
        f"| Bundler analysis | {_cell((security.get('bundler_analysis') or {}).get('status'))} |",
        f"| Decision gate | {_cell(gate.get('status'))} |",
    ]

    if onchain.get("status") not in {None, "not_requested", "unsupported_chain"}:
        lines.extend(
            [
                f"| On-chain coverage | {_cell(onchain.get('status'))} |",
                f"| Holder/activity proxy | {_cell(onchain.get('holder_count'))} holders / {_cell(onchain.get('unique_active_wallets_24h'))} active owners |",
            ]
        )

    dex_url = _safe_url(market.get("dex_url"))
    if dex_url:
        lines.extend(["", f"[Open live DEX chart]({dex_url})"])

    requirement_map = {item.get("name"): item for item in gate.get("requirements", [])}
    failed = list(gate.get("failed_requirements") or [])
    lines.extend(["", "### What still needs attention"])
    if failed:
        for name in failed:
            requirement = requirement_map.get(name) or {}
            lines.append(
                f"- **{_cell(str(name).replace('_', ' ').title())}:** "
                f"{_cell(requirement.get('detail') or 'Review required.')}"
            )
    else:
        lines.append("- All configured research checks passed for manual review.")

    flags = list(risk.get("flags") or [])
    if flags:
        lines.extend(["", "### Red-team flags"])
        for flag in flags[:8]:
            lines.append(
                f"- **{_cell(str(flag.get('severity') or 'review').upper())}:** "
                f"{_cell(flag.get('message') or 'Review required.')}"
            )

    security_flags = list(security.get("flags") or [])
    if security_flags:
        lines.extend(["", "### Scam and rug-risk screen"])
        for flag in security_flags[:10]:
            lines.append(
                f"- **{_cell(str(flag.get('severity') or 'review').upper())}:** "
                f"{_cell(flag.get('message') or 'Review required.')}"
            )
    holder_distribution = security.get("holder_distribution") or {}
    lp_distribution = security.get("lp_distribution") or {}
    bundler = security.get("bundler_analysis") or {}
    lines.extend(
        [
            "",
            "### Distribution and bundler coverage",
            (
                "- Largest shown unlocked/unexcluded holder: `"
                f"{_cell(holder_distribution.get('largest_unlocked_unexcluded_share_pct'))}%`"
            ),
            (
                "- Shown unlocked/unexcluded top-holder share: `"
                f"{_cell(holder_distribution.get('top_unlocked_unexcluded_share_pct'))}%`"
            ),
            (
                "- Shown unlocked/unexcluded LP share: `"
                f"{_cell(lp_distribution.get('top_unlocked_unexcluded_share_pct'))}%`"
            ),
            (
                "- Bundler/linked-wallet status: `"
                f"{_cell(bundler.get('status'))}` — "
                f"{_cell(bundler.get('note'))}"
            ),
        ]
    )
    if bundler.get("provider"):
        lines.extend(
            [
                (
                    "- Earliest token transactions checked: `"
                    f"{_cell(bundler.get('launch_transactions_scanned'))}` / "
                    f"limit `{_cell(bundler.get('launch_transaction_limit'))}`"
                ),
                (
                    "- First-acquisition owners checked: `"
                    f"{_cell(bundler.get('first_acquisition_owner_count'))}`"
                ),
                (
                    "- Pre-acquisition funding histories checked: `"
                    f"{_cell(bundler.get('funding_wallets_checked'))}` / "
                    f"`{_cell(bundler.get('funding_wallets_requested'))}`"
                ),
                (
                    "- Observable linked clusters / blockers: `"
                    f"{_cell(bundler.get('linked_cluster_count'))}` / "
                    f"`{_cell(bundler.get('blocking_cluster_count'))}`"
                ),
                (
                    "- Largest observed linked-cluster supply share: `"
                    f"{_cell(bundler.get('largest_cluster_supply_share_pct'))}%`"
                ),
            ]
        )
        for cluster in list(bundler.get("clusters") or [])[:5]:
            review_label = "BLOCKER" if cluster.get("hard_blocker") else "review"
            lines.append(
                f"  - **{review_label}:** {_cell(cluster.get('type'))} — "
                f"{_cell(cluster.get('owner_count'))} wallet(s), "
                f"{_cell(cluster.get('concentration_share_pct'))}% observed supply"
            )

    lines.extend(["", "### Paper-only market preview"])
    if preview:
        lines.extend(
            [
                f"- Status: **{_cell(preview.get('status'))}**",
                f"- Review amount: **{_money(preview.get('notional_usd'))}**",
                f"- Estimated token amount: `{_cell(preview.get('estimated_token_amount'))}`",
                f"- Snapshot age: `{_cell(preview.get('snapshot_age_seconds'))}` seconds",
                f"- Manual approval required: `{_cell(preview.get('manual_approval_required'))}`",
                f"- Execution enabled: `{_cell(preview.get('execution_enabled'))}`",
            ]
        )
        for check in preview.get("checks", []):
            if check.get("status") != "pass":
                lines.append(
                    f"- {_cell(check.get('name'))}: {_cell(check.get('detail'))}"
                )
    else:
        lines.append("- No order preview was requested.")

    if gate.get("status") == "blocked":
        lines.append("- This preview does not override the blocked decision gate.")

    evidence = list((report.get("narrative") or {}).get("verified_evidence") or [])
    evidence.extend((report.get("narrative") or {}).get("uncertain_evidence") or [])
    linked_evidence = []
    seen_urls = set()
    for item in evidence:
        url = _safe_url(item.get("source_url"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        linked_evidence.append((item, url))
    if linked_evidence:
        lines.extend(["", "### Evidence leads"])
        for item, url in linked_evidence[:5]:
            label = item.get("claim") or item.get("source_type") or "Source"
            lines.append(f"- [{_cell(label)}]({url})")

    if research.get("error"):
        lines.extend(["", f"Research note: {_cell(research.get('error'))}"])
    for warning in list(research.get("provider_warnings") or [])[:5]:
        lines.append(f"- Research source warning: {_cell(warning)}")

    lines.extend(
        [
            "",
            "---",
            "No transaction was created, signed, or submitted. Market conditions can change before you open Axiom.",
        ]
    )
    return "\n".join(lines)
