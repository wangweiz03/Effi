from __future__ import annotations

import json

from runtime.memory_cards import (
    _build_soft_lines,
    _join_soft_threads,
    rebuild_high_level_memory,
    write_round_memory_artifacts,
)
from runtime.validation import (
    _parse_post_code_method_summary_block,
    _parse_round_summary,
    write_local_memory_after_round,
)


def _soft_lines(tmp_path, *, status: str, score: float | None) -> str:
    result = {
        "status": status,
        "validation": {"status": status, "score": score},
    }
    return "\n".join(_build_soft_lines(
        task_dir=tmp_path,
        round_num=0,
        round_summary={
            "method_family": "test_family",
            "method_summary": "A bounded test method.",
            "method_profile": "A bounded test profile.",
            "result_reflection": (
                f"Status={status}; score={score}; failure_primary=none; "
                "Diagnostics: base_candidates=6/6, long diagnostic payload"
            ),
        },
        result=result,
        validation=result["validation"],
        failure_taxonomy={"primary": "none"},
        cost_risk={"cost_bucket": "low_cost", "sandbox_run_time": 10.0, "risk_tags": []},
        delta_label="unknown",
        status="completed_local",
    ))


def test_success_memory_card_result_signal_omits_diagnostics(tmp_path) -> None:
    text = _soft_lines(tmp_path, status="success", score=0.7)

    assert "validation_signal: Status=success; score=0.7; failure_primary=none" in text
    assert "Diagnostics:" not in text
    assert "base_candidates" not in text


def test_failed_memory_card_result_signal_keeps_diagnostics(tmp_path) -> None:
    text = _soft_lines(tmp_path, status="timeout", score=None)

    assert "Diagnostics:" in text
    assert "base_candidates=6/6" in text


def test_local_memory_update_does_not_generate_legacy_prompt_context(tmp_path) -> None:
    memory_result = write_local_memory_after_round(
        task_dir=tmp_path,
        metadata={"task_name": "test-task"},
        round_num=0,
        commit_hash="abc12345",
        branch="draft",
        validation_status="success",
        validation_score=0.7,
        round_summary={
            "method_family": "test_family",
            "method_summary": "A bounded test method.",
            "core_components": ["test_component"],
            "validation_diagnostics": {"evidence_lines": ["verbose diagnostic"]},
        },
        higher_is_better=True,
        result={
            "validation": {
                "status": "success",
                "score": 0.7,
                "failure_taxonomy": {"primary": "none"},
                "run_time": 1.0,
            },
            "branch_decision": {"branch": "draft", "branch_state": "initial_seed"},
            "search_operator": {"name": "test_operator", "family": "test_family"},
            "solution_contract": {"status": "pass", "missing": []},
            "code": "print('test')\n",
        },
    )

    assert not (tmp_path / "memory_bank" / "prompt_context.md").exists()
    assert "prompt_context_file" not in memory_result
    assert (tmp_path / "memory_bank" / "rounds.jsonl").exists()
    assert (tmp_path / "memory_bank" / "state.json").exists()


def test_method_summary_remains_complete_from_ingestion_through_card(tmp_path) -> None:
    method_summary = "Long method portrait. " + ("complete detail " * 100) + "COMPLETE_END."
    parsed_post_code = _parse_post_code_method_summary_block(
        f"# Post-Code Memory Summary\ncard_method_summary: {method_summary}\n",
        source="test",
    )
    parsed_support = _parse_round_summary(json.dumps({
        "method_summary": method_summary,
        "result_reflection": "success",
    }))
    result = {
        "status": "success",
        "validation": {"status": "success", "score": 0.7},
    }
    card_text = "\n".join(_build_soft_lines(
        task_dir=tmp_path,
        round_num=0,
        round_summary={
            "method_family": "test_family",
            "method_summary": parsed_post_code["method_summary"],
        },
        result=result,
        validation=result["validation"],
        failure_taxonomy={"primary": "none"},
        cost_risk={"cost_bucket": "low_cost", "sandbox_run_time": 10.0, "risk_tags": []},
        delta_label="unknown",
        status="completed_local",
    ))

    assert parsed_post_code["method_summary"] == method_summary
    assert parsed_support["method_summary"] == method_summary
    assert f"- method_summary: {method_summary}" in card_text
    assert "COMPLETE_END." in card_text


def _round_result(
    *,
    round_num: int,
    branch: str,
    score: float | None,
    commit: str,
    method_family: str,
    method_summary: str,
    components: list[str],
    parent: dict | None = None,
    diff_action: str = "none",
    diff_reason: str = "none",
) -> dict:
    branch_decision = {
        "branch": branch,
        "branch_state": "test_state",
        "parent_binding": parent or {"role": "none"},
    }
    return {
        "round": round_num,
        "branch": branch,
        "branch_decision": branch_decision,
        "status": "success" if score is not None else "timeout",
        "commit_hash": commit,
        "validation": {
            "status": "success" if score is not None else "timeout",
            "score": score,
            "run_time": 10.0,
            "failure_taxonomy": {"primary": "none" if score is not None else "timeout"},
        },
        "round_summary": {
            "method_family": method_family,
            "method_summary": method_summary,
            "method_profile": method_summary,
            "core_components": components,
            "diff_action": diff_action,
            "diff_reason": diff_reason,
            "result_reflection": f"score={score}",
        },
        "solution_contract": {"missing": [], "blockers": []},
    }


