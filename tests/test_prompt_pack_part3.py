from __future__ import annotations

import json

from runtime.bootstrap import (
    build_pinned_runtime_context,
    build_v35_context_source_map,
    pack_prompt_with_pinned_runtime,
)


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_v3_improve_prompt_uses_one_parent_binding_and_source_map_paths(tmp_path) -> None:
    commit = "best1234"
    commit_dir = tmp_path / "commits" / commit
    commit_dir.mkdir(parents=True)
    (commit_dir / "solution.py").write_text("VALUE = 1\n", encoding="utf-8")
    (commit_dir / "validation_feedback.txt").write_text("score improved\n", encoding="utf-8")
    card = tmp_path / "memory_bank" / "cards" / "round_001_best1234.md"
    card.parent.mkdir(parents=True)
    card.write_text(
        "\n".join([
            "# Memory Card",
            "- branch: draft",
            "- branch_state: required_seed",
            "- commit: best1234",
            "- status: success",
            "- score: 0.81",
            "- method_family: tabular_gbdt",
            "- core_components: robust split, categorical encoding, bounded ensemble",
            "- method_summary: A compact validated tabular route.",
            "- reuse_risk: Keep the split contract and avoid unbounded searches.",
        ]),
        encoding="utf-8",
    )
    rounds = tmp_path / "memory_bank" / "rounds.jsonl"
    rounds.write_text(
        json.dumps({
            "round": 1,
            "branch": "draft",
            "branch_state": "required_seed",
            "status": "success",
            "score": 0.81,
            "method_family": "tabular_gbdt",
            "commit": commit,
        }) + "\n",
        encoding="utf-8",
    )
    binding = {
        "role": "validation_best",
        "round": 1,
        "commit": commit,
        "status": "success",
        "score": 0.81,
        "method_family": "tabular_gbdt",
        "memory_card_path": str(card.relative_to(tmp_path)),
        "code_path": f"commits/{commit}/solution.py",
        "feedback_path": f"commits/{commit}/validation_feedback.txt",
    }
    _write_json(tmp_path / "index" / "current_branch_decision.json", {
        "schema_version": "branch_decision_v3",
        "round": 2,
        "branch": "improve",
        "branch_state": "final_audit",
        "branch_reason": "final_budget_window_audit_best_candidate",
        "runtime_profile": "final_audit",
        "parent_binding": binding,
        "budget": {"remaining_budget": 2400},
        "validation_timeout_seconds": 1800,
        "external_timeout_plan": {
            "schema_version": "external_timeout_plan_v1",
            "validation_timeout_seconds": 1800,
            "remaining_sandbox_runtime_seconds": 2400,
            "runtime_profile": "final_audit",
            "allocation_basis": "framework_operator_cap",
        },
    })

    metadata = {
        "task_name": "unit-task",
        "branch": "improve",
        "higher_is_better": True,
        "cpu_gpu": "cpu",
        "data_dir": "/tmp/data",
        "incumbent_prefill": {
            "enabled": True,
            "source_path": str(commit_dir / "solution.py"),
            "parent_role": "validation_best",
        },
    }
    context, info = build_pinned_runtime_context(tmp_path, metadata, None, "coding")
    full_prompt, pack = pack_prompt_with_pinned_runtime(
        "system",
        context,
        info,
        "",
        ["[USER]\nBuild the solution."],
        "coding",
        20_000,
    )
    part3 = full_prompt.split("# PART 3 - CURRENT ROUND ITERATION STATE", 1)[1].split(
        "# PART 4 - REQUIRED AND OPTIONAL SOURCE PATHS", 1
    )[0]
    part4 = full_prompt.split("# PART 4 - REQUIRED AND OPTIONAL SOURCE PATHS", 1)[1]

    assert part3.count("[ROUND DIRECTIVE]") == 1
    assert "[PARENT MEMORY CARD]" in part3
    assert "[PRIOR DRAFT MEMORY]" not in part3
    assert "- round: 1" in part3
    assert "- score: 0.81" in part3
    assert "- method_summary: A compact validated tabular route." in part3
    assert "role:" not in part3
    assert "method_family:" not in part3
    assert "action: audit and safely finalize the validation-best parent" in part3
    assert str(commit_dir / "solution.py") not in part3
    assert f"commits/{commit}/solution.py" in part4
    assert "[ROUND STATE]" not in full_prompt
    assert "[BEST VALIDATION CANDIDATE]" not in full_prompt
    assert "agent_selected_after_context" not in full_prompt
    assert "[EXTERNAL VALIDATION TIMEOUT]" in part3
    assert "validation_timeout_seconds: 1800" in part3
    assert "solution_internal_budget" not in part3
    assert "runtime_budget_plan" not in part3
    assert pack["round_context_schema"] == "part3_compact_v2"
    assert not pack["critical_marker_failures"]


