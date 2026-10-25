import json

from eval.run_eval import main, write_results


def test_heldout_blocked_without_flag(capsys):
    assert main(["--split", "heldout"]) == 2
    assert "--allow-heldout" in capsys.readouterr().err


def test_unknown_retriever_returns_3(capsys):
    assert main(["--split", "tune", "--stage", "retrieval", "--retriever", "nope"]) == 3


def test_write_results(tmp_path):
    path = write_results({"recall_at_k": 0.9}, "retrieval", "tune", tmp_path, run_date="2026-11-03")
    assert path.name == "2026-11-03_retrieval_tune.json"
    data = json.loads(path.read_text())
    assert data["recall_at_k"] == 0.9 and data["stage"] == "retrieval" and data["split"] == "tune"
