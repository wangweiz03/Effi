from __future__ import annotations

import json

from prompts import SYSTEM_PROMPT
from runtime.bootstrap import (
    build_pinned_runtime_context,
    build_v35_context_source_map,
    filter_user_task_for_context_first_coding,
    pack_prompt_with_pinned_runtime,
    prompt_token_count,
)


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


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


def test_coding_user_task_removes_redundant_metadata_but_keeps_task_description() -> None:
    raw = """[USER TASK]

[SYSTEM]
duplicated environment

[USER]
legacy output contract

[METADATA]
Task: example
Higher is Better: True

[DATA DESCRIPTION]
large generated inventory

[TASK DESCRIPTION]
Authoritative competition description.
"""

    filtered, record = filter_user_task_for_context_first_coding(raw)

    assert "[METADATA]" not in filtered
    assert "[DATA DESCRIPTION]" not in filtered
    assert "duplicated environment" not in filtered
    assert "legacy output contract" not in filtered
    assert filtered.count("[TASK DESCRIPTION]") == 1
    assert "Authoritative competition description." in filtered
    assert "metadata" in record["removed_blocks"]


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
        "workload_plan": _workload_plan(
            ceiling=None,
            reference={
                "round": 1,
                "branch": "draft",
                "status": "success",
                "runtime": 601.5,
                "timeout": 1800,
                "saturation": 601.5 / 1800,
                "timed_out": False,
            },
        ),
    })
    model_cache_path = tmp_path / "context_sources" / "sandbox_model_cache.txt"
    model_cache_path.parent.mkdir(parents=True, exist_ok=True)
    model_cache_path.write_text(
        "HF\tmicrosoft/deberta-v3-base\trevision=abc\tbytes=100\n",
        encoding="utf-8",
    )

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
    assert "[OBSERVED RUNTIME EVIDENCE]" in part3
    assert "reference_round: 1" in part3
    assert "previous_validation_runtime_seconds: 601.5" in part3
    assert "[DRAFT WORKLOAD CEILING]" not in part3
    assert "[SANDBOX CAPABILITIES]" not in part3
    assert "sandbox_model_cache: context_sources/sandbox_model_cache.txt" in part4
    improve_must = part4.split("Must inspect before coding:", 1)[1].split("Optional expansion paths:", 1)[0]
    improve_optional = part4.split("Optional expansion paths:", 1)[1]
    assert "sandbox_model_cache" not in improve_must
    assert "sandbox_model_cache: context_sources/sandbox_model_cache.txt" in improve_optional
    assert pack["round_context_schema"] == "part3_compact_v3"
    assert not pack["critical_marker_failures"]


def test_sandbox_environment_routes_ready_model_cache_through_grep(tmp_path) -> None:
    raw = """[USER TASK]

[SYSTEM]
You are operating in a Python environment where the following machine learning-related packages are preinstalled: torch, torchvision, timm, transformers, sentence-transformers.

[USER]
**CONSTRAINTS**:
- Use torch.optim.AdamW.

[TASK DESCRIPTION]
Build a model.
"""
    _write_json(tmp_path / "index" / "current_branch_decision.json", {
        "round": 0,
        "branch": "draft",
        "branch_state": "initial_seed",
        "parent_binding": {"role": "none"},
        "budget": {"remaining_budget": 3600},
        "validation_timeout_seconds": 3600,
    })
    context, info = build_pinned_runtime_context(
        tmp_path,
        {"task_name": "unit-task", "branch": "draft", "higher_is_better": True},
        None,
        "coding",
    )
    full_prompt, _ = pack_prompt_with_pinned_runtime(
        "system",
        context,
        info,
        "",
        [raw],
        "coding",
        20_000,
    )

    assert "Model cache lookup:" in full_prompt
    assert "grep -iE 'deberta|roberta|resnet|efficientnet' context_sources/sandbox_model_cache.txt" in full_prompt
    assert "do not read the entire file" in full_prompt
    assert "unavailable or incomplete entries are omitted" in full_prompt
    assert "sandbox_model_cache: context_sources/sandbox_model_cache.txt" in full_prompt
    draft_part4 = full_prompt.split("# PART 4 - REQUIRED AND OPTIONAL SOURCE PATHS", 1)[1]
    draft_must = draft_part4.split("Must inspect before coding:", 1)[1].split("Optional expansion paths:", 1)[0]
    assert "sandbox_model_cache: context_sources/sandbox_model_cache.txt" in draft_must


