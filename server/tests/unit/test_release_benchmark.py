from dokura.release_benchmark import percentile, resource_summary


def test_percentile_uses_nearest_rank() -> None:
    assert percentile(list(range(1, 101))) == 95
    assert percentile([7]) == 7


def test_resource_summary_compares_stable_windows() -> None:
    samples = [
        {"rss_kib": rss, "threads": 4, "file_descriptors": 12, "timestamp_ns": index}
        for index, rss in enumerate([1000] * 10 + [1050] * 10)
    ]
    result = resource_summary(samples, duration=1_200)
    assert result["rss_growth_percent"] == 5
    assert result["threads_min"] == result["threads_max"] == 4
