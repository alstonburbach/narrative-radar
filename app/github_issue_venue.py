"""Phone-friendly rendering for Pump.fun and Robinhood Chain launch watches."""

from __future__ import annotations

from collections import Counter
from math import isfinite
import re
from typing import Any, Mapping
from urllib.parse import urlparse


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


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


def _cell(value: Any, limit: int = 300) -> str:
    text = str(value if value is not None else "n/a")
    text = (
        text.replace("\n", " ")
        .replace("@", "@\u200b")
        .replace("`", "'")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
    )
    return re.sub(r"([\\[\\]])", r"\\\1", text)[:limit]


def _safe_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if any(character.isspace() or character in "<>" for character in url):
        return None
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _venue_label(value: Any) -> str:
    return {
        "pump_fun": "Pump.fun",
        "robinhood_chain": "Robinhood Chain",
    }.get(str(value), str(value or "Unknown venue").replace("_", " ").title())


def _signal_label(value: Any) -> str:
    return {
        "screened_research": "SCREENED RESEARCH",
        "research_now": "RESEARCH NOW — LINK CHECK INCOMPLETE",
        "queued_security": "QUEUED FOR SECURITY",
        "market_watch": "WATCHING MARKET",
        "blocked_market_risk": "BLOCKED: MARKET RISK",
        "blocked_security": "BLOCKED: TOKEN SECURITY",
        "blocked_linked_wallets": "BLOCKED: LINKED WALLETS",
    }.get(str(value), str(value or "unknown").replace("_", " ").upper())


def _candidate_lines(candidate: Mapping[str, Any], index: int) -> list[str]:
    name = candidate.get("token_name") or "Unknown token"
    symbol = candidate.get("token_symbol") or "unknown"
    contract = _cell(candidate.get("contract_address"), 80)
    security = candidate.get("token_security") or {}
    bundler = candidate.get("bundler_analysis") or {}
    market_screen = candidate.get("market_screen") or {}
    buys = int(_number(candidate.get("buys_1h")) or 0)
    sells = int(_number(candidate.get("sells_1h")) or 0)
    age = _number(candidate.get("pair_age_minutes"))
    age_text = "n/a" if age is None else (f"{age / 60:.1f}h" if age >= 60 else f"{age:.0f}m")
    coverage = bundler.get("coverage") or {}
    linked_clusters = int(_number(bundler.get("linked_cluster_count")) or 0)
    blocking_clusters = int(
        _number(bundler.get("blocking_cluster_count"))
        or len(bundler.get("hard_blockers") or [])
    )
    largest_share = _number(bundler.get("largest_cluster_supply_share_pct"))
    largest_share_text = "n/a" if largest_share is None else f"{largest_share:.4g}%"
    block_start = bundler.get("launch_block_start")
    block_end = bundler.get("launch_block_end")
    scope = str(bundler.get("analysis_scope") or "not reported")
    if block_start is not None and block_end is not None:
        scope += f"; blocks {block_start}-{block_end}"
    owners = bundler.get("first_acquisition_owner_count")
    if owners is not None:
        scope += f"; {owners} first-acquisition owner(s)"
    gate_reason = candidate.get("gate_reason") or candidate.get("signal_note")

    lines = [
        f"### {index}. {_cell(name)} ({_cell(symbol)})",
        "",
        f"**{_signal_label(candidate.get('signal_status'))}** · "
        f"{_venue_label(candidate.get('venue'))} · `{_cell(candidate.get('change_state'))}`",
        "",
        f"**Contract:** `{contract}`",
        "",
        "| Live check | Result |",
        "|---|---:|",
        f"| Market cap | {_money(candidate.get('market_cap'))} |",
        f"| Liquidity | {_money(candidate.get('liquidity_usd'))} |",
        f"| Market structure | {_cell(candidate.get('market_structure'))} |",
        f"| 1h volume | {_money(candidate.get('volume_1h'))} |",
        f"| 1h buys / sells | {buys} / {sells} |",
        f"| Pair age | {age_text} |",
        f"| 5m / 1h change | {_cell(candidate.get('price_change_5m'))}% / {_cell(candidate.get('price_change_1h'))}% |",
        f"| Market prefilter | {_cell(market_screen.get('status'))} ({_cell(market_screen.get('score'))}/100) |",
        f"| GoPlus security | {_cell(security.get('status'))} / {_cell(security.get('risk_level'))} |",
        f"| Security blockers | {_cell(', '.join(security.get('hard_blockers') or []) or 'none shown')} |",
        f"| Linked-wallet check | {_cell(bundler.get('status'))} |",
        f"| Linked-wallet provider | {_cell(bundler.get('provider'))} |",
        f"| Linked clusters / blockers | {linked_clusters} / {blocking_clusters} |",
        f"| Largest linked-cluster share | {largest_share_text} |",
        f"| Same-block coverage | {_cell(coverage.get('same_block'))} |",
        f"| Pre-funding coverage | {_cell(coverage.get('pre_acquisition_funding'))} |",
        f"| Linked-wallet scope | {_cell(scope)} |",
        f"| Gate reason | {_cell(gate_reason)} |",
        "",
        _cell(gate_reason or "Research review is required."),
    ]
    dex_url = _safe_url(candidate.get("dex_url"))
    if dex_url:
        lines.extend(["", f"[Open live chart]({dex_url})"])
    source_links = []
    for item in candidate.get("profile_links") or []:
        if not isinstance(item, Mapping):
            continue
        url = _safe_url(item.get("url"))
        if url:
            source_links.append(f"[{_cell(item.get('label') or 'source', 40)}]({url})")
    if source_links:
        lines.append(" · ".join(source_links[:4]))

    cautions = list(market_screen.get("cautions") or [])
    blockers = list(market_screen.get("blockers") or [])
    linked_blockers = list(bundler.get("hard_blockers") or [])
    if blockers or cautions or bundler.get("status") != "complete" or linked_blockers:
        lines.extend(["", "**Needs attention:**"])
        for blocker in blockers[:5]:
            lines.append(f"- Market blocker: `{_cell(blocker)}`")
        for caution in cautions[:4]:
            lines.append(f"- {_cell(caution)}")
        for blocker in linked_blockers[:5]:
            lines.append(f"- Linked-wallet blocker: `{_cell(blocker)}`")
        if bundler.get("status") != "complete":
            lines.append(
                "- The bounded wallet check is incomplete. Missing history remains unknown—not safe."
            )
    lines.extend(
        [
            "",
            "_Wallet links are bounded on-chain observations, not proof of common ownership. A complete result means only that the stated window and providers completed._",
        ]
    )
    return lines


