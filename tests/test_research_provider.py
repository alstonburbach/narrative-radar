from app.collectors.research_provider import ResearchResult


def test_research_result():
    result = ResearchResult(
        title="Example post",
        url="https://example.com/post",
        snippet="An example research result.",
        source="example",
    )

    assert result.title == "Example post"
    assert result.url == "https://example.com/post"
    assert result.source == "example"