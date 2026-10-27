# scripts/manual_pr10_fake.py
from clausecheck.rag.context_builder import build_context
from clausecheck.rag.relevance_gate import check
from clausecheck.rag.types import SearchHit
from clausecheck.llm.tokens import count_tokens

# 1) Normal hits
hits = [
    SearchHit("c1", 1.0, "Payment is due Net 45 days.",
              {"doc_id": "doc-1", "page": 1, "section": "2. Payment", "clause_no": "2.1",
               "doc_type": "contract", "has_redaction": False}),
    SearchHit("c2", 0.9, "Late payments incur 1.5% monthly interest.",
              {"doc_id": "doc-1", "page": 2, "section": "2. Payment", "clause_no": "2.2",
               "doc_type": "contract", "has_redaction": False}),
    SearchHit("c3", 0.8, "Term renews automatically for 12 months.",
              {"doc_id": "doc-2", "page": 5, "section": "5. Renewal", "clause_no": "5.1",
               "doc_type": "amendment", "parent_doc_id": "doc-1", "effective_date": "2020-03-01",
               "has_redaction": True}),
]

ctx = build_context(hits, budget_tokens=3000)
print("=== ctx.text ===")
print(ctx.text)
print("\nmarkers:", list(ctx.marker_map))
print("used:", [h.chunk_id for h in ctx.used])
print("token_count:", ctx.token_count, "<= 3000:", ctx.token_count <= 3000)

# 2) Budget: first block kept even if huge; smaller later block still included
big = "word " * 400
hits2 = [
    SearchHit("c1", 1.0, big, {"doc_id": "d1", "page": 1, "section": "s", "clause_no": "1",
                               "doc_type": "contract", "has_redaction": False}),
    SearchHit("c2", 1.0, big, {"doc_id": "d2", "page": 2, "section": "s", "clause_no": "2",
                               "doc_type": "contract", "has_redaction": False}),
    SearchHit("c3", 1.0, "short", {"doc_id": "d3", "page": 3, "section": "s", "clause_no": "3",
                                   "doc_type": "contract", "has_redaction": False}),
]
ctx2 = build_context(hits2, budget_tokens=500)
print("\n=== budget test ===")
print("used:", [h.chunk_id for h in ctx2.used])   # expect ['c1', 'c3']
print("word count in ctx2:", ctx2.text.count("word"))  # expect 400

# 3) Gate scores
print("\n=== gate ===")
print("no hits:", check([], 0.5).reason)
h = [SearchHit("a", 0.9, "t", rerank_score=0.2)]
print("low score:", check(h, 0.5).passed, check(h, 0.5).reason, check(h, 0.5).top_score)
print("high score:", check(h, 0.1).passed)
h2 = [SearchHit("x", 0.0, "t", expanded=True), SearchHit("a", 0.7, "t")]
g = check(h2, 0.5)
print("fallback/skip-expanded:", g.passed, g.top_score)
r = check([SearchHit("a", 1.0, "t")], 0.1, supplier_required=True, supplier_id=None)
print("unknown supplier:", (r.passed, r.reason))