def test_v3_draft_prompt_renders_frozen_prior_cards_without_parent(tmp_path) -> None:
    (tmp_path / "memory_bank").mkdir(parents=True)
    cards_dir = tmp_path / "memory_bank" / "cards"
    cards_dir.mkdir()
    (cards_dir / "round_000_draft000.md").write_text(
        "## Method Portrait\n- method_summary: Sparse word and character linear ensemble.\n",
        encoding="utf-8",
    )
    (cards_dir / "round_002_draft222.md").write_text(
        "## Method Portrait\n- method_summary: Compact transformer representation with a bounded classifier.\n",
        encoding="utf-8",
    )
    _write_json(tmp_path / "index" / "current_branch_decision.json", {
        "schema_version": "branch_decision_v3",
        "round": 4,
        "branch": "draft",
        "branch_state": "plateau_new_seed",
        "branch_reason": "plateau",
        "parent_binding": {"role": "none"},
        "draft_prior_memory": {
            "schema_version": "draft_prior_memory_v1",
            "status": "available",
            "evidence_cutoff_round": 3,
            "cards": [
                {
                    "round": 0,
                    "commit": "draft000",
                    "status": "success",
                    "score": 0.4,
                    "method_family": "sparse_text_logreg",
                    "card_path": "memory_bank/cards/round_000_draft000.md",
                },
                {
                    "round": 2,
                    "commit": "draft222",
                    "status": "timeout",
                    "score": None,
                    "method_family": "transformer_text",
                    "card_path": "memory_bank/cards/round_002_draft222.md",
                },
            ],
            "omitted_count": 0,
        },
        "budget": {"remaining_budget": 5000},
        "validation_timeout_seconds": 3000,
    })
    context, info = build_pinned_runtime_context(
        tmp_path,
        {"task_name": "unit-task", "branch": "draft", "higher_is_better": True},
        None,
        "coding",
    )

    assert "[PRIOR DRAFT MEMORY]" in context
    assert "Sparse word and character linear ensemble." in context
    assert "Compact transformer representation with a bounded classifier." in context
    assert "status=" not in context
    assert "family=" not in context
    assert "[PARENT MEMORY CARD]" not in context
    assert info["parent_binding"] == {}
    assert not info["parent_commit"]


def test_skill_sources_follow_source_policy_with_required_path_emphasis(tmp_path) -> None:
    task_skill = tmp_path / "context_sources" / "task_skill_source_1.md"
    failure_skill = tmp_path / "context_sources" / "failure_prevention_skill_source_1.md"
    task_skill.parent.mkdir(parents=True)
    task_skill.write_text("# Task Skill\n", encoding="utf-8")
    failure_skill.write_text("# ML Failure Prevention\n", encoding="utf-8")
    _write_json(tmp_path / "index" / "current_branch_decision.json", {
        "schema_version": "branch_decision_v3",
        "round": 0,
        "branch": "draft",
        "branch_state": "initial_seed",
        "source_policy": {
            "must": ["task_skill", "failure_prevention_skill", "eda_summary"],
            "optional": [],
        },
        "budget": {"remaining_budget": 5000},
        "validation_timeout_seconds": 3000,
    })
    metadata = {
        "task_name": "unit-task",
        "branch": "draft",
        "higher_is_better": True,
        "skill_sources": [str(task_skill), str(failure_skill)],
    }

    context, info = build_pinned_runtime_context(tmp_path, metadata, None, "coding")
    full_prompt, pack = pack_prompt_with_pinned_runtime(
        "system", context, info, "", ["[USER]\nBuild the solution."], "coding", 20_000
    )
    part4 = full_prompt.split("# PART 4 - REQUIRED AND OPTIONAL SOURCE PATHS", 1)[1]

    assert info["retrieval_paths"] == [str(task_skill), str(failure_skill)]
    assert "- task_skill_source: **context_sources/task_skill_source_1.md** - task-specific" in part4
    assert (
        "- failure_prevention_skill_source: **context_sources/failure_prevention_skill_source_1.md** "
        "- general MLE contract checklist" in part4
    )
    must_labels = {entry["label"] for entry in pack["context_source_map"]["must_inspect"]}
    assert {"task_skill_source", "failure_prevention_skill_source"} <= must_labels


