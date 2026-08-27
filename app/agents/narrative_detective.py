from collections import Counter
from typing import Any, Iterable, List, Optional

from app.database.models import Evidence


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def build_research_query(
    contract_address: str,
    chain: str = "unknown",
    token_name: Optional[str] = None,
    token_symbol: Optional[str] = None,
) -> str:
    parts = [
        token_name,
        token_symbol,
        f"contract {contract_address}",
        chain if chain and chain.lower() not in {"unknown", "auto", "any"} else None,
        "crypto token",
    ]
    return " ".join(str(part).strip() for part in parts if part and str(part).strip())


def results_to_evidence(
    results: Iterable[Any],
    contract_address: str,
    token_name: Optional[str] = None,
    token_symbol: Optional[str] = None,
) -> List[Evidence]:
    """Convert search results into deliberately unverified evidence.

    A search hit is not treated as a primary-source confirmation. Only evidence
    entered from a known primary source can reach the verified threshold.
    """
    evidence: List[Evidence] = []
    seen_urls = set()
    needle = (contract_address or "").lower()
    identity = token_symbol or token_name or contract_address

    for result in results:
        title = str(_get_value(result, "title", "")).strip()
        url = str(_get_value(result, "url", "")).strip()
        snippet = str(_get_value(result, "snippet", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        matched_contract = bool(needle and needle in f"{title} {snippet}".lower())
        confidence = 0.60 if matched_contract else 0.35
        evidence.append(
            Evidence(
                claim=f"Public search result references {identity}: {title or url}",
                source_url=url,
                source_type="web_search",
                published_at=_get_value(result, "published_at"),
                quote=snippet[:500] or None,
                relevance=(
                    "Search result contains the contract address"
                    if matched_contract
                    else "Search result may relate to the token identity"
                ),
                confidence=confidence,
            )
        )

    return evidence


def build_narrative_report(
    token_name: str,
    token_symbol: str,
    evidence: Iterable[Evidence],
) -> dict:
    items = list(evidence)
    verified = [
        item.to_dict()
        for item in items
        if item.source_type == "primary" and item.confidence >= 0.75
    ]
    uncertain = [
        item.to_dict()
        for item in items
        if not (item.source_type == "primary" and item.confidence >= 0.75)
    ]

    source_breakdown = Counter(item.source_type for item in items)
    return {
        "token_name": token_name,
        "token_symbol": token_symbol,
        "evidence_count": len(items),
        "verified_evidence": verified,
        "uncertain_evidence": uncertain,
        "source_breakdown": dict(source_breakdown),
        "status": "evidence_found" if items else "no_evidence",
        "note": (
            "Search results are leads, not endorsements. Verify primary sources "
            "before treating a claim as confirmed."
        ),
    }
