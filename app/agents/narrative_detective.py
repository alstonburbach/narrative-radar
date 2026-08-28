from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional
from urllib.parse import urlparse, urlunparse

from app.database.models import Evidence


RESEARCH_LENSES = {
    "official_builders": "official docs github developers team roadmap",
    "adoption_usage": "integrations launch users customers usage partnership",
    "funding_backers": "funding investors financing team backers",
    "onchain_tokenomics": "token allocation unlocks holders treasury contract on-chain",
    "counterevidence": "scam exploit hack criticism insider unlocks lawsuit controversy",
}

SOCIAL_DOMAINS = {
    "x.com",
    "twitter.com",
    "t.co",
    "t.me",
    "telegram.me",
    "discord.com",
    "discord.gg",
    "reddit.com",
    "old.reddit.com",
    "farcaster.xyz",
    "warpcast.com",
}

ONCHAIN_DOMAINS = {
    "etherscan.io",
    "basescan.org",
    "arbiscan.io",
    "optimistic.etherscan.io",
    "bscscan.com",
    "solscan.io",
    "solana.fm",
    "dexscreener.com",
    "birdeye.so",
}

SECONDARY_DOMAINS = {
    "coindesk.com",
    "theblock.co",
    "cointelegraph.com",
    "decrypt.co",
    "blockworks.co",
    "dlnews.com",
}

ALLOWED_SEARCH_SOURCE_TYPES = {
    "primary_candidate",
    "onchain_data",
    "secondary_lead",
    "social_lead",
    "web_search",
}


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            parsed.query,
            "",
        )
    )


def classify_source(url: str) -> str:
    """Classify a URL as a lead category without claiming verification."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host in SOCIAL_DOMAINS:
        return "social_lead"
    if host == "github.com" or host.endswith(".github.io"):
        return "primary_candidate"
    if host in ONCHAIN_DOMAINS or host.endswith(".etherscan.io"):
        return "onchain_data"
    if host in SECONDARY_DOMAINS:
        return "secondary_lead"
    return "web_search"


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


def build_research_queries(
    contract_address: str,
    chain: str = "unknown",
    token_name: Optional[str] = None,
    token_symbol: Optional[str] = None,
) -> dict[str, str]:
    """Build independent research lenses around the same token identity."""
    base = build_research_query(
        contract_address=contract_address,
        chain=chain,
        token_name=token_name,
        token_symbol=token_symbol,
    )
    return {
        lens: f"{base} {suffix}".strip()
        for lens, suffix in RESEARCH_LENSES.items()
    }


def results_to_evidence(
    results: Iterable[Any],
    contract_address: str,
    token_name: Optional[str] = None,
    token_symbol: Optional[str] = None,
    research_lens: Optional[str] = None,
    retrieved_at: Optional[str] = None,
) -> List[Evidence]:
    """Convert search results into deliberately unverified evidence.

    A search hit is not treated as a primary-source confirmation. Only evidence
    entered from a known primary source can reach the verified threshold.
    """
    evidence: List[Evidence] = []
    seen_urls = set()
    needle = (contract_address or "").lower()
    identity = token_symbol or token_name or contract_address
    retrieved_at = retrieved_at or datetime.now(timezone.utc).isoformat()

    for result in results:
        title = str(_get_value(result, "title", "")).strip()
        url = str(_get_value(result, "url", "")).strip()
        snippet = str(_get_value(result, "snippet", "")).strip()
        canonical_url = _canonical_url(url) if url else ""
        if not canonical_url or canonical_url in seen_urls:
            continue
        seen_urls.add(canonical_url)

        matched_contract = bool(needle and needle in f"{title} {snippet}".lower())
        confidence = 0.60 if matched_contract else 0.35
        declared_source_type = str(
            _get_value(result, "source_type", "") or ""
        ).strip()
        source_type = (
            declared_source_type
            if declared_source_type in ALLOWED_SEARCH_SOURCE_TYPES
            else classify_source(url)
        )
        evidence.append(
            Evidence(
                claim=f"Public search result references {identity}: {title or url}",
                source_url=url,
                source_type=source_type,
                published_at=_get_value(result, "published_at"),
                quote=snippet[:500] or None,
                relevance=(
                    "Search result contains the contract address"
                    if matched_contract
                    else "Search result may relate to the token identity"
                ),
                confidence=confidence,
                claim_type="lead",
                verification_status="unverified_search_lead",
                research_lens=research_lens,
                retrieved_at=retrieved_at,
            )
        )

    return evidence


def run_lens_research(
    provider: Any,
    contract_address: str,
    chain: str = "unknown",
    token_name: Optional[str] = None,
    token_symbol: Optional[str] = None,
    limit: int = 5,
) -> tuple[List[Evidence], dict]:
    """Search multiple lenses and keep a transparent audit of each query."""
    queries = build_research_queries(
        contract_address=contract_address,
        chain=chain,
        token_name=token_name,
        token_symbol=token_symbol,
    )
    evidence: List[Evidence] = []
    seen_urls = set()
    lens_reports = {}
    successful_lenses = []
    errors = []
    limit = max(1, min(int(limit), 20))

    for lens, query in queries.items():
        lens_report = {"query": query, "status": "pending", "result_count": 0, "error": None}
        try:
            results = provider.search(query, limit=limit)
            lens_evidence = results_to_evidence(
                results,
                contract_address=contract_address,
                token_name=token_name,
                token_symbol=token_symbol,
                research_lens=lens,
            )
            for item in lens_evidence:
                canonical_url = _canonical_url(item.source_url)
                if canonical_url in seen_urls:
                    continue
                seen_urls.add(canonical_url)
                evidence.append(item)
            lens_report["status"] = "complete"
            lens_report["result_count"] = len(lens_evidence)
            successful_lenses.append(lens)
        except Exception as exc:
            lens_report["status"] = "failed"
            lens_report["error"] = str(exc)
            errors.append(f"{lens}: {exc}")
        lens_reports[lens] = lens_report

    if len(successful_lenses) == len(queries):
        status = "complete"
    elif successful_lenses:
        status = "partial"
    else:
        status = "failed"
    return evidence, {
        "status": status,
        "queries": queries,
        "lenses": lens_reports,
        "searched_lenses": successful_lenses,
        "result_count": len(evidence),
        "error": "; ".join(errors) if errors else None,
    }


def build_narrative_report(
    token_name: str,
    token_symbol: str,
    evidence: Iterable[Evidence],
    quality: Optional[dict] = None,
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
        "quality": quality or {},
        "note": (
            "Search results are leads, not endorsements. Verify primary sources "
            "before treating a claim as confirmed."
        ),
    }
