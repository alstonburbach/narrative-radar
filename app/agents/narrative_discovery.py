from collections import Counter, defaultdict
from datetime import datetime, timezone
import re
from typing import Any, Iterable, List, Optional

from app.research_domains import source_domain_family
from app.research_independence import collapse_syndicated_evidence

from app.agents.narrative_detective import results_to_evidence
from app.agents.narrative_quality import assess_narrative_quality


POSITIVE_DISCOVERY_LENSES = {
    "official_builders",
    "adoption_usage",
    "funding_backers",
    "onchain_tokenomics",
}

SINGLE_TERM_NARRATIVES = {
    "depin",
    "gaming",
    "memecoin",
    "memecoins",
    "payments",
    "privacy",
    "restaking",
    "rwa",
    "stablecoin",
    "stablecoins",
    "tokenization",
}

CANONICAL_NARRATIVE_PATTERNS = {
    "ai agents": (
        r"\bai agents?\b",
        r"\bagentic (?:apps?|protocols?|systems?|wallets?)\b",
        r"\bautonomous (?:ai )?agents?\b",
    ),
    "depin": (
        r"\bdepin\b",
        r"\bdecentralized physical infrastructure\b",
    ),
    "memecoins": (
        r"\bmeme coins?\b",
        r"\bmemecoins?\b",
    ),
    "prediction markets": (
        r"\bprediction markets?\b",
        r"\bevent betting markets?\b",
    ),
    "privacy": (
        r"\bprivacy\b",
        r"\bprivate transactions?\b",
        r"\bzero[- ]knowledge\b",
        r"\bzk[- ]?proofs?\b",
    ),
    "real-world assets": (
        r"\brwa\b",
        r"\breal[- ]world assets?\b",
        r"\btokeni[sz](?:ed|ation) (?:real[- ]world )?assets?\b",
    ),
    "restaking": (r"\brestaking\b",),
    "stablecoins": (
        r"\bstablecoins?\b",
        r"\bdigital dollars?\b",
    ),
}


DISCOVERY_LENSES = {
    "counterevidence": (
        "scam exploit hack vulnerability criticism insider lawsuit controversy "
        "denies denied warning risk fraud fake breach halt failure flaw crash rug "
        "credible credibility"
    ),
    "official_builders": "official docs github builders developers release update upgrade",
    "funding_backers": "funding round raise capital investors financing grants backers",
    "onchain_tokenomics": "on-chain transactions activity holders volume fees supply staking unlocks",
    "adoption_usage": "adoption integration launch users customers usage payments partnership",
}

