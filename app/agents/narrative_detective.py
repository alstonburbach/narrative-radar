from typing import List

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

    return {
        "token_name": token_name,
        "token_symbol": token_symbol,
        "evidence_count": len(evidence),
        "verified_evidence": verified,
        "uncertain_evidence": uncertain,
        "status": (
            "evidence_found"
            if evidence
            else "no_evidence"
        ),
    }