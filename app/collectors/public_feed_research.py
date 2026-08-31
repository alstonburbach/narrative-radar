"""No-key research fallback built from public crypto and ecosystem RSS feeds."""

import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

from app.collectors.research_provider import ResearchProvider, ResearchResult


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str
    source_type: str
    allowed_domains: tuple[str, ...]


DEFAULT_FEEDS = (
    FeedSource(
        "CoinDesk",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "secondary_lead",
        ("coindesk.com",),
    ),
    FeedSource(
        "Cointelegraph",
        "https://cointelegraph.com/rss",
        "secondary_lead",
        ("cointelegraph.com",),
    ),
    FeedSource(
        "Decrypt",
        "https://decrypt.co/feed",
        "secondary_lead",
        ("decrypt.co",),
    ),
    FeedSource(
        "Blockworks",
        "https://blockworks.co/feed",
        "secondary_lead",
        ("blockworks.co", "blockworks.com"),
    ),
    FeedSource(
        "Solana News",
        "https://solana.com/news/rss.xml",
        "primary_candidate",
        ("solana.com",),
    ),
    FeedSource(
        "Solana Changelog",
        "https://solana.com/changelog/rss.xml",
        "primary_candidate",
        ("solana.com",),
    ),
    FeedSource(
        "Ethereum Foundation Blog",
        "https://blog.ethereum.org/feed.xml",
        "primary_candidate",
        ("ethereum.org",),
    ),
)


_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,}")
_GENERIC_QUERY_TERMS = {
    "contract",
    "crypto",
    "cryptocurrency",
    "latest",
    "narrative",
    "narratives",
    "news",
    "public",
    "references",
    "result",
    "results",
    "search",
    "token",
    "tokens",
}
_LENS_TERMS = {
    "adoption",
    "activity",
    "allocation",
    "backers",
    "builders",
    "capital",
    "controversy",
    "credible",
    "credibility",
    "crash",
    "criticism",
    "customers",
    "developers",
    "docs",
    "exploit",
    "failure",
    "fake",
    "fees",
    "financing",
    "funding",
    "fraud",
    "github",
    "grants",
    "hack",
    "halt",
    "holders",
    "insider",
    "integration",
    "integrations",
    "investors",
    "lawsuit",
    "launch",
    "open",
    "partnership",
    "payments",
    "raise",
    "release",
    "roadmap",
    "scam",
    "source",
    "supply",
    "staking",
    "team",
    "treasury",
    "transactions",
    "update",
    "upgrade",
    "unlock",
    "unlocks",
    "usage",
    "users",
    "volume",
    "vulnerability",
    "warning",
    "risk",
    "rug",
    "breach",
    "denied",
    "denies",
    "flaw",
}


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _child_text(element, names: Iterable[str]) -> str:
    wanted = set(names)
    for child in element:
        if _local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


def _entry_link(element) -> str:
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        href = str(child.attrib.get("href") or "").strip()
        if href:
            return href
        if child.text:
            return child.text.strip()
    return ""


def _clean_text(value: str, limit: int = 1_000) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _allowed_article_url(url: str, domains: tuple[str, ...]) -> bool:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _parse_feed(content: bytes, source: FeedSource) -> list[ResearchResult]:
    root = ElementTree.fromstring(content)
    entries = [
        element
        for element in root.iter()
        if _local_name(element.tag) in {"item", "entry"}
    ]
    results = []
    seen_urls = set()
    for entry in entries:
        url = _entry_link(entry)
        if not _allowed_article_url(url, source.allowed_domains) or url in seen_urls:
            continue
        seen_urls.add(url)
        title = _clean_text(_child_text(entry, {"title"}), limit=300)
        snippet = _clean_text(_child_text(entry, {"description", "summary", "content"}))
        published_at = _child_text(
            entry,
            {"pubdate", "published", "updated", "date"},
        )
        results.append(
            ResearchResult(
                title=title,
                url=url,
                snippet=snippet,
                source=f"rss:{source.name}",
                published_at=published_at or None,
                source_type=source.source_type,
            )
        )
    return results


def _query_terms(query: str) -> tuple[set[str], set[str]]:
    normalized = str(query or "").lower()
    tokens = set(_TOKEN_PATTERN.findall(normalized))
    lens_terms = tokens & _LENS_TERMS
    if " contract " in normalized:
        identity_text = normalized.split(" contract ", 1)[0]
        identity_terms = set(_TOKEN_PATTERN.findall(identity_text))
        long_identifiers = {token for token in tokens if len(token) >= 20}
        anchor_terms = (
            identity_terms - _LENS_TERMS - _GENERIC_QUERY_TERMS
        ) | long_identifiers
        return anchor_terms, lens_terms
    anchor_terms = tokens - _LENS_TERMS - _GENERIC_QUERY_TERMS
    return anchor_terms, lens_terms


