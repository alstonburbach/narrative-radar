"""GitHub issue parsing and mobile reports for forward-time paper signals."""

import base64
from collections.abc import Mapping
import json
from math import isfinite
import re
from typing import Any
from urllib.parse import urlparse

from app.paper_signal import PAPER_SIGNAL_VERSION, validate_paper_signal_state


_EVM_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SUPPORTED_CHAINS = {"auto", "unknown", "solana", "base", "ethereum", "bsc"}
_NO_RESPONSE_VALUES = {"", "_no response_", "no response", "none", "n/a"}
_STATE_MARKER = re.compile(
    r"<!-- narrative-radar-paper-state:([A-Za-z0-9_-]+) -->"
)


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


def _positive_number(
    value: str | None,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(str(value or "").replace("$", "").replace(",", "").strip())
    except ValueError:
        raise ValueError(f"{field} must be a number.") from None
    if not isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}.")
    return round(number, 4)


def _validated_contract(value: str | None, chain: str) -> str:
    contract = str(value or "").strip().strip("`").strip()
    if not contract or any(character.isspace() for character in contract):
        raise ValueError("A single token contract address is required.")
    is_evm = bool(_EVM_ADDRESS.fullmatch(contract))
    is_solana = bool(_SOLANA_ADDRESS.fullmatch(contract))
    if not is_evm and not is_solana:
        raise ValueError("Contract must be a valid EVM 0x address or Solana mint address.")
    if chain == "solana" and not is_solana:
        raise ValueError("The Solana chain selection requires a Solana mint address.")
    if chain in {"base", "ethereum", "bsc"} and not is_evm:
        raise ValueError(f"The {chain} chain selection requires an EVM 0x address.")
    return contract


def parse_paper_signal_request(body: str) -> dict:
    """Parse a bounded, non-executing paper signal from the issue form."""
    sections = _sections(body)
    chain = str(_section_value(sections, "Chain") or "auto").strip().lower()
    if chain not in _SUPPORTED_CHAINS:
        raise ValueError("Chain must be auto, solana, base, ethereum, or bsc.")
    normalized_chain = "unknown" if chain in {"auto", "unknown"} else chain
    contract = _validated_contract(
        _section_value(sections, "Contract address"),
        normalized_chain,
    )
    stake_usd = _positive_number(
        _section_value(sections, "Paper stake USD") or "50",
        "Paper stake",
        1,
        100_000,
    )
    target_multiple = _positive_number(
        _section_value(sections, "Target multiple") or "10",
        "Target multiple",
        2,
        100,
    )
    family = re.sub(
        r"\s+",
        " ",
        str(_section_value(sections, "Narrative family") or "unassigned"),
    ).strip()
    if len(family) > 80:
        raise ValueError("Narrative family must contain no more than 80 characters.")
    source_text = str(
        _section_value(sections, "Signal source") or "Narrative Radar"
    ).strip().lower()
    source_map = {
        "narrative radar": "narrative_radar",
        "manual research": "manual_research",
    }
    if source_text not in source_map:
        raise ValueError("Signal source must be Narrative Radar or Manual research.")
    return {
        "contract_address": contract,
        "chain": normalized_chain,
        "stake_usd": stake_usd,
        "target_multiple": target_multiple,
        "narrative_family": family or "unassigned",
        "signal_source": source_map[source_text],
    }


def validate_owner_paper_event(event: Mapping[str, Any]) -> dict:
    """Fail closed unless the repository owner opened a paper-signal issue."""
    issue = event.get("issue") or {}
    repository = event.get("repository") or {}
    requester = str((issue.get("user") or {}).get("login") or "").strip()
    owner = str((repository.get("owner") or {}).get("login") or "").strip()
    title = str(issue.get("title") or "").strip()
    if not requester or not owner or requester.casefold() != owner.casefold():
        raise ValueError("Only the repository owner can start a paper signal.")
    if not title.upper().startswith("[RADAR PAPER]"):
        raise ValueError("Issue title must start with [RADAR PAPER].")
    return parse_paper_signal_request(str(issue.get("body") or ""))


