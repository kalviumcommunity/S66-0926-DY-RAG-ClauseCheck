from clausecheck.llm.tokens import count_tokens, decode, encode


def test_count_tokens():
    assert count_tokens("") == 0
    assert count_tokens("Payment is due Net 45 days.") > 3


def test_encode_decode_roundtrip():
    text = "Section 4.2: Supplier shall invoice monthly."
    assert decode(encode(text)) == text