def _write_round(tmp_path, result: dict, *, higher_is_better: bool) -> dict:
    update = write_round_memory_artifacts(
        task_dir=tmp_path,
        metadata={"task_name": "unit-task"},
        result=result,
        higher_is_better=higher_is_better,
    )
    _join_soft_threads()
    return update


def test_scored_drafts_compare_against_best_prior_and_record_positive_experience(tmp_path) -> None:
    first_summary = "Linear sparse views with calibrated probabilities."
    worse_summary = "A shallow tree over compact metadata."
    current_summary = "Transformer embeddings with a regularized linear head. COMPLETE_END."
    _write_round(tmp_path, _round_result(
        round_num=0,
        branch="draft",
        score=0.8,
        commit="draft000",
        method_family="sparse_linear",
        method_summary=first_summary,
        components=["word tfidf", "character tfidf", "draft", "test_state"],
    ), higher_is_better=True)
    _write_round(tmp_path, _round_result(
        round_num=1,
        branch="draft",
        score=0.4,
        commit="draft111",
        method_family="metadata_tree",
        method_summary=worse_summary,
        components=["metadata", "tree"],
    ), higher_is_better=True)
    update = _write_round(tmp_path, _round_result(
        round_num=2,
        branch="draft",
        score=0.7,
        commit="draft222",
        method_family="embedding_linear",
        method_summary=current_summary,
        components=["transformer embeddings", "linear head"],
    ), higher_is_better=True)

    assert update["memory_diff_path"] == "memory_bank/diffs/round_002_vs_draft_0.md"
    diff_text = (tmp_path / update["memory_diff_path"]).read_text(encoding="utf-8")
    assert "schema_version: draft_method_diff_v1" in diff_text
    assert "reference_round: 0" in diff_text
    assert "better_round: 0" in diff_text
    assert f"current_method_summary: {current_summary}" in diff_text
    assert "COMPLETE_END." in diff_text
    assert "current_only_components: embedding_linear, transformer embeddings, linear head" in diff_text
    assert "test_state" not in diff_text.split("## Method Comparison", 1)[1]
    index_rows = [json.loads(line) for line in (tmp_path / "memory_bank" / "card_index.jsonl").read_text().splitlines()]
    current_index = next(row for row in index_rows if row["round"] == 2)
    assert current_index["diff_kind"] == "draft_vs_best_prior_draft"
    assert current_index["comparison_round"] == 0
    assert current_index["comparison_score"] == 0.8
    assert current_index["metric_aligned_delta_vs_parent"] is None

    high_level = (tmp_path / "memory_bank" / "high_level_memory.md").read_text(encoding="utf-8")
    assert "schema_version: high_level_memory_v2" in high_level
    assert "draft_r0_over_r2" in high_level
    assert "better_score: 0.8" in high_level
    assert "worse_score: 0.7" in high_level
    assert first_summary in high_level
    assert current_summary in high_level
    negative = high_level.split("## Negative Experiences", 1)[1]
    assert "- None yet." in negative


def test_lower_is_better_draft_comparison_orients_positive_experience(tmp_path) -> None:
    _write_round(tmp_path, _round_result(
        round_num=0,
        branch="draft",
        score=0.30,
        commit="draft000",
        method_family="baseline",
        method_summary="Baseline method.",
        components=["baseline"],
    ), higher_is_better=False)
    update = _write_round(tmp_path, _round_result(
        round_num=1,
        branch="draft",
        score=0.20,
        commit="draft111",
        method_family="improved",
        method_summary="Improved lower-loss method.",
        components=["improved"],
    ), higher_is_better=False)

    diff_text = (tmp_path / update["memory_diff_path"]).read_text(encoding="utf-8")
    assert "metric_direction: lower" in diff_text
    assert "metric_aligned_delta: 0.09999999999999998" in diff_text
    assert "better_round: 1" in diff_text
    high_level = (tmp_path / update["high_level_memory_path"]).read_text(encoding="utf-8")
    assert "draft_r1_over_r0" in high_level
    assert "better_aligned_margin: 0.09999999999999998" in high_level


def test_best_prior_draft_tie_uses_earliest_round(tmp_path) -> None:
    for round_num, score in ((0, 0.8), (1, 0.8), (2, 0.7)):
        update = _write_round(tmp_path, _round_result(
            round_num=round_num,
            branch="draft",
            score=score,
            commit=f"draft{round_num}",
            method_family=f"family_{round_num}",
            method_summary=f"Method {round_num}.",
            components=[f"component_{round_num}"],
        ), higher_is_better=True)

    assert update["memory_diff_path"] == "memory_bank/diffs/round_002_vs_draft_0.md"