STOP_WORDS = {
    "about",
    "after",
    "again",
    "against",
    "all",
    "also",
    "and",
    "any",
    "are",
    "because",
    "before",
    "been",
    "being",
    "between",
    "blockchain",
    "both",
    "but",
    "can",
    "chain",
    "could",
    "crypto",
    "data",
    "does",
    "each",
    "even",
    "every",
    "first",
    "for",
    "from",
    "funding",
    "github",
    "growth",
    "had",
    "has",
    "have",
    "here",
    "how",
    "into",
    "its",
    "just",
    "latest",
    "launch",
    "like",
    "mainnet",
    "market",
    "may",
    "million",
    "more",
    "most",
    "new",
    "not",
    "now",
    "official",
    "one",
    "only",
    "onchain",
    "on-chain",
    "other",
    "our",
    "own",
    "out",
    "over",
    "partnership",
    "project",
    "protocol",
    "said",
    "says",
    "release",
    "relate",
    "report",
    "reported",
    "reports",
    "references",
    "result",
    "results",
    "round",
    "search",
    "should",
    "short",
    "some",
    "sold",
    "such",
    "team",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "token",
    "transaction",
    "transactions",
    "under",
    "unlock",
    "unlocks",
    "using",
    "users",
    "usage",
    "very",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "will",
    "would",
    "web3",
    "solana",
    "ethereum",
    "bitcoin",
    "base",
    "bsc",
    "with",
    "your",
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
    return source_domain_family(url)


def _tokens(text: str) -> List[str]:
    values = re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
    return [value for value in values if value not in STOP_WORDS]


def _canonical_narratives(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", str(text or "").lower())
    return {
        label
        for label, patterns in CANONICAL_NARRATIVE_PATTERNS.items()
        if any(re.search(pattern, normalized) for pattern in patterns)
    }


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
    independent_evidence, _ = collapse_syndicated_evidence(evidence)
    signals = defaultdict(
        lambda: {
            "mentions": 0,
            "domains": set(),
            "lenses": set(),
            "positive_domains": set(),
            "urls": set(),
            "source_types": set(),
            "canonical_theme": False,
        }
    )

    for item in independent_evidence:
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
        canonical_narratives = _canonical_narratives(f"{title} {quote}")
        phrases.update(canonical_narratives)
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
            if domain and lens in POSITIVE_DISCOVERY_LENSES:
                signal["positive_domains"].add(domain)
            if url:
                signal["urls"].add(url)
            if source_type:
                signal["source_types"].add(source_type)
            if phrase in canonical_narratives:
                signal["canonical_theme"] = True

    candidates = []
    for label, signal in signals.items():
        if " " not in label and label not in SINGLE_TERM_NARRATIVES:
            continue
        if len(signal["domains"]) < min_domains:
            continue
        positive_lenses = signal["lenses"] & POSITIVE_DISCOVERY_LENSES
        cross_source_theme_watch = (
            signal["canonical_theme"]
            and len(signal["positive_domains"]) >= min_domains
        )
        cross_lens_candidate = (
            len(signal["lenses"]) >= min_lenses
            and len(positive_lenses) >= 2
        )
        if not (cross_source_theme_watch or cross_lens_candidate):
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
                "positive_lenses": sorted(positive_lenses),
                "positive_domains": sorted(signal["positive_domains"]),
                "source_types": sorted(signal["source_types"]),
                "evidence_urls": sorted(signal["urls"])[:5],
                "research_strength": (
                    "cross_lens_candidate"
                    if cross_lens_candidate
                    else "cross_source_watch"
                ),
                "canonical_theme": bool(signal["canonical_theme"]),
                "classification_only": True,
            }
        )

    return sorted(
        candidates,
        key=lambda item: (-item["signal_score"], -item["mentions"], item["label"]),
    )[: max(1, int(limit))]


def build_signal_follow_up_queries(label: str, chain: str = "unknown") -> dict[str, str]:
    """Turn a candidate theme into transparent, human-review search prompts."""
    anchor = str(label or "").strip()
    chain_text = ""
    if chain and chain.lower() not in {"unknown", "auto", "any"}:
        chain_text = f" {chain.strip()}"
    return {
        "official_builders": f'"{anchor}"{chain_text} official docs github developers',
        "adoption_usage": f'"{anchor}"{chain_text} users customers integrations usage',
        "funding_backers": f'"{anchor}"{chain_text} funding investors grants backers',
        "onchain_tokenomics": f'"{anchor}"{chain_text} on-chain holders volume unlocks',
        "counterevidence": f'"{anchor}"{chain_text} scam exploit criticism insider unlocks',
    }


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
        "research_provider": getattr(provider, "provider_name", "custom"),
        "research_provider_requested": getattr(
            provider,
            "requested_provider",
            getattr(provider, "provider_name", "custom"),
        ),
        "deep_research_active": getattr(
            provider,
            "deep_research_active",
            getattr(provider, "provider_name", "custom") == "tavily",
        ),
        "provider_fallback_reason": getattr(provider, "fallback_reason", None),
        "provider_warnings": list(getattr(provider, "warnings", []) or []),
        "queries": queries,
        "lenses": lens_reports,
        "searched_lenses": searched_lenses,
        "lead_count": len(evidence),
        "independent_domain_count": quality["independent_domain_count"],
        "candidate_signals": [
            {
                **signal,
                "follow_up_queries": build_signal_follow_up_queries(
                    signal["label"], normalized_chain
                ),
            }
            for signal in cluster_signal_terms(evidence)
        ],
        "evidence": [item.to_dict() for item in evidence],
        "quality": quality,
        "error": "; ".join(errors) if errors else None,
        "disclaimer": (
            "Discovery results are unverified leads. Validate the underlying project, "
            "people, on-chain data, and counterevidence before treating a theme as real."
        ),
    }
