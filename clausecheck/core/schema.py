"""Allowed values and column lists for the corpus manifest and the supplier file."""

import re

MANIFEST_COLUMNS: list[str] = [
    "doc_id",
    "supplier_id",
    "source",
    "doc_type",
    "format",
    "path",
    "title",
    "effective_date",
    "parent_doc_id",
    "licence",
    "url",
    "sha256",
    "is_synthetic",
]
SUPPLIER_COLUMNS: list[str] = ["supplier_id", "display_name", "aliases"]  # aliases joined by "|"
SOURCES: set[str] = {"cuad", "edgar", "vendor", "synthetic"}
DOC_TYPES: set[str] = {"contract", "amendment", "dpa", "sla", "price_schedule", "certificate"}
FORMATS: set[str] = {"pdf", "html", "docx", "txt"}
AMENDMENT_TYPES: set[str] = {"amendment"}  # rows of these types must have parent_doc_id
TARGETS: dict[str, tuple[int, int]] = {  # PRD section 5 ranges (min, max)
    "contract": (58, 200),
    "amendment": (6, 40),
    "price_schedule": (30, 50),
    "compliance": (30, 50),  # dpa + sla + certificate
    "suppliers": (30, 50),
}

_LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "llc",
    "lp",
    "llp",
    "plc",
    "gmbh",
    "sa",
    "ag",
    "nv",
    "bv",
    "the",
}


def normalise_name(name: str) -> str:
    """Return a lowercase company name without punctuation or legal suffixes."""
    words = re.sub(r"[^a-z0-9 ]+", " ", name.lower().replace("&", " and ")).split()
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    if len(words) > 1 and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def supplier_id_from_name(name: str) -> str:
    """Return the `supplier_id` slug for a company name, e.g. `acme-industrial`."""
    return normalise_name(name).replace(" ", "-")
