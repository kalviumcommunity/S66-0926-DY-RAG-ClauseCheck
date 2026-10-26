from eval.run_eval import ablation_table


def test_ablation_table_sorted_markdown():
    results = {("vector", True): {"recall_at_k": 0.71, "mrr": 0.5},
               ("hybrid_rerank", True): {"recall_at_k": 0.88, "mrr": 0.7}}
    table = ablation_table(results)
    lines = [l for l in table.splitlines() if l.startswith("|")]
    assert "recall@5" in lines[0]
    assert "hybrid_rerank" in lines[2] and "0.880" in lines[2]
