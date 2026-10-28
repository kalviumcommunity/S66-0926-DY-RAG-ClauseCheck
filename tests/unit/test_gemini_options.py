from clausecheck.llm.gemini import GeminiProvider


def test_temperature_goes_into_config_not_kwargs():
    options = GeminiProvider._options({"temperature": 0.0})
    assert "temperature" not in options
    assert options["config"].temperature == 0.0


def test_no_temperature_leaves_options_alone():
    assert GeminiProvider._options({}) == {}
