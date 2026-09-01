"""Read-only token security normalization for scam and rug-risk screening."""

from collections.abc import Mapping
from math import isfinite
from typing import Any

import requests


EVM_TOKEN_SECURITY_URL = (
    "https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
)
SOLANA_TOKEN_SECURITY_URL = (
    "https://api.gopluslabs.io/api/v1/solana/token_security"
)
EVM_CHAIN_IDS = {
    "ethereum": "1",
    "bsc": "56",
    "base": "8453",
    "robinhood": "4663",
}
_ZERO_ADDRESSES = {
    "",
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
}
_EXCLUDED_HOLDER_TAGS = {
    "black hole",
    "burn",
    "dead",
    "liquidity pool",
    "locker",
    "null",
    "pair",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _truth(value: Any) -> bool | None:
    if isinstance(value, Mapping):
        value = value.get("status", value.get("value"))
    if value is True or value == 1 or (
        isinstance(value, str) and value in {"1", "2"}
    ):
        return True
    if value is False or value == 0 or value == "0":
        return False
    return None


def _percent(value: Any) -> float | None:
    number = _number(value)
    if number is None or number < 0:
        return None
    return round(number * 100 if number <= 1 else number, 4)


def _flag(code: str, severity: str, message: str, **details: Any) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "details": details,
    }


def _excluded_holder(row: Mapping[str, Any]) -> bool:
    if _truth(row.get("is_locked")) is True:
        return True
    tag = str(row.get("tag") or "").strip().lower()
    return any(value in tag for value in _EXCLUDED_HOLDER_TAGS)


def _holder_metrics(rows: Any) -> dict:
    if not isinstance(rows, list):
        rows = []
    raw = []
    exposed = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        percent = _percent(row.get("percent"))
        if percent is None:
            continue
        raw.append(percent)
        if not _excluded_holder(row):
            exposed.append(percent)
    return {
        "row_count": len(rows),
        "raw_top_rows_share_pct": round(sum(raw), 4) if raw else None,
        "largest_unlocked_unexcluded_share_pct": max(exposed) if exposed else None,
        "top_unlocked_unexcluded_share_pct": (
            round(sum(exposed), 4) if exposed else None
        ),
    }


def _result_item(payload: Mapping[str, Any], contract_address: str) -> dict:
    result = payload.get("result") or {}
    if not isinstance(result, Mapping):
        return {}
    wanted = contract_address.casefold()
    for key, value in result.items():
        if str(key).casefold() == wanted and isinstance(value, Mapping):
            return dict(value)
    return {}


def _active_owner(item: Mapping[str, Any]) -> bool:
    owner = str(item.get("owner_address") or "").strip().casefold()
    return owner not in _ZERO_ADDRESSES


def _risk_level(flags: list[dict]) -> str:
    if any(flag["severity"] == "critical" for flag in flags):
        return "critical"
    if any(flag["severity"] == "high" for flag in flags):
        return "high"
    if any(flag["severity"] == "medium" for flag in flags):
        return "medium"
    return "low"


def _add_boolean_flag(
    flags: list[dict],
    item: Mapping[str, Any],
    field: str,
    code: str,
    severity: str,
    message: str,
) -> None:
    if _truth(item.get(field)) is True:
        flags.append(_flag(code, severity, message, source_field=field))


