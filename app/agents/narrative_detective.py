from typing import Dict, List

from app.database.models import Evidence


def build_narrative_report(
    token_name: str,
    token_symbol: str,
    evidence: List[Evidence],
) -> dict:

    verified = []
    uncertain = []

    for item in evidence:
        if item.confidence >= 0.75:
            verified.append(item.to_dict())
        else:
            uncertain.append(item.to_dict())

    source_types = sorted({item.source_type for item in evidence})

    return {
        "token_name": token_name,
        "token_symbol": token_symbol,
        "evidence_count": len(evidence),
        "source_types": source_types,
        "verified_evidence": verified,
        "uncertain_evidence": uncertain,
        "primary_source_count": sum(
            item.source_type.lower() == "primary" for item in evidence
        ),
        "status": (
            "evidence_found"
            if evidence
            else "no_evidence"
        ),
    }


def evidence_from_research_results(results: List[Dict]) -> List[Evidence]:
    """Convert normalized provider output into cautious, reviewable evidence."""

    evidence: List[Evidence] = []
    for result in results:
        title = str(result.get("title") or "Untitled source").strip()
        url = str(result.get("url") or "").strip()
        snippet = str(result.get("snippet") or "").strip()

        if not url:
            continue

        evidence.append(
            Evidence(
                claim=title,
                source_url=url,
                source_type=str(result.get("source") or "web_research"),
                published_at=result.get("published_at"),
                author=result.get("author"),
                quote=snippet[:1000] or None,
                relevance="Public research result; requires manual verification",
                confidence=0.55,
            )
        )

    return evidence