def encode_paper_state(state: Mapping[str, Any]) -> str:
    validated = validate_paper_signal_state(state)
    payload = json.dumps(
        validated,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def extract_paper_state(body: str) -> dict:
    match = _STATE_MARKER.search(str(body or ""))
    if not match:
        raise ValueError("Paper state marker was not found.")
    token = match.group(1)
    padding = "=" * (-len(token) % 4)
    try:
        payload = base64.urlsafe_b64decode(f"{token}{padding}")
        state = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Paper state marker is invalid.") from exc
    if not isinstance(state, dict):
        raise ValueError("Paper state marker must contain an object.")
    return validate_paper_signal_state(state)


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


def _money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if abs(number) >= 1_000_000:
        return f"${number / 1_000_000:,.2f}M"
    if abs(number) >= 1_000:
        return f"${number / 1_000:,.1f}K"
    return f"${number:,.2f}"


def _safe_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if any(character.isspace() or character in "()<>" for character in url):
        return None
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else None


def render_paper_signal_error(message: str) -> str:
    return "\n".join(
        [
            "<!-- narrative-radar-paper-report -->",
            "## Paper signal could not start",
            "",
            str(message).strip() or "The request was invalid.",
            "",
            "No transaction was created, signed, or submitted.",
        ]
    )


def render_paper_signal_report(state: Mapping[str, Any]) -> str:
    """Render the latest sampled mark and embed the validated machine state."""
    state = validate_paper_signal_state(state)
    marker = f"<!-- narrative-radar-paper-state:{encode_paper_state(state)} -->"
    latest = state.get("latest_snapshot") or {}
    target_reached = bool(state.get("target_reached_at"))
    lines = [
        "<!-- narrative-radar-paper-report -->",
        marker,
        f"## Paper signal: {_cell(state.get('token_name'))} ({_cell(state.get('token_symbol'))})",
        "",
        (
            "**Sampled target reached.** This remains a paper observation."
            if target_reached
            else "**Open paper signal.** No capital was deployed."
        ),
        "",
        "| Check | Result |",
        "|---|---:|",
        f"| Status | {_cell(state.get('status'))} / {_cell(state.get('mark_status'))} |",
        f"| Signal source | {_cell(state.get('signal_source'))} |",
        f"| Narrative family | {_cell(state.get('narrative_family'))} |",
        f"| Chain | {_cell(state.get('chain'))} |",
        f"| Contract | `{_cell(state.get('contract_address'))}` |",
        f"| Paper stake | {_money(state.get('stake_usd'))} |",
        f"| Entry gate | {_cell(state.get('entry_decision_gate'))} |",
        f"| Entry radar score | {_cell(state.get('entry_radar_score'))} |",
        f"| Entry evidence quality | {_cell(state.get('entry_narrative_quality_score'))} |",
        f"| Entry risk | {_cell(state.get('entry_risk_level'))} |",
        f"| Entry market cap | {_money(state.get('entry_market_cap'))} |",
        f"| Current market cap | {_money(state.get('current_market_cap'))} |",
        f"| Current multiple | {_cell(state.get('current_multiple'))}x |",
        f"| Highest sampled multiple | {_cell(state.get('highest_sampled_multiple'))}x |",
        f"| Target | {_cell(state.get('target_multiple'))}x / {_money(state.get('target_market_cap'))} |",
        f"| Gross paper mark | {_money(state.get('gross_marked_value_usd'))} |",
        f"| Gross sampled PnL | {_money(state.get('gross_marked_pnl_usd'))} |",
        f"| Later marks | {_cell(state.get('marks_count'))} |",
        f"| Execution enabled | `{_cell(state.get('execution_enabled'))}` |",
    ]
    if state.get("last_error"):
        lines.extend(["", f"Mark note: {_cell(state.get('last_error'))}"])
    if latest.get("pair_changed_since_entry"):
        lines.extend(
            [
                "",
                "Pair note: the strongest-liquidity pair changed after entry; market-cap comparisons remain sampled research only.",
            ]
        )
    failed_requirements = state.get("entry_failed_requirements") or []
    if failed_requirements:
        lines.extend(
            [
                "",
                "Entry gate failures: "
                + ", ".join(_cell(item, limit=80) for item in failed_requirements),
            ]
        )
    dex_url = _safe_url(latest.get("dex_url"))
    if dex_url:
        lines.extend(["", f"[Open the current DEX chart]({dex_url})"])
    lines.extend(
        [
            "",
            "### Timing integrity",
            f"- Signal detected: `{_cell(state.get('signal_detected_at'))}`",
            f"- Entry recorded: `{_cell(state.get('entry_recorded_at'))}`",
            f"- Signal-to-entry delay: `{_cell(state.get('entry_delay_seconds'))}` seconds",
            f"- Last checked: `{_cell(state.get('last_checked_at'))}`",
            f"- Target first sampled: `{_cell(state.get('target_reached_at'))}`",
            "",
            f"Sample note: {_cell(state.get('sampled_only_note'))}",
            "",
            "---",
            "No transaction was created, signed, or submitted. This is forward-time paper tracking, not financial advice.",
        ]
    )
    return "\n".join(lines)


def render_paper_alert(notification: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "<!-- narrative-radar-paper-alert -->",
            f"## {_cell(notification.get('message') or 'Paper milestone sampled')}",
            "",
            "This alert is based on a scheduled snapshot, not a trade or guaranteed fill.",
        ]
    )


def empty_paper_state() -> dict:
    """Expose the current schema version for workflow diagnostics."""
    return {"version": PAPER_SIGNAL_VERSION, "execution_enabled": False}