def _evm_report(item: Mapping[str, Any]) -> dict:
    flags: list[dict] = []
    owner_active = _active_owner(item)
    open_source = _truth(item.get("is_open_source"))
    if open_source is False:
        flags.append(
            _flag(
                "closed_source_contract",
                "high",
                "Contract source is closed; dangerous behavior cannot be fully inspected.",
            )
        )
    elif open_source is None:
        flags.append(
            _flag(
                "open_source_status_unknown",
                "medium",
                "Contract source-verification status is unavailable.",
            )
        )

    for args in (
        (
            "is_honeypot",
            "honeypot_detected",
            "critical",
            "Security simulation identifies the token as a honeypot.",
        ),
        (
            "cannot_buy",
            "cannot_buy",
            "critical",
            "The token may not be buyable in the security simulation.",
        ),
        (
            "hidden_owner",
            "hidden_owner",
            "critical",
            "The contract contains hidden ownership capability.",
        ),
        (
            "selfdestruct",
            "self_destruct_capability",
            "critical",
            "The contract can self-destruct.",
        ),
        (
            "is_airdrop_scam",
            "airdrop_scam",
            "critical",
            "The token is identified as an airdrop scam.",
        ),
        (
            "cannot_sell_all",
            "cannot_sell_all",
            "high",
            "The contract may prevent holders from selling their full balance.",
        ),
        (
            "is_proxy",
            "upgradeable_proxy",
            "high",
            "A proxy may allow token behavior to change after review.",
        ),
    ):
        _add_boolean_flag(flags, item, *args)

    fake_token = item.get("fake_token") or {}
    if isinstance(fake_token, Mapping) and _truth(fake_token.get("value")) is True:
        flags.append(
            _flag(
                "fake_token",
                "critical",
                "The contract may imitate another token.",
                true_token_address=fake_token.get("true_token_address"),
            )
        )

    can_take_back = _truth(item.get("can_take_back_ownership")) is True
    if can_take_back:
        flags.append(
            _flag(
                "ownership_can_return",
                "critical",
                "Ownership can be reclaimed after appearing renounced.",
            )
        )

    admin_fields = (
        (
            "owner_change_balance",
            "owner_can_change_balances",
            "critical",
            "An active owner can change holder balances.",
        ),
        (
            "slippage_modifiable",
            "modifiable_trading_tax",
            "high",
            "An active owner can modify trading tax or slippage settings.",
        ),
        (
            "personal_slippage_modifiable",
            "personal_tax_modifiable",
            "critical",
            "An active owner can set address-specific trading restrictions or tax.",
        ),
        (
            "transfer_pausable",
            "transfers_pausable",
            "high",
            "An active owner can pause transfers.",
        ),
        (
            "is_blacklisted",
            "blacklist_capability",
            "high",
            "An active owner can blacklist holders.",
        ),
        (
            "is_mintable",
            "mint_authority_active",
            "high",
            "An active owner can mint additional supply.",
        ),
    )
    for field, code, severity, message in admin_fields:
        active = _truth(item.get(field)) is True
        if active and (owner_active or can_take_back or code == "owner_can_change_balances"):
            flags.append(_flag(code, severity, message, source_field=field))
        elif active:
            flags.append(
                _flag(
                    f"{code}_but_owner_inactive",
                    "medium",
                    f"{message} Ownership appears inactive, but this needs verification.",
                    source_field=field,
                )
            )

    buy_tax_pct = _percent(item.get("buy_tax"))
    sell_tax_pct = _percent(item.get("sell_tax"))
    if sell_tax_pct is not None and sell_tax_pct >= 50:
        flags.append(
            _flag(
                "prohibitive_sell_tax",
                "critical",
                "Simulated sell tax is at least 50%.",
                sell_tax_pct=sell_tax_pct,
            )
        )
    elif sell_tax_pct is not None and sell_tax_pct >= 10:
        flags.append(
            _flag(
                "high_sell_tax",
                "high",
                "Simulated sell tax is at least 10%.",
                sell_tax_pct=sell_tax_pct,
            )
        )
    if buy_tax_pct is not None and buy_tax_pct >= 10:
        flags.append(
            _flag(
                "high_buy_tax",
                "high",
                "Simulated buy tax is at least 10%.",
                buy_tax_pct=buy_tax_pct,
            )
        )

    holder_metrics = _holder_metrics(item.get("holders"))
    largest = holder_metrics["largest_unlocked_unexcluded_share_pct"]
    top_share = holder_metrics["top_unlocked_unexcluded_share_pct"]
    if largest is not None and largest >= 20:
        flags.append(
            _flag(
                "single_holder_concentration",
                "high",
                "One unlocked, unexcluded top holder controls at least 20%.",
                largest_share_pct=largest,
            )
        )
    if top_share is not None and top_share >= 60:
        flags.append(
            _flag(
                "top_holder_concentration",
                "high",
                "Shown unlocked, unexcluded top holders control at least 60%.",
                top_share_pct=top_share,
            )
        )

    creator_pct = _percent(item.get("creator_percent"))
    owner_pct = _percent(item.get("owner_percent"))
    if creator_pct is not None and creator_pct >= 10:
        flags.append(
            _flag(
                "creator_supply_concentration",
                "high",
                "The creator controls at least 10% of supply.",
                creator_share_pct=creator_pct,
            )
        )
    if owner_pct is not None and owner_pct >= 10:
        flags.append(
            _flag(
                "owner_supply_concentration",
                "high",
                "The owner controls at least 10% of supply.",
                owner_share_pct=owner_pct,
            )
        )

    lp_metrics = _holder_metrics(item.get("lp_holders"))
    lp_exposed = lp_metrics["top_unlocked_unexcluded_share_pct"]
    if lp_exposed is not None and lp_exposed >= 50:
        flags.append(
            _flag(
                "unlocked_lp_concentration",
                "critical",
                "At least 50% of shown LP ownership appears unlocked and unexcluded.",
                unlocked_unexcluded_lp_share_pct=lp_exposed,
            )
        )
    elif lp_exposed is not None and lp_exposed >= 25:
        flags.append(
            _flag(
                "elevated_unlocked_lp_concentration",
                "high",
                "At least 25% of shown LP ownership appears unlocked and unexcluded.",
                unlocked_unexcluded_lp_share_pct=lp_exposed,
            )
        )
    elif _truth(item.get("is_in_dex")) is True and not lp_metrics["row_count"]:
        flags.append(
            _flag(
                "lp_lock_status_unknown",
                "medium",
                "DEX trading is reported, but LP lock/burn ownership is unavailable.",
            )
        )

    return {
        "data_complete": (
            open_source is True
            and _truth(item.get("is_honeypot")) is not None
            and _truth(item.get("cannot_buy")) is not None
            and sell_tax_pct is not None
            and holder_metrics["row_count"] > 0
        ),
        "contract_open_source": open_source,
        "owner_active": owner_active,
        "buy_tax_pct": buy_tax_pct,
        "sell_tax_pct": sell_tax_pct,
        "holder_count": _number(item.get("holder_count")),
        "holder_distribution": holder_metrics,
        "lp_holder_count": _number(item.get("lp_holder_count")),
        "lp_distribution": lp_metrics,
        "flags": flags,
    }


