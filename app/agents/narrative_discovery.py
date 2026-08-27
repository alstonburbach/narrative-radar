from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional
from urllib.parse import urlparse
import re

from app.agents.narrative_detective import results_to_evidence
from app.agents.narrative_quality import assess_narrative_quality


POSITIVE_DISCOVERY_LENSES = {
    "official_builders",
    "adoption_usage",
    "funding_backers",
    "onchain_tokenomics",
}


DISCOVERY_LENSES = {
    "official_builders": "official docs open source github developers release",
    "adoption_usage": "integration launch users customers usage fees partnership",
    "funding_backers": "funding round investors financing grants backers",
    "onchain_tokenomics": "on-chain activity users volume fees token supply unlocks",
    "counterevidence": "scam exploit hack criticism insider unlocks controversy",
}

STOP_WORDS = {
    "about",
    "after",
    "also",
    "been",
    "being",
    "blockchain",
    "chain",
    "crypto",
    "data",
    "from",
    "funding",
    "github",
    "growth",
    "into",
    "latest",
    "launch",
    "mainnet",
    "market",
    "more",
    "new",
    "official",
    "onchain",
    "on-chain",
    "partnership",
    "project",
    "protocol",
    "release",
    "relate",
    "references",
    "result",
    "results",
    "round",
    "search",
    "short",
    "some",
    "team",
    "token",
    "users",
    "usage",
    "web3",
    "with",
    "public",
    "narrative",
    "narratives",
    "identity",
    "claim",
}


def build_discovery_queries(
    topic: Optional[str] = None,
    chain: str = "unknown",
) -> dict[str, str]:
    """Build broad discovery searches while keeping the evidence lenses separate."""
    anchor = (topic or "crypto narratives").strip()
    chain_text = ""
    if chain and chain.lower() not in {"unknown", "auto", "any"}:
        chain_text = f" {chain.strip()}"
    return {
        lens: f"{anchor}{chain_text} {suffix}".strip()
        for lens, suffix in DISCOVERY_LENSES.items()
    }


def _domain(url: str) -> str:
    return (urlparse(str(url)).hostname or "").lower().removeprefix("www.")


def _tokens(text: str) -> List[str]:
    values = re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
    return [value for value in values if value not in STOP_WORDS]


def cluster_signal_terms(
    evidence: Iterable[Any],
    min_domains: int = 2,
    min_lenses: int = 2,
    limit: int = 15,
) -> List[dict]:
    """Find repeated terms across independent sources and research lenses.

    These are candidate labels for human review, not automatically extracted
    claims about a project or sector.
    """
    signals = defaultdict(
        lambda: {
            "mentions": 0,
            "domains": set(),
            "lenses": set(),
            "urls": set(),
            "source_types": set(),
        }
    )

    for item in evidence:
        title = str(getattr(item, "claim", ""))
        quote = str(getattr(item, "quote", ""))
        if isinstance(item, dict):
            title = str(item.get("claim", ""))
            quote = str(item.get("quote", ""))
        words = _tokens(f"{title} {quote}")
        phrases = set(words)
        phrases.update(
            f"{left} {right}"
            for left, right in zip(words, words[1:])
            if left != right
        )
        url = getattr(item, "source_url", "")
        lens = getattr(item, "research_lens", None)
        source_type = getattr(item, "source_type", "unknown")
        if isinstance(item, dict):
            url = item.get("source_url", "")
            lens = item.get("research_lens")
            source_type = item.get("source_type") or "unknown"
        domain = _domain(url)
        for phrase in phrases:
            signal = signals[phrase]
            signal["mentions"] += 1
            if domain:
                signal["domains"].add(domain)
            if lens:
                signal["lenses"].add(lens)
            if url:
                signal["urls"].add(url)
            if source_type:
                signal["source_types"].add(source_type)

    candidates = []
    for label, signal in signals.items():
        if len(signal["domains"]) < min_domains or len(signal["lenses"]) < min_lenses:
            continue
        if not (signal["lenses"] & POSITIVE_DISCOVERY_LENSES):
            continue
        if not (signal["source_types"] - {"social_lead"}):
            continue
        score = min(
            100,
            signal["mentions"] * 5
            + len(signal["domains"]) * 15
            + len(signal["lenses"]) * 10,
        )
        candidates.append(
            {
                "label": label,
                "signal_score": score,
                "mentions": signal["mentions"],
                "independent_domains": sorted(signal["domains"]),
                "lenses": sorted(signal["lenses"]),
                "positive_lenses": sorted(
                    signal["lenses"] & POSITIVE_DISCOVERY_LENSES
                ),
                "source_types": sorted(signal["source_types"]),
                "evidence_urls": sorted(signal["urls"])[:5],
                "classification_only": True,
            }
        )

    return sorted(
        candidates,
        key=lambda item: (-item["signal_score"], -item["mentions"], item["label"]),
    )[: max(1, int(limit))]


def discover_narratives(
    provider: Any,
    topic: Optional[str] = None,
    chain: str = "unknown",
    limit: int = 5,
) -> dict:
    """Search for emerging narrative leads before a contract is known."""
    started_at = datetime.now(timezone.utc).isoformat()
    normalized_chain = (chain or "unknown").strip().lower()
    queries = build_discovery_queries(topic=topic, chain=normalized_chain)
    anchor = (topic or "crypto narratives").strip()
    evidence = []
    seen_urls = set()
    lens_reports = {}
    searched_lenses = []
    errors = []
    limit = max(1, min(int(limit), 20))

    for lens, query in queries.items():
        report = {"query": query, "status": "pending", "result_count": 0, "error": None}
        try:
            results = provider.search(query, limit=limit)
            lens_evidence = results_to_evidence(
                results,
                contract_address="",
                token_name=anchor,
                research_lens=lens,
            )
            for item in lens_evidence:
                url = item.source_url.rstrip("/").lower()
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                evidence.append(item)
            report["status"] = "complete"
            report["result_count"] = len(lens_evidence)
            searched_lenses.append(lens)
        except Exception as exc:
            report["status"] = "failed"
            report["error"] = str(exc)
            errors.append(f"{lens}: {exc}")
        lens_reports[lens] = report

    if len(searched_lenses) == len(queries):
        status = "complete"
    elif searched_lenses:
        status = "partial"
    else:
        status = "failed"

    quality = assess_narrative_quality(evidence, searched_lenses=searched_lenses)
    return {
        "topic": anchor,
        "chain": normalized_chain,
        "started_at": started_at,
        "status": status,
        "queries": queries,
        "lenses": lens_reports,
        "searched_lenses": searched_lenses,
        "lead_count": len(evidence),
        "independent_domain_count": len(
            {
                _domain(item.source_url)
                for item in evidence
                if _domain(item.source_url)
            }
        ),
        "candidate_signals": cluster_signal_terms(evidence),
        "evidence": [item.to_dict() for item in evidence],
        "quality": quality,
        "error": "; ".join(errors) if errors else None,
        "disclaimer": (
            "Discovery results are unverified leads. Validate the underlying project, "
            "people, on-chain data, and counterevidence before treating a theme as real."
        ),
    }