def _word_forms(value: str) -> set[str]:
    """Return conservative inflection variants for one search token.

    The old prefix matcher treated unrelated words such as ``inside`` and
    ``insider`` as equivalent.  Discovery queries only need small grammatical
    variations (launch/launches, release/released, holder/holders), so keep the
    normalization intentionally narrow.
    """
    word = str(value or "").strip().lower()
    if not word:
        return set()
    forms = {word}
    if len(word) >= 5 and word.endswith("ies"):
        forms.add(f"{word[:-3]}y")
    if len(word) >= 5 and word.endswith("es"):
        forms.add(word[:-2])
        forms.add(word[:-1])
    elif len(word) >= 5 and word.endswith("s"):
        forms.add(word[:-1])
    if len(word) >= 6 and word.endswith("ed"):
        forms.add(word[:-2])
        forms.add(word[:-1])
    if len(word) >= 7 and word.endswith("ing"):
        forms.add(word[:-3])
        forms.add(f"{word[:-3]}e")
    return {item for item in forms if len(item) >= 3}


def _match_count(terms: set[str], values: set[str]) -> int:
    value_forms = {form for value in values for form in _word_forms(value)}
    return sum(bool(_word_forms(term) & value_forms) for term in terms)


def _rank_result(
    result: ResearchResult,
    anchor_terms: set[str],
    lens_terms: set[str],
) -> int | None:
    title_tokens = set(_TOKEN_PATTERN.findall(result.title.lower()))
    body_tokens = set(_TOKEN_PATTERN.findall(result.snippet.lower()))

    anchor_title = _match_count(anchor_terms, title_tokens)
    anchor_body = _match_count(anchor_terms, body_tokens)
    if anchor_terms and not (anchor_title or anchor_body):
        return None
    lens_title = _match_count(lens_terms, title_tokens)
    lens_body = _match_count(lens_terms, body_tokens)
    if lens_terms and not (lens_title or lens_body):
        return None
    return anchor_title * 8 + anchor_body * 4 + lens_title * 3 + lens_body


def _published_datetime(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class PublicFeedResearchProvider(ResearchProvider):
    """Search a bounded cache of recent public-feed entries.

    Feed entries are discovery leads. Even official ecosystem feeds are labeled
    as primary candidates until the source-verification stage checks them.
    """

    provider_name = "public_rss"

    def __init__(
        self,
        session=None,
        feeds: Iterable[FeedSource] | None = None,
        timeout: int = 15,
        max_feed_bytes: int = 5_000_000,
        max_age_days: int | None = 14,
        as_of: datetime | None = None,
    ):
        self.session = session or requests.Session()
        self.feeds = tuple(feeds or DEFAULT_FEEDS)
        self.timeout = max(1, int(timeout))
        self.max_feed_bytes = max(100_000, int(max_feed_bytes))
        self.max_age_days = (
            max(1, int(max_age_days)) if max_age_days is not None else None
        )
        self.as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.warnings: list[str] = []
        self.requested_provider = "public_rss"
        self.deep_research_active = False
        self.fallback_reason: str | None = None
        self._results: list[ResearchResult] | None = None

    def _fetch_source(
        self,
        source: FeedSource,
    ) -> tuple[list[ResearchResult], str | None]:
        try:
            response = self.session.get(
                source.url,
                headers={"User-Agent": "NarrativeRadar/1.0 (+research-only)"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.content
            if len(content) > self.max_feed_bytes:
                raise RuntimeError("feed response exceeded the size limit")
            return _parse_feed(content, source), None
        except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the run
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status else type(exc).__name__
            return [], f"{source.name} feed unavailable ({detail})."

    def _load(self) -> list[ResearchResult]:
        if self._results is not None:
            return self._results
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(self.feeds)))) as pool:
            source_results = list(pool.map(self._fetch_source, self.feeds))

        loaded = []
        failures = 0
        cutoff = (
            self.as_of - timedelta(days=self.max_age_days)
            if self.max_age_days is not None
            else None
        )
        for results, warning in source_results:
            if warning:
                failures += 1
                self.warnings.append(warning)
                continue
            for result in results:
                published = _published_datetime(result.published_at)
                if cutoff is not None and published is not None and published < cutoff:
                    continue
                loaded.append(result)
        if failures == len(self.feeds):
            raise RuntimeError("All configured public research feeds are unavailable.")
        self._results = loaded
        return loaded

    def search(self, query: str, limit: int = 10) -> list[ResearchResult]:
        if not query or not query.strip():
            raise ValueError("query is required")
        requested_limit = max(1, min(int(limit), 20))
        anchor_terms, lens_terms = _query_terms(query)
        ranked = []
        for index, result in enumerate(self._load()):
            score = _rank_result(result, anchor_terms, lens_terms)
            if score is None:
                continue
            ranked.append((score, -index, result))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:requested_limit]]