def _solana_report(item: Mapping[str, Any]) -> dict:
    flags: list[dict] = []
    for field, code, severity, message in (
        (
            "non_transferable",
            "non_transferable_token",
            "critical",
            "Token transfers are disabled by design.",
        ),
        (
            "balance_mutable_authority",
            "balance_mutable_authority",
            "critical",
            "An authority can modify token-account balances.",
        ),
        (
            "mintable",
            "mint_authority_active",
            "high",
            "Additional token supply can be minted.",
        ),
        (
            "freezable",
            "freeze_authority_active",
            "high",
            "Token accounts can be frozen.",
        ),
        (
            "closable",
            "close_authority_active",
            "high",
            "A close authority remains active.",
        ),
        (
            "default_account_state_upgradable",
            "default_state_upgradable",
            "high",
            "The default token-account state can be changed.",
        ),
        (
            "transfer_fee_upgradable",
            "transfer_fee_upgradable",
            "high",
            "Transfer fees can be changed by an authority.",
        ),
        (
            "transfer_hook_upgradable",
            "transfer_hook_upgradable",
            "high",
            "Transfer-hook behavior can be changed by an authority.",
        ),
        (
            "metadata_mutable",
            "metadata_mutable",
            "medium",
            "Token metadata can still be changed.",
        ),
    ):
        if _truth(item.get(field)) is True:
            flags.append(_flag(code, severity, message, source_field=field))

    transfer_hook = item.get("transfer_hook")
    if isinstance(transfer_hook, list) and transfer_hook:
        flags.append(
            _flag(
                "transfer_hook_active",
                "high",
                "A Token-2022 transfer hook can alter transfer behavior.",
            )
        )
    transfer_fee = item.get("transfer_fee") or {}
    if isinstance(transfer_fee, Mapping) and transfer_fee:
        flags.append(
            _flag(
                "transfer_fee_present",
                "medium",
                "Token-2022 transfer fees require manual review.",
            )
        )

    holder_metrics = _holder_metrics(item.get("holders"))
    largest = holder_metrics["largest_unlocked_unexcluded_share_pct"]
    top_share = holder_metrics["top_unlocked_unexcluded_share_pct"]
    if largest is not None and largest >= 20:
        flags.append(
            _flag(
                "single_holder_concentration",
                "high",
                "One unlocked, unexcluded top holder controls at least 20%.",
                largest_share_pct=largest,
            )
        )
    if top_share is not None and top_share >= 60:
        flags.append(
            _flag(
                "top_holder_concentration",
                "high",
                "Shown unlocked, unexcluded top holders control at least 60%.",
                top_share_pct=top_share,
            )
        )
    if not holder_metrics["row_count"]:
        flags.append(
            _flag(
                "holder_distribution_unknown",
                "medium",
                "No holder-distribution rows were returned.",
            )
        )

    authority_data_complete = (
        _truth(item.get("non_transferable")) is not None
        and all(
            _truth(item.get(field)) is not None
            for field in (
                "balance_mutable_authority",
                "closable",
                "freezable",
                "mintable",
                "default_account_state_upgradable",
                "transfer_fee_upgradable",
                "transfer_hook_upgradable",
            )
        )
        and "transfer_fee" in item
        and "transfer_hook" in item
    )

    return {
        "data_complete": (
            holder_metrics["row_count"] > 0
            and _truth(item.get("mintable")) is not None
            and _truth(item.get("freezable")) is not None
            and _truth(item.get("balance_mutable_authority")) is not None
        ),
        "authority_data_complete": authority_data_complete,
        "trusted_token": _truth(item.get("trusted_token")) is True,
        "holder_count": _number(item.get("holder_count")),
        "holder_distribution": holder_metrics,
        "lp_holder_count": None,
        "lp_distribution": {
            "row_count": 0,
            "raw_top_rows_share_pct": None,
            "largest_unlocked_unexcluded_share_pct": None,
            "top_unlocked_unexcluded_share_pct": None,
        },
        "flags": flags,
    }


