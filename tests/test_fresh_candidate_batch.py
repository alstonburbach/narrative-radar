from app.fresh_candidate_batch_main import RotatingBatchProvider


class FakeCollector:
    def collect(self, **kwargs):
        return {
            "status": "ok",
            "candidates": [
                {"contract_address": f"token-{i}", "venue": "pump_fun", "chain": "solana"}
                for i in range(12)
            ],
        }


def test_fresh_batch_selects_next_slice_without_shuffle():
    provider = RotatingBatchProvider(batch_index=1, batch_size=5)
    provider.inner = FakeCollector()
    report = provider.collect(venues=("pump_fun",), profile_limit_per_venue=5, candidate_limit=5)
    assert [row["contract_address"] for row in report["candidates"]] == [
        "token-5", "token-6", "token-7", "token-8", "token-9"
    ]
    assert report["selection"]["wrapped_to_first_batch"] is False


def test_fresh_batch_wraps_only_when_requested_page_is_empty():
    provider = RotatingBatchProvider(batch_index=3, batch_size=5)
    provider.inner = FakeCollector()
    report = provider.collect(venues=("pump_fun",), profile_limit_per_venue=5, candidate_limit=5)
    assert [row["contract_address"] for row in report["candidates"]] == [
        "token-0", "token-1", "token-2", "token-3", "token-4"
    ]
    assert report["selection"]["wrapped_to_first_batch"] is True