def test_optional_skill_path_is_not_bold_and_missing_must_skill_is_explicit(tmp_path) -> None:
    task_skill = tmp_path / "context_sources" / "task_skill_source_1.md"
    task_skill.parent.mkdir(parents=True)
    task_skill.write_text("# Task Skill\n", encoding="utf-8")
    source_map, source_info = build_v35_context_source_map({
        "task_dir": str(tmp_path),
        "phase_name": "coding",
        "branch": "debug",
        "source_policy": {
            "must": ["failure_prevention_skill"],
            "optional": ["task_skill"],
        },
        "retrieval_paths": [str(task_skill)],
    })

    assert "- task_skill_source: context_sources/task_skill_source_1.md - task-specific" in source_map
    assert "task_skill_source: **" not in source_map
    assert "- failure_prevention_skill_source: <missing> - general MLE contract checklist" in source_map
    assert any(
        entry["label"] == "failure_prevention_skill_source" and entry["prompt_path"] == "<missing>"
        for entry in source_info["must_inspect"]
    )
    assert any(entry["label"] == "task_skill_source" for entry in source_info["optional"])


def test_draft_static_gate_repair_exposes_current_round_not_history(tmp_path) -> None:
    context_sources = tmp_path / "context_sources"
    context_sources.mkdir()
    task_skill = context_sources / "task_skill_source_1.md"
    failure_skill = context_sources / "failure_prevention_skill_source_1.md"
    task_skill.write_text("# Task Skill\n", encoding="utf-8")
    failure_skill.write_text("# ML Failure Prevention\n", encoding="utf-8")
    (tmp_path / "solution.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "context_readiness.md").write_text("# Current plan\n", encoding="utf-8")
    (tmp_path / "post_code_memory_summary.md").write_text("# Current method\n", encoding="utf-8")
    card = tmp_path / "memory_bank" / "cards" / "round_000_old.md"
    card.parent.mkdir(parents=True)
    card.write_text("- method_summary: Historical draft.\n", encoding="utf-8")
    (tmp_path / "memory_bank" / "card_index.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "memory_bank" / "rounds.jsonl").write_text("{}\n", encoding="utf-8")
    portfolio = tmp_path / "graph" / "portfolio.json"
    portfolio.parent.mkdir()
    portfolio.write_text("{}\n", encoding="utf-8")
    _write_json(tmp_path / "index" / "current_branch_decision.json", {
        "schema_version": "branch_decision_v3",
        "round": 1,
        "branch": "draft",
        "branch_state": "required_seed",
        "source_policy": {
            "must": ["task_skill", "failure_prevention_skill", "eda_summary"],
            "optional": ["card_index", "top_cards"],
        },
        "draft_prior_memory": {
            "status": "available",
            "cards": [{
                "round": 0,
                "score": 0.4,
                "method_summary": "Historical draft.",
                "card_path": "memory_bank/cards/round_000_old.md",
            }],
        },
        "budget": {"remaining_budget": 5000},
        "validation_timeout_seconds": 3000,
    })
    metadata = {
        "task_name": "unit-task",
        "branch": "draft",
        "higher_is_better": True,
        "skill_sources": [str(task_skill), str(failure_skill)],
    }

    context, info = build_pinned_runtime_context(tmp_path, metadata, None, "static_gate_repair")
    full_prompt, pack = pack_prompt_with_pinned_runtime(
        "system",
        context,
        info,
        "",
        ["[USER]\nRepair the current solution."],
        "static_gate_repair",
        20_000,
    )
    part3 = full_prompt.split("# PART 3 - CURRENT ROUND ITERATION STATE", 1)[1].split(
        "# PART 4 - REQUIRED AND OPTIONAL SOURCE PATHS", 1
    )[0]
    part4 = full_prompt.split("# PART 4 - REQUIRED AND OPTIONAL SOURCE PATHS", 1)[1]

    assert "[PRIOR DRAFT MEMORY]" not in part3
    assert "[ROUND HISTORY]" not in part3
    assert "repair the current-round solution only" in part3
    assert "current_round_solution: solution.py" in part4
    assert "current_context_readiness: context_readiness.md" in part4
    assert "current_post_code_memory_summary: post_code_memory_summary.md" in part4
    for forbidden in (
        "prior_draft_card_",
        "memory_card_index",
        "memory_cards_dir",
        "memory_diffs_dir",
        "portfolio_json",
        "rounds_ledger",
        "runtime_memory_prompt_compat",
    ):
        assert forbidden not in part4
    must_labels = {entry["label"] for entry in pack["context_source_map"]["must_inspect"]}
    assert {
        "current_round_solution",
        "current_context_readiness",
        "current_post_code_memory_summary",
        "task_skill_source",
        "failure_prevention_skill_source",
    } <= must_labels


def test_high_level_memory_follows_branch_and_phase_source_policy(tmp_path) -> None:
    memory_path = tmp_path / "memory_bank" / "high_level_memory.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("# High-Level Memory\n", encoding="utf-8")

    draft_map, draft_info = build_v35_context_source_map({
        "task_dir": str(tmp_path),
        "phase_name": "coding",
        "branch": "draft",
        "source_policy": {"must": ["high_level_memory"], "optional": []},
    })
    assert "- high_level_memory: memory_bank/high_level_memory.md - task-level" in draft_map
    assert any(entry["label"] == "high_level_memory" for entry in draft_info["must_inspect"])

    debug_map, debug_info = build_v35_context_source_map({
        "task_dir": str(tmp_path),
        "phase_name": "coding",
        "branch": "debug",
        "source_policy": {"must": [], "optional": ["high_level_memory"]},
    })
    assert "- high_level_memory: memory_bank/high_level_memory.md - task-level" in debug_map
    assert any(entry["label"] == "high_level_memory" for entry in debug_info["optional"])

    repair_map, repair_info = build_v35_context_source_map({
        "task_dir": str(tmp_path),
        "phase_name": "static_gate_repair",
        "branch": "improve",
        "source_policy": {"must": ["high_level_memory"], "optional": []},
    })
    assert "- high_level_memory:" not in repair_map
    assert not any(
        entry["label"] == "high_level_memory"
        for entry in repair_info["must_inspect"] + repair_info["optional"]
    )


def test_missing_high_level_memory_is_omitted_until_it_exists(tmp_path) -> None:
    source_map, source_info = build_v35_context_source_map({
        "task_dir": str(tmp_path),
        "phase_name": "coding",
        "branch": "draft",
        "source_policy": {"must": ["high_level_memory"], "optional": []},
    })

    assert "- high_level_memory:" not in source_map
    assert not any(
        entry["label"] == "high_level_memory"
        for entry in source_info["must_inspect"] + source_info["optional"]
    )


def test_eda_file_presence_is_distinct_from_inline_presence(tmp_path) -> None:
    eda_summary = tmp_path / "early_eda" / "round_0" / "eda_summary.md"
    eda_summary.parent.mkdir(parents=True)
    eda_summary.write_text("# EDA Summary\n", encoding="utf-8")
    _write_json(tmp_path / "index" / "current_branch_decision.json", {
        "schema_version": "branch_decision_v3",
        "round": 0,
        "branch": "draft",
        "branch_state": "initial_seed",
        "runtime_profile": "new_seed_score_first",
        "runtime_control": {"strict_score_first_required": True},
        "source_policy": {"must": ["eda_summary"], "optional": []},
    })

    _context, info = build_pinned_runtime_context(
        tmp_path,
        {"task_name": "unit-task", "branch": "draft", "higher_is_better": True},
        None,
        "coding",
    )

    assert info["latest_eda_summary_exists"] is True
    assert info["source_presence"]["latest_eda_summary"] is True
    assert "early_eda_summary" not in info["source_presence"]
    assert info["inline_presence"]["early_eda_summary"] is False


def test_historical_legacy_prompt_context_is_not_exposed_in_part4(tmp_path) -> None:
    memory_path = tmp_path / "memory_bank" / "prompt_context.md"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text("# Retrieved Runtime Memory Context\n", encoding="utf-8")

    for branch in ("draft", "debug", "improve"):
        source_map, source_info = build_v35_context_source_map({
            "task_dir": str(tmp_path),
            "phase_name": "coding",
            "branch": branch,
            "source_policy": {"must": [], "optional": []},
        })

        assert "runtime_memory_prompt_compat" not in source_map
        assert not any(
            entry["label"] == "runtime_memory_prompt_compat"
            for entry in source_info["must_inspect"] + source_info["optional"]
        )