class GoPlusTokenSecurityProvider:
    """Fetch normalized security data without signing or submitting anything."""

    provider_name = "goplus"

    def __init__(self, session=None, timeout: int = 20):
        self.session = session or requests.Session()
        self.timeout = max(1, int(timeout))

    def fetch(self, contract_address: str, chain: str) -> dict:
        contract = str(contract_address or "").strip()
        normalized_chain = str(chain or "").strip().lower()
        if not contract:
            raise ValueError("contract_address is required")
        if normalized_chain == "solana":
            url = SOLANA_TOKEN_SECURITY_URL
        elif normalized_chain in EVM_CHAIN_IDS:
            url = EVM_TOKEN_SECURITY_URL.format(
                chain_id=EVM_CHAIN_IDS[normalized_chain]
            )
        else:
            return {
                "status": "unsupported_chain",
                "provider": self.provider_name,
                "chain": normalized_chain or "unknown",
                "contract_address": contract,
                "risk_level": "unknown",
                "hard_blockers": ["token_security_unsupported"],
                "promotion_eligible": False,
                "bundler_analysis": {
                    "status": "not_available",
                    "note": "No linked-wallet or funding-cluster adapter is configured.",
                },
                "execution_enabled": False,
            }

        response = self.session.get(
            url,
            params={"contract_addresses": contract},
            headers={"User-Agent": "NarrativeRadar/1.0 (+research-only)"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping) or int(payload.get("code") or 0) != 1:
            raise RuntimeError("token security provider returned an unsuccessful result")
        item = _result_item(payload, contract)
        if not item:
            return {
                "status": "no_data",
                "provider": self.provider_name,
                "chain": normalized_chain,
                "contract_address": contract,
                "risk_level": "unknown",
                "hard_blockers": ["token_security_no_data"],
                "promotion_eligible": False,
                "bundler_analysis": {
                    "status": "not_available",
                    "note": "No linked-wallet or funding-cluster adapter is configured.",
                },
                "execution_enabled": False,
            }

        normalized = (
            _solana_report(item)
            if normalized_chain == "solana"
            else _evm_report(item)
        )
        flags = normalized.pop("flags")
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        flags.sort(key=lambda flag: (severity_order.get(flag["severity"], 4), flag["code"]))
        hard_blockers = [
            flag["code"]
            for flag in flags
            if flag["severity"] in {"critical", "high"}
        ]
        if normalized.get("data_complete") is not True:
            hard_blockers.append("security_data_incomplete")
        return {
            "status": "complete",
            "provider": self.provider_name,
            "chain": normalized_chain,
            "contract_address": contract,
            **normalized,
            "risk_level": _risk_level(flags),
            "flags": flags,
            "hard_blockers": hard_blockers,
            "promotion_eligible": not hard_blockers,
            "bundler_analysis": {
                "status": "not_available",
                "note": (
                    "Holder concentration is checked, but linked-wallet funding or "
                    "same-block bundle clustering is not yet available."
                ),
            },
            "execution_enabled": False,
            "note": (
                "Third-party security heuristics reduce obvious scam and rug risk but "
                "cannot prove a token is safe. Unknown data fails closed in the decision gate."
            ),
        }
