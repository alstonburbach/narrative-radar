import requests

from app.agents.narrative_detective import results_to_evidence
from app.collectors.public_feed_research import (
    FeedSource,
    PublicFeedResearchProvider,
)
from app.collectors.research_provider import ResearchResult
from app.collectors.web_research import (
    TavilyResearchProvider,
    build_default_research_provider,
)

SECONDARY_FEED = FeedSource(
    "News",
    "https://feed.example/news.xml",
    "secondary_lead",
    ("news.example",),
)
OFFICIAL_FEED = FeedSource(
    "Official",
    "https://feed.example/official.xml",
    "primary_candidate",
    ("official.example",),
)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Solana payment adoption grows</title>
    <link>https://news.example/solana-payments</link>
    <description>New integrations brought more payment users.</description>
    <pubDate>Thu, 27 Aug 2026 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Unrelated market story</title>
    <link>https://news.example/other</link>
    <description>Bitcoin price coverage.</description>
    <pubDate>Thu, 27 Aug 2026 11:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Injected link</title>
    <link>https://attacker.example/not-allowed</link>
    <description>This entry must be discarded.</description>
  </item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Solana developer platform launches</title>
    <link href="https://official.example/platform" />
    <summary>Official builders released new developer tooling.</summary>
    <updated>2026-08-27T10:00:00Z</updated>
  </entry>
</feed>"""


class Response:
    def __init__(self, content=b"", status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class Session:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url]


def test_public_feed_provider_filters_domains_ranks_topic_and_caches_feeds():
    session = Session(
        {
            SECONDARY_FEED.url: Response(RSS),
            OFFICIAL_FEED.url: Response(ATOM),
        }
    )
    provider = PublicFeedResearchProvider(
        session=session,
        feeds=(SECONDARY_FEED, OFFICIAL_FEED),
        max_age_days=None,
    )

    adoption = provider.search(
        "crypto narratives solana integrations launch users",
        limit=5,
    )
    builders = provider.search(
        "crypto narratives solana official developers release",
        limit=5,
    )

    assert {result.url for result in adoption} == {
        "https://news.example/solana-payments",
        "https://official.example/platform",
    }
    assert {result.source_type for result in builders} == {"primary_candidate"}
    assert all("attacker.example" not in result.url for result in adoption)
    assert len(session.calls) == 2
    assert all(call[1]["timeout"] == 15 for call in session.calls)

    unrelated_token = provider.search(
        "UnknownCoin UNK contract 0x1111111111111111111111111111111111111111 "
        "solana crypto token adoption users",
        limit=5,
    )
    assert unrelated_token == []


def test_public_feed_provider_reports_partial_and_total_source_failure_safely():
    partial = PublicFeedResearchProvider(
        session=Session(
            {
                SECONDARY_FEED.url: Response(RSS),
                OFFICIAL_FEED.url: Response(status_code=503),
            }
        ),
        feeds=(SECONDARY_FEED, OFFICIAL_FEED),
        max_age_days=None,
    )

    assert partial.search("solana adoption")
    assert partial.warnings == ["Official feed unavailable (HTTP 503)."]

    failed = PublicFeedResearchProvider(
        session=Session({SECONDARY_FEED.url: Response(status_code=503)}),
        feeds=(SECONDARY_FEED,),
        max_age_days=None,
    )
    try:
        failed.search("solana")
    except RuntimeError as exc:
        assert str(exc) == "All configured public research feeds are unavailable."
    else:
        raise AssertionError("total feed failure should fail closed")


def test_default_provider_uses_public_feeds_without_tavily_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    fallback = build_default_research_provider(session=Session({}))
    tavily = build_default_research_provider(api_key="test-key")

    assert isinstance(fallback, PublicFeedResearchProvider)
    assert isinstance(tavily, TavilyResearchProvider)


def test_feed_source_type_can_never_self_declare_as_verified_primary():
    candidate = ResearchResult(
        title="Official update",
        url="https://official.example/update",
        snippet="An update.",
        source_type="primary_candidate",
    )
    untrusted_primary = ResearchResult(
        title="Claimed primary",
        url="https://unknown.example/update",
        snippet="A claim.",
        source_type="primary",
    )

    evidence = results_to_evidence(
        [candidate, untrusted_primary],
        contract_address="",
        token_name="example",
    )

    assert evidence[0].source_type == "primary_candidate"
    assert evidence[1].source_type == "web_search"
    assert all(
        item.verification_status == "unverified_search_lead" for item in evidence
    )
