"""Types shared by the retrieval modules."""

from dataclasses import dataclass, field


@dataclass
class SearchHit:
    """One retrieved chunk with its score."""

    chunk_id: str
    score: float
    text: str = ""
    metadata: dict = field(default_factory=dict)  # Chunk fields except text
    source: str = "vector"  # vector | bm25 | hybrid | expansion
    expanded: bool = False
    rerank_score: float | None = None
