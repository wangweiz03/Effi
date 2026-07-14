from __future__ import annotations

import json

from runtime.branch_policy import _frozen_draft_prior_memory, choose_branch_for_round
from runtime.memory_store import init_git_structure
from runtime.skills import prefill_active_solution_from_incumbent


def _write_solution(task_dir, commit: str, code: str) -> None:
    commit_dir = task_dir / "commits" / commit
    commit_dir.mkdir(parents=True, exist_ok=True)
    (commit_dir / "solution.py").write_text(code, encoding="utf-8")
    (commit_dir / "validation_feedback.txt").write_text("feedback", encoding="utf-8")


def _choose(task_dir, round_num: int, rounds: list[dict], *, higher_is_better: bool = False) -> dict:
    return choose_branch_for_round(
        task_dir=task_dir,
        round_num=round_num,
        all_rounds=rounds,
        higher_is_better=higher_is_better,
        branch_strategy="portfolio_first",
        warmup_branches=("draft",),
        task_name="unit-task",
        elapsed_fraction=0.2,
        remaining_budget=20_000,
    )


def test_draft_decision_has_no_parent_and_never_prefills(tmp_path) -> None:
    init_git_structure(tmp_path)
    decision = _choose(tmp_path, 0, [])

    assert decision["schema_version"] == "branch_decision_v3"
    assert decision["branch"] == "draft"
    assert decision["parent_binding"] == {"role": "none"}
    assert "anchor_parent" not in decision
    assert "debug_parent" not in decision
    assert "search_operator" not in decision
    assert "search_intent" not in decision

    active = tmp_path / "solution.py"
    info = prefill_active_solution_from_incumbent(tmp_path, active, decision)
    assert not info["enabled"]
    assert info["reason"] == "draft_branch_has_no_parent"
    assert not active.exists()


def test_later_draft_freezes_prior_draft_card_summary(tmp_path) -> None:
    init_git_structure(tmp_path)
    card_path = tmp_path / "memory_bank" / "cards" / "round_000_draft000.md"
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(
        "## Method Portrait\n- method_summary: A bounded categorical boosting ensemble.\n",
        encoding="utf-8",
    )
    (tmp_path / "memory_bank" / "card_index.jsonl").write_text(
        json.dumps({
            "round": 0,
            "branch": "draft",
            "status": "success",
            "score": 0.4,
            "method_family": "tabular_gbdt",
            "card_path": "memory_bank/cards/round_000_draft000.md",
        }) + "\n",
        encoding="utf-8",
    )
    rounds = [{
        "round": 0,
        "branch": "draft",
        "commit_hash": "draft000",
        "effective_method_family": "tabular_gbdt",
        "round_summary": {"core_components": ["categorical encoding", "bounded ensemble"]},
        "validation": {"status": "success", "score": 0.4},
    }]

    decision = _choose(tmp_path, 1, rounds)

    assert decision["branch"] == "draft"
    assert decision["parent_binding"] == {"role": "none"}
    prior = decision["draft_prior_memory"]
    assert prior["schema_version"] == "draft_prior_memory_v2"
    assert prior["evidence_cutoff_round"] == 0
    assert prior["cards"] == [{
        "round": 0,
        "score": 0.4,
        "method_summary": "A bounded categorical boosting ensemble.",
        "card_path": "memory_bank/cards/round_000_draft000.md",
    }]


def test_frozen_draft_memory_is_bounded_and_has_no_legacy_display_fields(tmp_path) -> None:
    cards_dir = tmp_path / "memory_bank" / "cards"
    cards_dir.mkdir(parents=True)
    index_rows = []
    rounds = []
    for round_num in range(7):
        card_rel = f"memory_bank/cards/round_{round_num:03d}.md"
        (tmp_path / card_rel).write_text(
            f"## Method Portrait\n- method_summary: Draft method portrait {round_num}.\n",
            encoding="utf-8",
        )
        index_rows.append({
            "round": round_num,
            "branch": "draft",
            "status": "success",
            "score": round_num / 10,
            "method_family": f"family_{round_num % 3}",
            "card_path": card_rel,
        })
        rounds.append({
            "round": round_num,
            "branch": "draft",
            "validation": {"status": "success", "score": round_num / 10},
            "memory_card_path": card_rel,
        })
    (tmp_path / "memory_bank" / "card_index.jsonl").write_text(
        "\n".join(json.dumps(row) for row in index_rows) + "\n",
        encoding="utf-8",
    )

    prior = _frozen_draft_prior_memory(tmp_path, rounds, higher_is_better=True)

    assert prior["schema_version"] == "draft_prior_memory_v2"
    assert len(prior["cards"]) == 4
    assert prior["omitted_count"] == 3
    for card in prior["cards"]:
        assert set(card) == {"round", "score", "method_summary", "card_path"}
        assert card["method_summary"].startswith("Draft method portrait ")