def render_venue_report(report: Mapping[str, Any]) -> str:
    notification = report.get("notification") or {}
    alert_candidates = list(notification.get("candidates") or [])
    all_candidates = list(report.get("candidates") or [])
    # The issue body doubles as the beta's current bounded screen. Always show
    # the latest ranked candidates there; alert comments are still created only
    # when the notification decision reports a material change.
    displayed = all_candidates[:8]
    counts = Counter(str(item.get("signal_status") or "unknown") for item in all_candidates)
    research_now_count = counts.get("screened_research", 0) + counts.get("research_now", 0)
    blocked_count = sum(value for key, value in counts.items() if key.startswith("blocked_"))

    lines = [
        "<!-- narrative-radar-launch-watch -->",
        "## Narra Radar launch watch",
        "",
        "**Exact-contract research alerts—not automatic buy signals.**",
        "",
        # Stable compatibility block for the phone beta. These labels are
        # intentionally simple so presentation changes cannot make a healthy
        # scanner look offline merely because a parser lost its anchors.
        "<!-- narra-radar-live-snapshot -->",
        "### Live snapshot",
        "",
        f"Update time: `{_cell(report.get('observed_at'))}`",
        f"Leads checked: `{_cell(report.get('profiles_received'))}`",
        f"Research now: `{research_now_count}`",
        f"Blocked: `{blocked_count}`",
        f"Visible candidates: `{len(displayed)}`",
        f"Source: `{_cell(report.get('provider'))}`",
        "",
        f"Observed: `{_cell(report.get('observed_at'))}`",
        f"Profiles checked: `{_cell(report.get('profiles_received'))}`; "
        f"eligible Pump.fun/Robinhood profiles: `{_cell(report.get('eligible_profiles'))}`",
        f"GoPlus scans: `{_cell(report.get('security_scans'))}`; "
        f"Helius holder scans: `{_cell(report.get('holder_scans'))}`; "
        f"bounded linked-wallet scans: `{_cell(report.get('bundler_scans'))}`",
        "",
    ]
    if alert_candidates:
        research_count = int(notification.get("research_candidate_count") or 0)
        downgrade_count = int(notification.get("safety_downgrade_count") or 0)
        lines.extend(
            [
                f"### {len(alert_candidates)} material launch-watch update(s)",
                "",
                f"New/strengthened research candidates: `{research_count}`; safety downgrades: `{downgrade_count}`.",
                "Read every remaining warning before making your own decision.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "### No new candidate cleared the available gates",
                "",
                "The latest leads are shown for transparency; blocked and incomplete checks were not promoted.",
                "",
            ]
        )

    for index, candidate in enumerate(displayed, start=1):
        lines.extend(_candidate_lines(candidate, index))
        lines.append("")

    lines.extend(
        [
            "### Scan summary",
            "",
            f"- Screened research: `{counts.get('screened_research', 0)}`",
            f"- Research now / manual link check: `{counts.get('research_now', 0)}`",
            f"- Market watch or queued: `{counts.get('market_watch', 0) + counts.get('queued_security', 0)}`",
            f"- Blocked: `{blocked_count}`",
            "",
            "A DEX profile is promotional material, not independent evidence. Even a screened result can fail, lose liquidity, or collapse. No wallet, private key, order, or automatic execution is used.",
        ]
    )
    return "\n".join(lines)


def venue_notification_state(report: Mapping[str, Any]) -> dict:
    notification = report.get("notification") or {}
    return {
        "notify": bool(notification.get("notify")),
        "reason": str(notification.get("reason") or "unknown"),
        "candidate_count": int(notification.get("candidate_count") or 0),
        "research_candidate_count": int(
            notification.get("research_candidate_count") or 0
        ),
        "safety_downgrade_count": int(
            notification.get("safety_downgrade_count") or 0
        ),
    }
