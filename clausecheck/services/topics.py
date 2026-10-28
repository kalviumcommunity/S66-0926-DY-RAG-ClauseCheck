"""Which topic a question is about, by keyword.

The first matching topic wins, so the order matters: a specific topic (service levels) comes before
a general one (price). The keywords were chosen by reading the questions in the query log; a
question that matches none is reported as `Not classified`, never hidden.
"""

NOT_CLASSIFIED = "Not classified"

# (label, keywords). Keywords are matched as lowercase substrings of the question.
TOPICS: list[tuple[str, tuple[str, ...]]] = [
    ("Governing law and disputes", ("governing law", "law governs", "arbitrat", "jurisdiction")),
    ("Insurance", ("insur",)),
    ("Warranty", ("warrant",)),
    (
        "Service levels",
        (
            "uptime",
            "service credit",
            "breakdown",
            "delivery date",
            "liquidated",
            "place a vehicle",
            "transit time",
            "response time",
        ),
    ),
    (
        "Audit and compliance",
        ("audit", "compliance", "certificate", "escrow", "data breach", "iso "),
    ),
    ("Liability", ("liab", "damages", "indemn", "consequential")),
    ("Termination", ("terminat", "end the ", "cure period", "breach", "notice")),
    ("Payment", ("payment", "invoice", "pay ", "net 30", "net 45", "net 60")),
    ("Price", ("price", "rate for", "rate from", " rate ", "fee", "cost", "charge", "$")),
    (
        "Term and renewal",
        ("renew", "initial term", "take effect", "took effect", "expire", "term of"),
    ),
    ("Commitments", ("minimum", "commitment", "capacity", "safety stock", "purchase")),
    ("Parties and definitions", ("parties", "defined", "definition", "who is the")),
]


def classify(question: str) -> str:
    """The topic label for `question`, or `Not classified`."""
    text = f" {(question or '').lower()} "
    for label, keywords in TOPICS:
        if any(k in text for k in keywords):
            return label
    return NOT_CLASSIFIED