def test_debug_binds_and_prefills_the_failed_round(tmp_path) -> None:
    init_git_structure(tmp_path)
    _write_solution(tmp_path, "failed123", "FAILED_PARENT = True\n")
    rounds = [{
        "round": 3,
        "branch": "improve",
        "commit_hash": "failed123",
        "code": "FAILED_PARENT = True\n",
        "effective_method_family": "xgboost",
        "validation": {
            "status": "timeout",
            "score": None,
            "failure_taxonomy": {"primary": "timeout"},
        },
    }]

    decision = _choose(tmp_path, 4, rounds)

    assert decision["branch"] == "debug"
    assert decision["parent_binding"]["role"] == "debug_parent"
    assert decision["parent_binding"]["round"] == 3
    assert decision["parent_binding"]["commit"] == "failed123"
    assert decision["parent_binding"]["failure_primary"] == "timeout"

    active = tmp_path / "solution.py"
    info = prefill_active_solution_from_incumbent(tmp_path, active, decision)
    assert info["enabled"]
    assert info["parent_role"] == "debug_parent"
    assert active.read_text(encoding="utf-8") == "FAILED_PARENT = True\n"


def test_improve_uses_current_eligible_best_not_stale_vault(tmp_path) -> None:
    init_git_structure(tmp_path)
    _write_solution(tmp_path, "stale000", "SOURCE = 'stale-vault'\n")
    _write_solution(tmp_path, "best1111", "SOURCE = 'eligible-best'\n")
    _write_solution(tmp_path, "blocked2", "SOURCE = 'blocked-better-score'\n")
    (tmp_path / "index" / "best_validation_candidate.json").write_text(
        json.dumps({
            "round": 0,
            "commit_hash": "stale000",
            "validation_score": 0.5,
            "code_path": "commits/stale000/solution.py",
        }),
        encoding="utf-8",
    )
    rounds = [
        {
            "round": 0,
            "branch": "draft",
            "commit_hash": "stale000",
            "code": "SOURCE = 'stale-vault'\n",
            "effective_method_family": "xgboost",
            "validation": {"status": "success", "score": 0.5},
        },
        {
            "round": 1,
            "branch": "draft",
            "commit_hash": "best1111",
            "code": "SOURCE = 'eligible-best'\n",
            "effective_method_family": "cnn_image",
            "validation": {"status": "success", "score": 0.1},
        },
        {
            "round": 2,
            "branch": "improve",
            "commit_hash": "blocked2",
            "code": "SOURCE = 'blocked-better-score'\n",
            "effective_method_family": "lightgbm",
            "solution_contract": {"submission_eligible": False},
            "validation": {"status": "success", "score": 0.01},
        },
    ]

    decision = _choose(tmp_path, 3, rounds)

    assert decision["branch"] == "improve"
    assert decision["parent_binding"]["role"] == "validation_best"
    assert decision["parent_binding"]["commit"] == "best1111"
    assert decision["parent_binding"]["score"] == 0.1

    active = tmp_path / "solution.py"
    info = prefill_active_solution_from_incumbent(tmp_path, active, decision)
    assert info["enabled"]
    assert info["source_path"].endswith("commits/best1111/solution.py")
    assert active.read_text(encoding="utf-8") == "SOURCE = 'eligible-best'\n"


def test_improve_parent_selection_respects_higher_is_better(tmp_path) -> None:
    init_git_structure(tmp_path)
    _write_solution(tmp_path, "lower000", "SOURCE = 'lower'\n")
    _write_solution(tmp_path, "higher11", "SOURCE = 'higher'\n")
    rounds = [
        {
            "round": 0,
            "branch": "draft",
            "commit_hash": "lower000",
            "code": "SOURCE = 'lower'\n",
            "effective_method_family": "xgboost",
            "validation": {"status": "success", "score": 0.2},
        },
        {
            "round": 1,
            "branch": "draft",
            "commit_hash": "higher11",
            "code": "SOURCE = 'higher'\n",
            "effective_method_family": "cnn_image",
            "validation": {"status": "success", "score": 0.8},
        },
    ]

    decision = _choose(tmp_path, 2, rounds, higher_is_better=True)

    assert decision["branch"] == "improve"
    assert decision["parent_binding"]["commit"] == "higher11"
    assert decision["parent_binding"]["score"] == 0.8


def test_v3_missing_binding_does_not_fall_back_to_vault(tmp_path) -> None:
    init_git_structure(tmp_path)
    _write_solution(tmp_path, "vault123", "SOURCE = 'vault'\n")
    (tmp_path / "index" / "best_validation_candidate.json").write_text(
        json.dumps({
            "commit_hash": "vault123",
            "code_path": "commits/vault123/solution.py",
            "validation_score": 0.1,
        }),
        encoding="utf-8",
    )
    decision = {"schema_version": "branch_decision_v3", "branch": "improve"}

    active = tmp_path / "solution.py"
    info = prefill_active_solution_from_incumbent(tmp_path, active, decision)

    assert not info["enabled"]
    assert info["reason"] == "v3_parent_binding_missing"
    assert not active.exists()


def test_legacy_v2_anchor_parent_remains_readable(tmp_path) -> None:
    _write_solution(tmp_path, "legacy12", "SOURCE = 'legacy'\n")
    decision = {
        "schema_version": "branch_decision_v2",
        "branch": "improve",
        "anchor_parent": {
            "commit": "legacy12",
            "code_path": "commits/legacy12/solution.py",
        },
    }

    active = tmp_path / "solution.py"
    info = prefill_active_solution_from_incumbent(tmp_path, active, decision)

    assert info["enabled"]
    assert info["parent_role"] == "validation_best"
    assert active.read_text(encoding="utf-8") == "SOURCE = 'legacy'\n"