def test_equal_or_unscored_draft_does_not_create_high_level_experience(tmp_path) -> None:
    _write_round(tmp_path, _round_result(
        round_num=0,
        branch="draft",
        score=0.5,
        commit="draft000",
        method_family="family_a",
        method_summary="Method A.",
        components=["a"],
    ), higher_is_better=True)
    equal_update = _write_round(tmp_path, _round_result(
        round_num=1,
        branch="draft",
        score=0.5,
        commit="draft111",
        method_family="family_b",
        method_summary="Method B.",
        components=["b"],
    ), higher_is_better=True)
    unscored_update = _write_round(tmp_path, _round_result(
        round_num=2,
        branch="draft",
        score=None,
        commit="draft222",
        method_family="family_c",
        method_summary="Method C.",
        components=["c"],
    ), higher_is_better=True)

    assert equal_update["memory_diff_path"] == "memory_bank/diffs/round_001_vs_draft_0.md"
    assert unscored_update["memory_diff_path"] == ""
    high_level = (tmp_path / unscored_update["high_level_memory_path"]).read_text(encoding="utf-8")
    assert high_level.count("- None yet.") == 3


def test_parent_diffs_feed_positive_and_negative_high_level_sections(tmp_path) -> None:
    parent = {
        "role": "validation_best",
        "round": 0,
        "commit": "parent00",
        "status": "success",
        "score": 0.5,
        "card_path": "memory_bank/cards/round_000_parent00.md",
    }
    for round_num, score, commit, action in (
        (1, 0.6, "better11", "added a calibrated blend"),
        (2, 0.4, "worse222", "expanded a noisy feature block"),
    ):
        commit_dir = tmp_path / "commits" / commit
        commit_dir.mkdir(parents=True)
        (commit_dir / "solution.py").write_text("VALUE = 1\n", encoding="utf-8")
        result = _round_result(
            round_num=round_num,
            branch="improve",
            score=score,
            commit=commit,
            method_family="blend",
            method_summary=f"Method for round {round_num}.",
            components=["blend"],
            parent=parent,
            diff_action=action,
            diff_reason="the parent evidence suggested this comparison",
        )
        result["code_path"] = f"commits/{commit}/solution.py"
        _write_round(tmp_path, result, higher_is_better=True)

    high_level_path = tmp_path / "memory_bank" / "high_level_memory.md"
    first = high_level_path.read_text(encoding="utf-8")
    second_rel = rebuild_high_level_memory(tmp_path, task_name="unit-task")
    second = (tmp_path / second_rel).read_text(encoding="utf-8")
    assert first == second
    positive, negative = second.split("## Negative Experiences", 1)
    assert "parent_patch_r1_vs_r0" in positive
    assert "added a calibrated blend" in positive
    assert "parent_patch_r2_vs_r0" in negative
    assert "expanded a noisy feature block" in negative
    assert second.count("parent_patch_r1_vs_r0") == 1

    malformed = tmp_path / "memory_bank" / "diffs" / "malformed.md"
    malformed.write_text("# Unsupported Diff\n\n## Meta\n- schema_version: unknown\n", encoding="utf-8")
    rebuilt = tmp_path / rebuild_high_level_memory(tmp_path, task_name="unit-task")
    assert rebuilt.read_text(encoding="utf-8") == second


def test_successful_debug_recovery_feeds_debug_experiences(tmp_path) -> None:
    parent = {
        "role": "debug_parent",
        "round": 0,
        "commit": "failed00",
        "status": "code_execution_error",
        "score": None,
        "card_path": "memory_bank/cards/round_000_failed00.md",
    }
    commit = "repaired1"
    commit_dir = tmp_path / "commits" / commit
    commit_dir.mkdir(parents=True)
    (commit_dir / "solution.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = _round_result(
        round_num=1,
        branch="debug",
        score=0.8193,
        commit=commit,
        method_family="repaired_route",
        method_summary="The repaired parent route.",
        components=["safe parser"],
        parent=parent,
        diff_action="replaced the invalid parser and preserved the trained route",
        diff_reason="the parent failed before training because supplemental rows were malformed",
    )
    result["code_path"] = f"commits/{commit}/solution.py"
    update = _write_round(tmp_path, result, higher_is_better=True)

    high_level = (tmp_path / update["high_level_memory_path"]).read_text(encoding="utf-8")
    positive, remainder = high_level.split("## Negative Experiences", 1)
    negative, debug = remainder.split("## Debug Experiences", 1)
    assert "debug_recovery_r1_from_r0" not in positive
    assert "debug_recovery_r1_from_r0" not in negative
    assert "debug_recovery_r1_from_r0" in debug
    assert "comparison_type: debug_recovery" in debug
    assert "parent_status: code_execution_error" in debug
    assert "parent_score: unknown" in debug
    assert "current_status: success" in debug
    assert "current_score: 0.8193" in debug
    assert "replaced the invalid parser" in debug
    assert "supplemental rows were malformed" in debug
