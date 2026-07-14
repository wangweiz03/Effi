from __future__ import annotations

import json

from runtime.branch_policy import (
    _non_debug_scored_rounds_since_best,
    choose_branch_state_for_round,
    choose_branch_for_round,
    round_is_fresh_draft,
)
from runtime.constants import BRANCH_STATE_PLATEAU_NEW_SEED
from runtime.memory_store import init_git_structure
from runtime.portfolio import compact_candidate_ref, update_portfolio
from runtime.text_context import build_v35_context_source_map


def _scored_round(round_num: int, branch: str, score: float, branch_state: str = "") -> dict:
    return {
        "round": round_num,
        "branch": branch,
        "validation": {"score": score, "status": "success"},
        "branch_decision": {"branch": branch, "branch_state": branch_state},
    }


def test_plateau_draft_resets_stagnation_window() -> None:
    rounds = [_scored_round(0, "draft", 0.10)]
    rounds.extend(_scored_round(i, "improve", 0.11 + i / 100) for i in range(1, 5))

    assert _non_debug_scored_rounds_since_best(rounds, 0.10, higher_is_better=False) == 4

    rounds.append(_scored_round(5, "draft", 0.20, BRANCH_STATE_PLATEAU_NEW_SEED))
    assert _non_debug_scored_rounds_since_best(rounds, 0.10, higher_is_better=False) == 0
    assert round_is_fresh_draft(rounds[-1])

    rounds.append(_scored_round(6, "improve", 0.12))
    assert _non_debug_scored_rounds_since_best(rounds, 0.10, higher_is_better=False) == 1


def test_compact_candidate_parent_is_non_recursive() -> None:
    grandparent = {"round": 0, "commit": "root", "score": 0.1}
    parent = {
        "round": 1,
        "commit": "parent",
        "score": 0.09,
        "code_path": "commits/parent/solution.py",
        "anchor_parent": grandparent,
    }
    candidate = {
        "round": 2,
        "commit": "child",
        "score": 0.08,
        "anchor_parent": parent,
        "operator": {},
    }

    compact = compact_candidate_ref(candidate)

    assert compact is not None
    assert compact["parent_binding"]["commit"] == "parent"
    assert "anchor_parent" not in compact["parent_binding"]
    assert compact["parent_binding"]["code_path"] == "commits/parent/solution.py"


def test_current_decision_is_control_snapshot_without_history_log(tmp_path) -> None:
    init_git_structure(tmp_path)

    decision = choose_branch_for_round(
        task_dir=tmp_path,
        round_num=0,
        all_rounds=[],
        higher_is_better=False,
        branch_strategy="portfolio_first",
        warmup_branches=("draft",),
        task_name="unit-task",
    )

    assert decision["branch"] == "draft"
    assert decision["validation_timeout_seconds"] == 10800
    assert decision["external_timeout_plan"] == {
        "schema_version": "external_timeout_plan_v1",
        "validation_timeout_seconds": 10800,
        "remaining_sandbox_runtime_seconds": 43200,
        "runtime_profile": "new_seed_score_first",
        "allocation_basis": "framework_operator_cap",
        "policy": "profile_cap_with_remaining_sandbox",
    }
    assert "runtime_budget_bounds" not in decision
    assert "high_level_memory" in decision["source_policy"]["must"]
    assert "portfolio_state" not in decision
    assert "score_history" not in decision
    assert (tmp_path / "index" / "current_branch_decision.json").exists()
    assert not (tmp_path / "index" / "branch_decisions.jsonl").exists()
    assert not (tmp_path / "graph" / "operator_registry.json").exists()


def test_timeout_recovery_decision_keeps_general_external_timeout(tmp_path) -> None:
    init_git_structure(tmp_path)
    failed_round = {
        "round": 0,
        "branch": "draft",
        "status": "timeout",
        "code": "print('generated solution')",
        "validation": {
            "status": "timeout",
            "score": None,
            "feedback": "Sandbox validation timed out",
        },
    }

    decision = choose_branch_for_round(
        task_dir=tmp_path,
        round_num=1,
        all_rounds=[failed_round],
        higher_is_better=False,
        branch_strategy="portfolio_first",
        warmup_branches=("draft",),
        remaining_budget=20_000,
    )

    assert decision["branch_state"] == "timeout_recovery"
    assert decision["runtime_profile"] == "timeout_recovery"
    assert decision["validation_timeout_seconds"] == 10800
    assert decision["external_timeout_plan"]["validation_timeout_seconds"] == 10800


def test_plateau_scheduler_enforces_reset_cooldown_and_cap(tmp_path) -> None:
    portfolio = {
        "best_candidate": {
            "round": 0,
            "commit": "best",
            "score": 0.10,
            "branch": "draft",
            "method_family": "family_best",
            "commit_paths": {"solution_path": "commits/best/solution.py"},
        },
        "successful_draft_origin_seed_count": 2,
    }
    rounds = [_scored_round(0, "draft", 0.10, "initial_seed")]
    rounds.extend(_scored_round(i, "improve", 0.10 + i / 100) for i in range(1, 5))

    def decide() -> dict:
        return choose_branch_state_for_round(
            task_dir=tmp_path,
            round_num=len(rounds),
            all_rounds=rounds,
            higher_is_better=False,
            elapsed_fraction=0.5,
            remaining_budget=20_000,
            budget_state={},
            portfolio_state=portfolio,
        )

    assert decide()["branch_state"] == BRANCH_STATE_PLATEAU_NEW_SEED

    rounds.append(_scored_round(5, "draft", 0.20, BRANCH_STATE_PLATEAU_NEW_SEED))
    assert decide()["branch"] == "improve"

    rounds.extend(_scored_round(i, "improve", 0.20 + i / 100) for i in range(6, 10))
    assert decide()["branch"] == "improve"

    rounds.append(_scored_round(10, "improve", 0.31))
    assert decide()["branch_state"] == BRANCH_STATE_PLATEAU_NEW_SEED

    rounds.append(_scored_round(11, "draft", 0.32, BRANCH_STATE_PLATEAU_NEW_SEED))
    rounds.extend(_scored_round(i, "improve", 0.32 + i / 100) for i in range(12, 18))
    assert decide()["branch"] == "improve"


def test_portfolio_update_compacts_legacy_recursive_candidates(tmp_path) -> None:
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    recursive_parent = {
        "round": 1,
        "commit": "parent",
        "anchor_parent": {"round": 0, "commit": "grandparent"},
    }
    (graph_dir / "portfolio.json").write_text(
        json.dumps({
            "candidates": [{
                "round": 2,
                "commit": "child",
                "score": 0.1,
                "operator": {},
                "anchor_parent": recursive_parent,
            }],
        }),
        encoding="utf-8",
    )

    update_portfolio(tmp_path, {"validation": {"score": None}}, higher_is_better=False)

    candidate = json.loads((graph_dir / "portfolio.json").read_text(encoding="utf-8"))["candidates"][0]
    assert candidate["parent_binding"]["commit"] == "parent"
    assert "anchor_parent" not in candidate["parent_binding"]


def test_source_map_does_not_expose_mutable_decision_or_legacy_outcomes(tmp_path) -> None:
    init_git_structure(tmp_path)
    source_map, _ = build_v35_context_source_map({
        "task_dir": str(tmp_path),
        "branch": "improve",
        "source_policy": {"must": [], "optional": []},
    })

    assert "current_branch_decision.json" not in source_map
    assert "branch_decision_json" not in source_map
    assert "operator_outcomes.json" not in source_map
