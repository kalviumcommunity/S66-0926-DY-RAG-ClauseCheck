from components.chat import StreamCollector, escape_dollars


def test_every_dollar_sign_is_escaped():
    assert escape_dollars("is $44.10 now, was $42.75") == r"is \$44.10 now, was \$42.75"
    assert escape_dollars("no price here") == "no price here"


def test_stream_shows_escaped_text_but_keeps_the_raw_answer():
    events = [
        ("token", {"text": "is $44.10 "}),
        ("token", {"text": "was $42.75"}),
        ("done", {"outcome": "answered"}),
    ]
    collector = StreamCollector(events)
    assert "".join(collector) == r"is \$44.10 was \$42.75"
    assert collector.message["content"] == "is $44.10 was $42.75"
