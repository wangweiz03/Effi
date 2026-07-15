from __future__ import annotations

import json

import pytest

import runtime.branch_policy as branch_policy
from runtime.branch_policy import (
    _non_debug_scored_rounds_since_best,
    choose_branch_state_for_round,
    choose_branch_for_round,
    round_is_fresh_draft,
)
from runtime.constants import (
    BRANCH_STATE_INITIAL_SEED,
    BRANCH_STATE_PLATEAU_NEW_SEED,
    BRANCH_STATE_REQUIRED_SEED,
)
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


def _runtime_round(
    round_num: int,
    branch: str,
    *,
    status: str,
    score: float | None,
    run_time: float,
    timeout: int,
    round_wall_time: float,
) -> dict:
    return {
        "round": round_num,
        "commit": f"runtime{round_num}",
        "branch": branch,
        "status": status,
        "score": score,
        "round_wall_time": round_wall_time,
        "validation_timeout_seconds": timeout,
        "validation": {
            "status": status,
            "score": score,
            "run_time": run_time,
            "timeout": timeout,
        },
        "branch_decision": {
            "branch": branch,
            "branch_state": "required_seed" if branch == "draft" else "frontier_improve",
            "validation_timeout_seconds": timeout,
        },
    }


def _force_branch_state(monkeypatch, *, branch: str, state: str, parent_binding: dict | None = None) -> None:
    monkeypatch.setattr(
        branch_policy,
        "choose_branch_state_for_round",
        lambda **_kwargs: {
            "branch": branch,
            "branch_state": state,
            "branch_reason": "unit_test_forced_state",
            "runtime_profile": "new_seed_score_first" if branch == "draft" else "standard",
            "eda_mode": "none",
            "parent_binding": parent_binding or {"role": "none"},
            "best_candidate": None,
            "diagnostics": {},
            "deep_eda_advice": "",
        },
    )


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
    assert "eda_findings" in decision["source_policy"]["must"]
    assert "eda_summary" not in decision["source_policy"]["must"]
    assert "portfolio_state" not in decision
    assert "score_history" not in decision
    assert (tmp_path / "index" / "current_branch_decision.json").exists()
    assert not (tmp_path / "index" / "branch_decisions.jsonl").exists()
    assert not (tmp_path / "graph" / "operator_registry.json").exists()


@pytest.mark.parametrize(
    "branch_state",
    (BRANCH_STATE_INITIAL_SEED, BRANCH_STATE_REQUIRED_SEED, BRANCH_STATE_PLATEAU_NEW_SEED),
)
def test_every_draft_state_gets_one_hour_workload_ceiling_without_shrinking_external_cap(
    tmp_path,
    monkeypatch,
    branch_state: str,
) -> None:
    init_git_structure(tmp_path)
    _force_branch_state(monkeypatch, branch="draft", state=branch_state)
    prior = _runtime_round(
        2,
        "draft",
        status="success",
        score=0.7,
        run_time=1234.5,
        timeout=10800,
        round_wall_time=9999.0,
    )
    rounds = [] if branch_state == BRANCH_STATE_INITIAL_SEED else [prior]

    decision = choose_branch_for_round(
        task_dir=tmp_path,
        round_num=0 if not rounds else 3,
        all_rounds=rounds,
        higher_is_better=True,
        branch_strategy="portfolio_first",
        warmup_branches=("draft",),
        remaining_budget=20_000,
    )

    plan = decision["workload_plan"]
    assert plan["schema_version"] == "workload_plan_v1"
    assert plan["draft_workload_ceiling_seconds"] == 3600
    assert plan["policy"] == "earliest_strong_complete_route"
    assert plan["ceiling_is_consumption_target"] is False
    assert plan["expansion_requires_evidence"] is True
    assert plan["solution_deadline_allowed"] is False
    assert decision["validation_timeout_seconds"] == 10800
    assert decision["external_timeout_plan"]["validation_timeout_seconds"] == 10800


