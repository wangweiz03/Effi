from __future__ import annotations

import json

from runtime.search_graph import _medal_for_score, build_search_graph_state


def test_medal_for_score_respects_metric_direction() -> None:
    lower = {"gold": 0.0, "silver": 0.00791, "bronze": 0.01526}
    higher = {"gold": 0.930508, "silver": 0.919654, "bronze": 0.914492}

    assert _medal_for_score(0.00747, lower, higher_is_better=False) == "silver"
    assert _medal_for_score(0.02, lower, higher_is_better=False) == "none"
    assert _medal_for_score(0.925, higher, higher_is_better=True) == "silver"
    assert _medal_for_score(None, higher, higher_is_better=True) is None


def test_rounds_summary_overrides_stale_graph_and_card_status(tmp_path) -> None:
    graph_dir = tmp_path / "graph"
    memory_dir = tmp_path / "memory_bank"
    graph_dir.mkdir()
    memory_dir.mkdir()
    (graph_dir / "nodes.jsonl").write_text(
        json.dumps({
            "round": 0,
            "node_id": "abc12345",
            "commit": "abc12345",
            "branch": "draft",
            "validation": {"status": "unknown", "score": None},
        }) + "\n",
        encoding="utf-8",
    )
    (memory_dir / "card_index.jsonl").write_text(
        json.dumps({
            "round": 0,
            "commit": "abc12345",
            "branch": "draft",
            "status": "unknown",
            "score": None,
        }) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "rounds_summary.json").write_text(
        json.dumps({
            "rounds": [{
                "round": 0,
                "task_name": "unit-task",
                "commit_hash": "abc12345",
                "branch": "draft",
                "status": "success",
                "score": 0.75,
                "validation": {
                    "status": "success",
                    "score": 0.75,
                    "raw_score": 0.75,
                    "run_time": 12.0,
                    "failure_taxonomy": {"primary": "none"},
                },
                "submit": {
                    "status": "success",
                    "score": 0.7,
                    "run_time": 20.0,
                },
            }],
        }),
        encoding="utf-8",
    )

    state = build_search_graph_state(tmp_path, higher_is_better=True)

    assert state["nodes"][0]["status"] == "success"
    assert state["nodes"][0]["score"] == 0.75
    assert state["nodes"][0]["submit_score"] == 0.7
    assert state["stats"]["best_round"] == 0
    assert state["stats"]["submitted_count"] == 1
    assert state["stats"]["best_submit_score"] == 0.7
    assert state["stats"]["best_submit_medal"] is None
