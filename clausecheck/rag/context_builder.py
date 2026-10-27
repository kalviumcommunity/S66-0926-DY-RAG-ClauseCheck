from dataclasses import dataclass

from clausecheck.llm.tokens import count_tokens
from clausecheck.rag.types import SearchHit


@dataclass
class Context:
    """Numbered evidence block built from retrieved hits."""

    text: str
    marker_map: dict[str, SearchHit]
    used: list[SearchHit]
    token_count: int


def _source_line(marker: str, hit: SearchHit) -> str:
    meta = hit.metadata or {}
    title = meta.get("title") or meta.get("doc_id") or ""
    page = meta.get("page", "-")
    section = meta.get("section") or "-"
    clause_no = meta.get("clause_no") or "-"
    line = f"[{marker}] {title} | page {page} | section {section} | clause {clause_no}"
    if meta.get("doc_type") == "amendment":
        line += (
            f" | AMENDMENT of {meta.get('parent_doc_id')}, "
            f"effective {meta.get('effective_date')}"
        )
    if meta.get("has_redaction"):
        line += " | contains redacted values"
    return line


def build_context(hits: list[SearchHit], budget_tokens: int) -> Context:
    """Pack hits into a numbered, budget-safe context block."""
    blocks: list[str] = []
    used: list[SearchHit] = []
    marker_map: dict[str, SearchHit] = {}

    for hit in hits:
        marker = f"C{len(used) + 1}"
        block = _source_line(marker, hit)
        if hit.text:
            block = block + "\n" + hit.text

        candidate_blocks = blocks + [block]
        candidate_text = "\n\n".join(candidate_blocks)
        candidate_tokens = count_tokens(candidate_text)

        if not used or candidate_tokens <= budget_tokens:
            blocks.append(block)
            used.append(hit)
            marker_map[marker] = hit
        # otherwise skip and keep trying later, smaller blocks

    text = "\n\n".join(blocks)
    return Context(text=text, marker_map=marker_map, used=used, token_count=count_tokens(text))
