import pytest

from clausecheck.services.topics import NOT_CLASSIFIED, classify


@pytest.mark.parametrize(
    "question, topic",
    [
        ("What are the payment terms with Orion?", "Payment"),
        ("What is Orion's rate for a 16 MT truck from Surat to Mumbai?", "Price"),
        ("What is the monthly fee for the production environment?", "Price"),
        ("What service credit do we get if uptime is 99.2%?", "Service levels"),
        ("How fast must Sapphire attend a lift breakdown?", "Service levels"),
        ("What insurance must Northstar carry?", "Insurance"),
        ("How long is the warranty on the forgings?", "Warranty"),
        (
            "Which law governs the agreement and where are disputes arbitrated?",
            "Governing law and disputes",
        ),
        ("Within what time must Helixa report a data breach?", "Audit and compliance"),
        ("Does the BSP have audit rights over Datec's records?", "Audit and compliance"),
        ("Is Sicap liable for consequential loss?", "Liability"),
        ("Can we end the agreement without cause, and what notice?", "Termination"),
        ("Does the agreement renew automatically?", "Term and renewal"),
        ("Is there a minimum annual purchase commitment?", "Commitments"),
        ("Who are the parties to the supply agreement?", "Parties and definitions"),
    ],
)
def test_questions_land_in_the_topic_a_buyer_would_expect(question, topic):
    assert classify(question) == topic


def test_a_question_that_matches_nothing_is_reported_as_not_classified():
    assert classify("What is the capital of France?") == NOT_CLASSIFIED
    assert classify("And to Pune?") == NOT_CLASSIFIED
    assert classify("") == classify(None) == NOT_CLASSIFIED


def test_the_more_specific_topic_wins():
    # "service credit" is a service level even though it mentions a fee-like word
    assert classify("What service credit is owed on the monthly fee?") == "Service levels"
