from app.collectors.web_research import TavilyResearchProvider


def test_live_search():
    provider = TavilyResearchProvider()

    results = provider.search(
        "Bicat Binance Flap crypto",
        limit=5,
    )

    print("\nLIVE RESULTS:")

    for result in results:
        print("\n---")
        print("TITLE:", result.title)
        print("URL:", result.url)
        print("SNIPPET:", result.snippet[:300])

    assert len(results) > 0