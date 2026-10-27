from components.insights import KPI_LABELS, format_kpi


def test_format_kpi():
    assert format_kpi("answer_rate", 0.8666) == "87%"
    assert format_kpi("citation_accuracy", None) == "—"
    assert format_kpi("median_ttft_ms", 1234.0) == "1.2 s"
    assert format_kpi("median_ttft_ms", 850.0) == "850 ms"
    assert format_kpi("questions_asked", 1234) == "1,234"


def test_five_kpi_cards():
    assert list(KPI_LABELS) == ["questions_asked", "answer_rate", "median_time_to_checked_answer_ms",
                                "median_ttft_ms", "citation_accuracy"]