def test_draft_workload_reference_uses_latest_prior_draft_validation_runtime_not_round_wall(
    tmp_path,
    monkeypatch,
) -> None:
    init_git_structure(tmp_path)
    _force_branch_state(monkeypatch, branch="draft", state=BRANCH_STATE_REQUIRED_SEED)
    rounds = [
        _runtime_round(
            0,
            "draft",
            status="success",
            score=0.9,
            run_time=111.0,
            timeout=10800,
            round_wall_time=8000.0,
        ),
        _runtime_round(
            1,
            "improve",
            status="success",
            score=0.95,
            run_time=222.0,
            timeout=10800,
            round_wall_time=8500.0,
        ),
        _runtime_round(
            2,
            "draft",
            status="timeout",
            score=None,
            run_time=10795.0,
            timeout=10800,
            round_wall_time=20_000.0,
        ),
    ]

    decision = choose_branch_for_round(
        task_dir=tmp_path,
        round_num=3,
        all_rounds=rounds,
        higher_is_better=True,
        branch_strategy="portfolio_first",
        warmup_branches=("draft",),
        remaining_budget=20_000,
    )

    plan = decision["workload_plan"]
    assert plan["reference_round"] == 2
    assert plan["reference_branch"] == "draft"
    assert plan["reference_status"] == "timeout"
    assert plan["previous_validation_runtime_seconds"] == 10795.0
    assert plan["previous_validation_runtime_seconds"] != 20_000.0
    assert plan["previous_validation_timeout_seconds"] == 10800
    assert plan["previous_timeout_saturation"] == pytest.approx(10795.0 / 10800.0)
    assert plan["previous_timed_out"] is True


def test_draft_workload_ceiling_is_clamped_by_remaining_sandbox_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    init_git_structure(tmp_path)
    _force_branch_state(monkeypatch, branch="draft", state=BRANCH_STATE_REQUIRED_SEED)

    decision = choose_branch_for_round(
        task_dir=tmp_path,
        round_num=1,
        all_rounds=[],
        higher_is_better=True,
        branch_strategy="portfolio_first",
        warmup_branches=("draft",),
        remaining_budget=2400,
    )

    assert decision["validation_timeout_seconds"] == 2400
    assert decision["workload_plan"]["draft_workload_ceiling_seconds"] == 2400


def test_draft_runtime_reference_skips_newer_draft_without_validation_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    init_git_structure(tmp_path)
    _force_branch_state(monkeypatch, branch="draft", state=BRANCH_STATE_REQUIRED_SEED)
    valid = _runtime_round(
        0,
        "draft",
        status="success",
        score=0.7,
        run_time=345.0,
        timeout=10800,
        round_wall_time=9000.0,
    )
    missing_runtime = {
        "round": 2,
        "commit": "runtime2",
        "branch": "draft",
        "status": "code_execution_error",
        "round_wall_time": 9999.0,
        "validation": {"status": "code_execution_error", "timeout": 10800},
    }

    decision = choose_branch_for_round(
        task_dir=tmp_path,
        round_num=3,
        all_rounds=[valid, missing_runtime],
        higher_is_better=True,
        branch_strategy="portfolio_first",
        warmup_branches=("draft",),
        remaining_budget=20_000,
    )

    plan = decision["workload_plan"]
    assert plan["reference_round"] == 0
    assert plan["previous_validation_runtime_seconds"] == 345.0
    assert plan["previous_validation_runtime_seconds"] != 9999.0


@pytest.mark.parametrize(
    ("branch", "branch_state", "status", "timed_out"),
    (
        ("debug", "repair_failure", "timeout", True),
        ("improve", "frontier_improve", "success", False),
    ),
)
def test_non_draft_workload_plan_has_no_ceiling_and_uses_bound_parent_runtime_evidence(
    tmp_path,
    monkeypatch,
    branch: str,
    branch_state: str,
    status: str,
    timed_out: bool,
) -> None:
    init_git_structure(tmp_path)
    parent_binding = {
        "role": "debug_parent" if branch == "debug" else "validation_best",
        "round": 2,
        "commit": "runtime2",
        "status": status,
        "score": None if timed_out else 0.8,
        "code_path": "commits/runtime2/solution.py",
    }
    _force_branch_state(
        monkeypatch,
        branch=branch,
        state=branch_state,
        parent_binding=parent_binding,
    )
    rounds = [
        _runtime_round(
            2,
            "draft",
            status=status,
            score=None if timed_out else 0.8,
            run_time=321.0,
            timeout=10800,
            round_wall_time=9999.0,
        )
    ]

    decision = choose_branch_for_round(
        task_dir=tmp_path,
        round_num=3,
        all_rounds=rounds,
        higher_is_better=True,
        branch_strategy="portfolio_first",
        warmup_branches=("draft",),
        remaining_budget=20_000,
    )

    plan = decision["workload_plan"]
    assert plan["draft_workload_ceiling_seconds"] is None
    assert plan["reference_round"] == 2
    assert plan["reference_branch"] == "draft"
    assert plan["reference_status"] == status
    assert plan["previous_validation_runtime_seconds"] == 321.0
    assert plan["previous_validation_runtime_seconds"] != 9999.0
    assert plan["previous_validation_timeout_seconds"] == 10800
    assert plan["previous_timed_out"] is timed_out
    assert decision["validation_timeout_seconds"] == 10800


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