def test_part1_is_compact_complete_and_contains_no_branch_skill_body(tmp_path) -> None:
    raw = """[USER TASK]

[SYSTEM]
You are operating in a Python environment where the following machine learning-related packages are preinstalled: torch, torchvision, timm, transformers, sentence-transformers, lightgbm, albumentations.
- CPU: 16 cores
- System Memory: 64 GB
- GPU Memory: 24 GB

[USER]
Use torch.optim.AdamW, lightgbm.early_stopping, TrainingArguments with eval_strategy, and albumentations RandomResizedCrop where relevant.

[TASK DESCRIPTION]
Build a trained model and produce the required submission.
"""
    _write_json(tmp_path / "index" / "current_branch_decision.json", {
        "round": 0,
        "branch": "draft",
        "branch_state": "initial_seed",
        "parent_binding": {"role": "none"},
        "budget": {"remaining_budget": 3600},
        "validation_timeout_seconds": 3600,
    })
    context, info = build_pinned_runtime_context(
        tmp_path,
        {"task_name": "unit-task", "branch": "draft", "higher_is_better": True},
        None,
        "coding",
    )
    full_prompt, pack = pack_prompt_with_pinned_runtime(
        SYSTEM_PROMPT,
        context,
        info,
        "",
        [raw],
        "coding",
        20_000,
    )
    part1 = full_prompt.split("# PART 1 - HARD EXECUTION RULES AND SANDBOX", 1)[1].split(
        "# PART 2 - TASK DESCRIPTION AND CONTRACT", 1
    )[0]

    assert prompt_token_count(part1) <= 2200
    for required in (
        "[SYSTEM INSTRUCTIONS]",
        "[PINNED SANDBOX ENVIRONMENT]",
        "[CONTEXT-FIRST PROTOCOL]",
        "[OUTPUT CONTRACT]",
        "candidate x fold x epoch",
        "complete end-to-end workload estimate",
        "draft_workload_ceiling_seconds",
        "expected_complete_path_seconds",
        "runtime_estimate_basis",
        "dominant_cost_units",
        "complete_workload_product",
        "within_ceiling: yes",
        "why_no_further_expansion",
        "context_readiness.md",
        "post_code_memory_summary.md",
        "sandbox_model_cache.txt",
        "review the required failure-prevention skill",
        "failure-prevention check",
        "stable, proven library components",
        "semantically equivalent deterministic alternative",
        "Cache availability alone is not evidence",
        "sandbox kill ceiling",
        "Historical runtime allowances",
        "unused runtime headroom",
        "torch.optim.AdamW",
        "lightgbm.early_stopping",
        "eval_strategy",
        "size=(H, W)",
    ):
        assert required in part1
    for obsolete in (
        "[BRANCH INLINE GUARDS]",
        "[RUNTIME HARDENING CONTRACT]",
        "top-ranked Kaggle grandmaster",
        "implementation coverage table",
        "two base models plus blends",
        "one-knob superstition",
        "prefer PyTorch over TensorFlow",
        "run_preflight",
        "BSPM_PREFLIGHT",
    ):
        assert obsolete not in part1
    assert pack["packing"] == "v54_draft_workload_ceiling"
    assert pack["branch_context_routing"]["inlined"] is False
    assert "branch_inline_guards" not in pack["section_tokens"]
    assert "selected_skill_filter" not in pack
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
        "budget": {"remaining_budget": 12000},
        "validation_timeout_seconds": 10800,
        "workload_plan": _workload_plan(
            ceiling=3600,
            reference={
                "round": 2,
                "branch": "draft",
                "status": "timeout",
                "runtime": 3590.0,
                "timeout": 3600,
                "saturation": 3590.0 / 3600,
                "timed_out": True,
            },
        ),
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
    assert "[DRAFT WORKLOAD CEILING]" in context
    assert "draft_workload_ceiling_seconds: 3600" in context
    assert "soft ceiling, not a target" in context
    assert "merely because headroom remains" in context
    assert "reference_round: 2" in context
    assert "previous_validation_runtime_seconds: 3590.0" in context

    full_prompt, pack = pack_prompt_with_pinned_runtime(
        SYSTEM_PROMPT,
        context,
        info,
        "",
        ["[USER]\nBuild the solution."],
        "coding",
        20_000,
    )
    part1 = full_prompt.split("# PART 1 - HARD EXECUTION RULES AND SANDBOX", 1)[1].split(
        "# PART 2 - TASK DESCRIPTION AND CONTRACT", 1
    )[0]
    part3 = full_prompt.split("# PART 3 - CURRENT ROUND ITERATION STATE", 1)[1].split(
        "# PART 4 - REQUIRED AND OPTIONAL SOURCE PATHS", 1
    )[0]
    for readiness_field in (
        "draft_workload_ceiling_seconds",
        "expected_complete_path_seconds",
        "runtime_estimate_basis",
        "dominant_cost_units",
        "complete_workload_product",
        "within_ceiling: yes",
        "why_no_further_expansion",
    ):
        assert readiness_field in part1
    assert "[DRAFT WORKLOAD CEILING]" in part3
    assert "[OBSERVED RUNTIME EVIDENCE]" not in part3
    assert "[PARENT MEMORY CARD]" not in part3
    assert "[PRIOR DRAFT MEMORY]" in part3
    for obsolete_runtime_mechanism in (
        "run_preflight",
        "BSPM_PREFLIGHT",
        "solution_internal_budget",
        "internal_deadline_seconds",
        "SOLUTION_INTERNAL",
        "time.monotonic",
    ):
        assert obsolete_runtime_mechanism not in full_prompt
    assert pack["packing"] == "v54_draft_workload_ceiling"
    assert pack["round_context_schema"] == "part3_compact_v3"
    assert not pack["critical_marker_failures"]


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
            "must": ["task_skill", "failure_prevention_skill", "eda_findings"],
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
            "must": ["task_skill", "failure_prevention_skill", "eda_findings"],
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


