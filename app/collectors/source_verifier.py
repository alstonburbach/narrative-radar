import ipaddress
import re
from dataclasses import replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

import requests

from app.database.models import Evidence


CHECKABLE_SOURCE_TYPES = {"primary_candidate", "onchain_data", "secondary_lead"}
DEFAULT_MAX_BYTES = 1_000_000


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "template"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def html_to_text(content: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(content)
        parser.close()
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", content)
    return " ".join(text.split())


def _safe_public_url(url: str) -> None:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source URL must be a public http or https URL")
    hostname = parsed.hostname.strip("[]")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    ):
        raise ValueError("private or local source URLs are not allowed")


class PublicSourceFetcher:
    """Fetch small public pages for evidence verification without executing them."""

    def __init__(
        self,
        timeout: int = 15,
        max_bytes: int = DEFAULT_MAX_BYTES,
        session: Any = None,
    ):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.session = session or requests

    def fetch(self, url: str) -> dict:
        _safe_public_url(url)
        response = self.session.get(
            url,
            headers={"User-Agent": "NarrativeRadar/1.0 research-only"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        content = getattr(response, "content", None)
        if content is not None:
            if isinstance(content, bytes):
                content = content[: self.max_bytes].decode("utf-8", errors="replace")
            else:
                content = str(content)[: self.max_bytes]
        else:
            content = str(getattr(response, "text", ""))[: self.max_bytes]
        return {
            "url": url,
            "text": html_to_text(content),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "status_code": getattr(response, "status_code", None),
        }


def _field(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _quote_for_match(text: str, term: str, width: int = 260) -> Optional[str]:
    lowered = text.casefold()
    index = lowered.find(term.casefold())
    if index < 0:
        return None
    start = max(0, index - width // 2)
    end = min(len(text), index + len(term) + width // 2)
    return text[start:end].strip()


def _identity_matches(text: str, identity_terms: Iterable[str]) -> list[str]:
    lowered = text.casefold()
    matches = []
    for raw_term in identity_terms:
        term = " ".join(str(raw_term).split()).strip()
        if not term:
            continue
        normalized = term.casefold()
        if len(normalized) >= 6 and normalized in lowered:
            matches.append(term)
            continue
        tokens = [token for token in re.findall(r"[a-z0-9]{3,}", normalized)]
        if len(tokens) >= 2 and all(token in lowered for token in tokens):
            matches.append(term)
    return matches


def verify_source_leads(
    evidence: Iterable[Evidence],
    identity_terms: Iterable[str],
    fetcher: Optional[Any] = None,
    max_sources: int = 8,
) -> tuple[list[Evidence], dict]:
    """Fetch high-value leads and verify identity presence without endorsing claims."""
    items = list(evidence)
    fetcher = fetcher or PublicSourceFetcher()
    terms = [str(term).strip() for term in identity_terms if str(term).strip()]
    checked = 0
    content_matches = 0
    no_identity_match = 0
    fetch_failures = 0
    skipped = 0
    errors = []
    checked_urls = []
    seen_domains = set()
    output = []

    for item in items:
        source_type = _field(item, "source_type")
        url = str(_field(item, "source_url", "")).strip()
        domain = (urlparse(url).hostname or "").lower().removeprefix("www.")
        eligible = source_type in CHECKABLE_SOURCE_TYPES and domain not in seen_domains
        if not eligible or checked >= max(1, int(max_sources)):
            skipped += 1
            output.append(item)
            continue

        seen_domains.add(domain)
        checked += 1
        checked_urls.append(url)
        try:
            document = fetcher.fetch(url)
            text = str(document.get("text", ""))
            matches = _identity_matches(text, terms)
            retrieved_at = document.get("retrieved_at") or datetime.now(timezone.utc).isoformat()
            if matches:
                content_matches += 1
                quote = _quote_for_match(text, matches[0])
                relevance = _field(item, "relevance") or ""
                relevance = f"{relevance}; fetched page contains identity: {', '.join(matches)}".strip("; ")
                output.append(
                    replace(
                        item,
                        quote=quote or _field(item, "quote"),
                        relevance=relevance,
                        confidence=max(float(_field(item, "confidence", 0.0) or 0.0), 0.70),
                        claim_type="observed_identity_match",
                        verification_status="content_match",
                        retrieved_at=retrieved_at,
                    )
                )
            else:
                no_identity_match += 1
                output.append(
                    replace(
                        item,
                        relevance="Fetched page did not contain the supplied project identity.",
                        confidence=min(float(_field(item, "confidence", 0.0) or 0.0), 0.15),
                        verification_status="no_identity_match",
                        retrieved_at=retrieved_at,
                    )
                )
        except Exception as exc:
            fetch_failures += 1
            errors.append(f"{url}: {exc}")
            output.append(replace(item, verification_status="fetch_failed"))

    return output, {
        "status": "complete" if not errors else "partial",
        "checked": checked,
        "content_matches": content_matches,
        "no_identity_match": no_identity_match,
        "fetch_failures": fetch_failures,
        "skipped": skipped,
        "checked_urls": checked_urls,
        "errors": errors,
        "note": (
            "Content matches show that a page contains the identity; they do not prove "
            "the page is official or that its claims are true."
        ),
    }
