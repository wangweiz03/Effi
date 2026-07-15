from __future__ import annotations

import json

from prompts import SYSTEM_PROMPT
from runtime.runner import compact_round_for_summary
from runtime.text_context import (
    _build_prior_draft_memory,
    _build_round_context_packet,
    _build_round_history,
    _build_score_context,
)


def test_system_prompt_references_current_round_runtime_sections() -> None:
    assert "[PINNED RUNTIME CONTROL]" not in SYSTEM_PROMPT
    assert "[RUNTIME BUDGET ENVELOPE]" not in SYSTEM_PROMPT
    assert "[EXTERNAL VALIDATION TIMEOUT]" in SYSTEM_PROMPT
    assert "[ROUND DIRECTIVE]" in SYSTEM_PROMPT
    assert "Do not copy it into code" in SYSTEM_PROMPT
    assert "internal timers" in SYSTEM_PROMPT
    assert "complete end-to-end path" in SYSTEM_PROMPT


def _round(round_num: int, branch: str, score: float | None, state: str = "frontier_improve") -> dict:
    return {
        "round": round_num,
        "commit": f"{round_num:08x}",
        "branch": branch,
        "branch_state": state,
        "status": "success" if score is not None else "timeout",
        "score": score,
        "method_family": f"family_{round_num % 5}",
    }


def _workload_plan(*, ceiling: int | None, reference: dict | None = None) -> dict:
    reference = reference or {}
    return {
        "schema_version": "workload_plan_v1",
        "policy": "earliest_strong_complete_route",
        "draft_workload_ceiling_seconds": ceiling,
        "ceiling_is_consumption_target": False,
        "expansion_requires_evidence": True,
        "solution_deadline_allowed": False,
        "reference_round": reference.get("round"),
        "reference_branch": reference.get("branch"),
        "reference_status": reference.get("status"),
        "previous_validation_runtime_seconds": reference.get("runtime"),
        "previous_validation_timeout_seconds": reference.get("timeout"),
        "previous_timeout_saturation": reference.get("saturation"),
        "previous_timed_out": reference.get("timed_out"),
    }


def test_compact_round_summary_preserves_frozen_workload_plan() -> None:
    plan = _workload_plan(ceiling=3600)
    compact = compact_round_for_summary({
        "round": 0,
        "branch": "draft",
        "status": "success",
        "branch_decision": {"branch": "draft", "workload_plan": plan},
        "validation": {"status": "success", "score": 0.5, "run_time": 120.0, "timeout": 10800},
    })

    assert compact["branch_decision"]["workload_plan"] == plan


def test_round_history_is_bounded_and_keeps_parent() -> None:
    rows = [_round(index, "draft" if index % 9 == 0 else "improve", index / 100) for index in range(100)]
    text = _build_round_history(rows, parent_round=37, higher_is_better=True)

    data_lines = [line for line in text.splitlines() if line[:1].isdigit()]
    assert len(data_lines) <= 24
    assert any(line.startswith("37 |") and line.endswith("| parent") for line in data_lines)
    assert "Omitted historical rounds: 76" in text
    assert "anchor_parent" not in text


def test_round_history_uses_validation_runtime_and_exposes_timeout_saturation() -> None:
    rows = [
        {
            **_round(0, "draft", 0.6, "initial_seed"),
            "round_wall_time": 9999.0,
            "validation": {"status": "success", "score": 0.6, "run_time": 1800.0, "timeout": 3600},
        },
        {
            **_round(1, "draft", None, "required_seed"),
            "round_wall_time": 8888.0,
            "validation": {"status": "timeout", "score": None, "run_time": 3599.0, "timeout": 3600},
        },
    ]

    text = _build_round_history(rows, parent_round=None, higher_is_better=True)
    lowered = text.lower()

    assert "sandbox_runtime_seconds" in lowered
    assert "timeout_saturation" in lowered
    assert "1800" in text
    assert "3599" in text
    assert "0.500" in text or "0.5" in text
    assert "1.000" in text or "0.999" in text
    assert "9999" not in text
    assert "8888" not in text
    assert "timeout" in lowered