def test_eda_findings_are_required_and_summary_is_not_routed(tmp_path) -> None:
    eda_summary = tmp_path / "early_eda" / "round_0" / "eda_summary.md"
    eda_summary.parent.mkdir(parents=True)
    eda_summary.write_text("# EDA Summary\n", encoding="utf-8")
    eda_findings = eda_summary.with_name("eda_findings.md")
    eda_findings.write_text("# EDA Findings\n", encoding="utf-8")
    _write_json(tmp_path / "index" / "current_branch_decision.json", {
        "schema_version": "branch_decision_v3",
        "round": 0,
        "branch": "draft",
        "branch_state": "initial_seed",
        "runtime_profile": "new_seed_score_first",
        "runtime_control": {"strict_score_first_required": True},
        "source_policy": {"must": ["eda_findings"], "optional": []},
    })

    _context, info = build_pinned_runtime_context(
        tmp_path,
        {"task_name": "unit-task", "branch": "draft", "higher_is_better": True},
        None,
        "coding",
    )

    assert info["latest_eda_summary_exists"] is True
    assert info["latest_eda_findings_exists"] is True
    assert info["latest_eda_findings_path"] == str(eda_findings)
    assert info["latest_eda_source_kind"] == "findings"
    assert info["source_presence"]["latest_eda_summary"] is True
    assert info["source_presence"]["latest_eda_findings"] is True
    assert "early_eda_summary" not in info["source_presence"]
    assert info["inline_presence"]["early_eda_summary"] is False

    source_map, source_info = build_v35_context_source_map(info)
    assert "- latest_eda_findings: early_eda/round_0/eda_findings.md" in source_map
    assert "eda_summary.md" not in source_map
    assert any(entry["label"] == "latest_eda_findings" for entry in source_info["must_inspect"])


def test_latest_deep_eda_findings_win_over_early_findings(tmp_path) -> None:
    early = tmp_path / "early_eda" / "round_0" / "eda_findings.md"
    deep = tmp_path / "deep_eda" / "round_3" / "eda_findings.md"
    early.parent.mkdir(parents=True)
    deep.parent.mkdir(parents=True)
    early.write_text("# Early findings\n", encoding="utf-8")
    deep.write_text("# Deep findings\n", encoding="utf-8")

    _context, info = build_pinned_runtime_context(
        tmp_path,
        {"task_name": "unit-task", "branch": "draft", "higher_is_better": True},
        None,
        "coding",
    )

    assert info["latest_eda_findings_path"] == str(deep)
    source_map, _source_info = build_v35_context_source_map(info)
    assert "- latest_eda_findings: deep_eda/round_3/eda_findings.md" in source_map


def test_legacy_eda_summary_is_required_only_when_findings_are_absent(tmp_path) -> None:
    summary = tmp_path / "early_eda" / "round_0" / "eda_summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("# Legacy EDA Summary\n", encoding="utf-8")

    _context, info = build_pinned_runtime_context(
        tmp_path,
        {"task_name": "unit-task", "branch": "draft", "higher_is_better": True},
        None,
        "coding",
    )
    source_map, source_info = build_v35_context_source_map(info)

    assert info["latest_eda_findings_exists"] is False
    assert info["latest_eda_source_kind"] == "summary_fallback"
    assert "- legacy_eda_summary_fallback: early_eda/round_0/eda_summary.md" in source_map
    assert any(entry["label"] == "legacy_eda_summary_fallback" for entry in source_info["must_inspect"])


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
