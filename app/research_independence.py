import re
from typing import Any, Iterable, Mapping

from app.research_domains import source_domain_family


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _content_signature(item: Any) -> tuple[str, set[str]] | None:
    """Return a conservative signature for a substantive search excerpt."""
    quote = str(_value(item, "quote", "") or "").strip().lower()
    tokens = re.findall(r"[a-z0-9]+", quote)
    if len(tokens) < 8:
        return None
    normalized = " ".join(tokens)
    shingles = {
        " ".join(tokens[index : index + 3])
        for index in range(len(tokens) - 2)
    }
    return normalized, shingles


def _looks_syndicated(
    left: tuple[str, set[str]] | None,
    right: tuple[str, set[str]] | None,
) -> bool:
    if left is None or right is None:
        return False
    left_text, left_shingles = left
    right_text, right_shingles = right
    if left_text == right_text:
        return True
    if len(left_text.split()) < 12 or len(right_text.split()) < 12:
        return False
    union = left_shingles | right_shingles
    if not union:
        return False
    return len(left_shingles & right_shingles) / len(union) >= 0.80


def _representative_rank(item: Any) -> tuple[int, int, float]:
    verification = str(_value(item, "verification_status", "") or "")
    source_type = str(_value(item, "source_type", "") or "")
    try:
        confidence = float(_value(item, "confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return (
        1 if verification == "verified" else 0,
        {
            "primary": 5,
            "onchain_data": 4,
            "primary_candidate": 3,
            "secondary_lead": 2,
            "web_search": 1,
            "social_lead": 0,
        }.get(source_type, 0),
        confidence,
    )


def collapse_syndicated_evidence(evidence: Iterable[Any]) -> tuple[list[Any], dict]:
    """Collapse highly similar excerpts across publisher families.

    This is intentionally conservative. Short or missing snippets are left alone,
    and same-publisher repetition is handled separately by domain-family counting.
    """
    items = list(evidence)
    parents = list(range(len(items)))
    domains = [
        source_domain_family(str(_value(item, "source_url", "") or ""))
        for item in items
    ]
    signatures = [_content_signature(item) for item in items]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(items)):
        if not domains[left] or signatures[left] is None:
            continue
        for right in range(left + 1, len(items)):
            if (
                not domains[right]
                or domains[left] == domains[right]
                or signatures[right] is None
            ):
                continue
            if _looks_syndicated(signatures[left], signatures[right]):
                union(left, right)

    components: dict[int, list[int]] = {}
    for index in range(len(items)):
        components.setdefault(find(index), []).append(index)

    removed = set()
    clusters = []
    for indexes in components.values():
        cluster_domains = sorted({domains[index] for index in indexes if domains[index]})
        if len(cluster_domains) < 2:
            continue
        representative = max(indexes, key=lambda index: _representative_rank(items[index]))
        removed.update(index for index in indexes if index != representative)
        clusters.append(
            {
                "representative_url": str(
                    _value(items[representative], "source_url", "") or ""
                ),
                "domains": cluster_domains,
                "source_count": len(indexes),
                "collapsed_count": len(indexes) - 1,
                "urls": sorted(
                    {
                        str(_value(items[index], "source_url", "") or "")
                        for index in indexes
                        if _value(items[index], "source_url", "")
                    }
                ),
            }
        )

    kept = [item for index, item in enumerate(items) if index not in removed]
    clusters.sort(key=lambda cluster: cluster["representative_url"])
    return kept, {
        "status": "duplicates_found" if clusters else "no_duplicates_detected",
        "raw_evidence_count": len(items),
        "effective_evidence_count": len(kept),
        "cluster_count": len(clusters),
        "collapsed_source_count": len(removed),
        "clusters": clusters,
        "method": (
            "Substantive search excerpts with identical normalized text or at least "
            "80% overlapping three-word sequences across publisher families are "
            "treated as syndicated, not independent confirmation."
        ),
    }