def test_prior_draft_memory_lists_cards_without_code_or_compat_operator(tmp_path) -> None:
    memory = tmp_path / "memory_bank"
    memory.mkdir()
    cards_dir = memory / "cards"
    cards_dir.mkdir()
    rows = []
    for index in range(25):
        summary = (
            "Summary for draft round 24. " + ("full detail " * 100) + "COMPLETE_END."
            if index == 24
            else f"Summary for draft round {index}."
        )
        (cards_dir / f"round_{index:03d}.md").write_text(
            f"## Method Portrait\n- method_summary: {summary}\n",
            encoding="utf-8",
        )
        rows.append({
            "round": index,
            "commit": f"{index:08x}",
            "branch": "draft",
            "status": "success" if index != 7 else "timeout",
            "score": index / 100,
            "method_family": "agent_selected_after_context" if index == 7 else f"family_{index % 4}",
            "method_keywords": [f"view_{index}", "draft", "new_seed_score_first"],
            "cost_bucket": "low_cost",
            "reward_bucket": "material_gain",
            "risk_tags": ["timeout_risk"],
            "card_path": f"memory_bank/cards/round_{index:03d}.md",
        })
    (memory / "card_index.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    text, paths = _build_prior_draft_memory(tmp_path, current_round=25, higher_is_better=True)

    assert len([line for line in text.splitlines() if line.startswith("- round:")]) <= 4
    assert "method_summary: Summary for draft round" in text
    assert "COMPLETE_END." in text
    assert "agent_selected_after_context" not in text
    assert "solution.py" not in text
    assert "status=" not in text
    assert "family=" not in text
    assert "cost=" not in text
    assert "reward=" not in text
    assert "risks=" not in text
    assert paths


def test_score_context_is_branch_aware_and_modality_neutral() -> None:
    feedback = {
        "latest": {"round": 2, "commit": "latest", "score": 0.4, "method_family": "cnn_image"},
        "best": {"round": 1, "commit": "best", "score": 0.5, "method_family": "cnn_image"},
        "required_response": ["Add text views, NB-SVM, LinearSVC, and vocabulary variants."],
    }

    improve = _build_score_context(feedback, "improve", "frontier_improve")
    debug = _build_score_context(feedback, "debug", "timeout_recovery")
    audit = _build_score_context(feedback, "improve", "final_audit")

    assert "NB-SVM" not in improve
    assert "appropriate to the chosen task" in improve
    assert "linked failure evidence" in debug
    assert "do not start a new route" in audit


def test_score_context_does_not_duplicate_latest_incumbent_identity() -> None:
    feedback = {
        "latest": {"round": 4, "commit": "same1234", "score": 0.7, "method_family": "tabular_gbdt"},
        "best": {"round": 4, "commit": "same1234", "score": 0.7, "method_family": "tabular_gbdt"},
    }

    text = _build_score_context(feedback, "improve", "frontier_improve")

    assert "latest_is_incumbent: true" in text
    assert "latest_scored:" in text
    assert not any(line.startswith("incumbent:") for line in text.splitlines())


def test_draft_round_packet_has_no_parent_and_includes_external_timeout(tmp_path) -> None:
    (tmp_path / "memory_bank").mkdir()
    (tmp_path / "memory_bank" / "card_index.jsonl").write_text("", encoding="utf-8")
    decision = {
        "round": 0,
        "branch_state": "initial_seed",
        "branch_reason": "round_0_initial_seed",
        "runtime_profile": "new_seed_score_first",
        "runtime_control": {"strict_score_first_required": True},
        "validation_timeout_seconds": 10800,
        "budget": {"remaining_budget": 12000},
        "workload_plan": _workload_plan(ceiling=3600),
    }

    text, _ = _build_round_context_packet(
        task_dir=tmp_path,
        metadata={"higher_is_better": True},
        branch_decision=decision,
        branch="draft",
        parent={},
        parent_card_path="",
        all_rounds=[],
    )

    assert "[ROUND DIRECTIVE]" in text
    assert "[PRIOR DRAFT MEMORY]" in text
    assert "[PARENT MEMORY CARD]" not in text
    assert "runtime_profile: new_seed_score_first" in text
    assert "strict_score_first_required: true" in text
    assert "[EXTERNAL VALIDATION TIMEOUT]" in text
    assert "validation_timeout_seconds: 10800" in text
    assert "remaining_sandbox_runtime_seconds: 12000" in text
    assert "enforces this sandbox kill ceiling externally" in text
    assert "not an expected runtime or quota" in text
    assert "[RUNTIME BUDGET ENVELOPE]" not in text
    assert "framework_reference" not in text
    assert "solution_internal_budget" not in text
    assert "allocation_basis" not in text
    assert "[PINNED RUNTIME CONTROL" not in text
    assert "[BEST VALIDATION CANDIDATE]" not in text
    assert "[DRAFT WORKLOAD CEILING]" in text
    assert "draft_workload_ceiling_seconds: 3600" in text
    assert "not a target" in text.lower()
    assert "headroom" in text.lower()


def test_non_draft_round_packet_renders_observed_parent_runtime_without_a_draft_ceiling(tmp_path) -> None:
    reference = {
        "round": 2,
        "branch": "draft",
        "status": "success",
        "runtime": 321.0,
        "timeout": 10800,
        "saturation": 321.0 / 10800.0,
        "timed_out": False,
    }
    decision = {
        "round": 3,
        "branch_state": "frontier_improve",
        "budget": {"remaining_budget": 12_000},
        "validation_timeout_seconds": 10_800,
        "workload_plan": _workload_plan(ceiling=None, reference=reference),
    }

    text, _ = _build_round_context_packet(
        task_dir=tmp_path,
        metadata={"higher_is_better": True},
        branch_decision=decision,
        branch="improve",
        parent={"round": 2, "score": 0.7},
        parent_card_path="",
        all_rounds=[],
    )

    assert "[OBSERVED RUNTIME EVIDENCE]" in text
    assert "reference_round: 2" in text
    assert "reference_branch: draft" in text
    assert "previous_validation_runtime_seconds: 321" in text
    assert "previous_validation_timeout_seconds: 10800" in text
    assert "[DRAFT WORKLOAD CEILING]" not in text


def test_round_packet_falls_back_to_remaining_runtime_for_external_timeout(tmp_path) -> None:
    decision = {
        "round": 1,
        "branch_state": "frontier_improve",
        "budget": {"remaining_budget": 5000},
    }

    text, _ = _build_round_context_packet(
        task_dir=tmp_path,
        metadata={"higher_is_better": True},
        branch_decision=decision,
        branch="improve",
        parent={},
        parent_card_path="",
        all_rounds=[],
    )

    assert "validation_timeout_seconds: 5000" in text
    assert "solution_internal_budget" not in text


def test_round_directive_owns_branch_specific_execution_guards(tmp_path) -> None:
    cases = (
        ("draft", "initial_seed", "independent phase-scoped strong seed"),
        ("debug", "repair_failure", "repair exactly the linked failed parent and failure class"),
        ("improve", "frontier_improve", "one evidence-backed material improvement"),
    )
    for branch, state, expected in cases:
        text, _ = _build_round_context_packet(
            task_dir=tmp_path,
            metadata={"higher_is_better": True},
            branch_decision={"round": 1, "branch_state": state},
            branch=branch,
            parent={},
            parent_card_path="",
            all_rounds=[],
        )

        assert expected in text


def test_debug_and_improve_packets_route_only_parent_memory(tmp_path) -> None:
    card_path = tmp_path / "parent_card.md"
    complete_parent_summary = "A compact parent method portrait. " + ("full detail " * 80) + "PARENT_COMPLETE_END."
    card_path.write_text(
        "- commit: parent12\n- status: success\n- score: 0.7\n"
        f"- method_summary: {complete_parent_summary}\n",
        encoding="utf-8",
    )
    parent = {
        "round": 2,
        "commit": "parent12",
        "status": "success",
        "score": 0.7,
        "method_family": "tabular_gbdt",
    }
    for branch, state in (("debug", "repair_failure"), ("improve", "frontier_improve")):
        text, draft_paths = _build_round_context_packet(
            task_dir=tmp_path,
            metadata={"higher_is_better": True},
            branch_decision={
                "round": 3,
                "branch_state": state,
                "workload_plan": _workload_plan(
                    ceiling=None,
                    reference={
                        "round": 2,
                        "branch": "draft",
                        "status": "success",
                        "runtime": 120.0,
                        "timeout": 1800,
                        "saturation": 120.0 / 1800.0,
                        "timed_out": False,
                    },
                ),
                "draft_prior_memory": {
                    "cards": [{"round": 0, "method_family": "must_not_render"}],
                },
            },
            branch=branch,
            parent=parent,
            parent_card_path=str(card_path),
            all_rounds=[],
        )

        assert "[PARENT MEMORY CARD]" in text
        assert "[PRIOR DRAFT MEMORY]" not in text
        assert "- round: 2" in text
        assert "- score: 0.7" in text
        assert f"- method_summary: {complete_parent_summary}" in text
        assert "PARENT_COMPLETE_END." in text
        assert "- status:" not in text
        assert "must_not_render" not in text
        assert draft_paths == []
        assert "[OBSERVED RUNTIME EVIDENCE]" in text
