from __future__ import annotations

import asyncio

import runtime.validation as validation
from runtime.constants import CodexCliError, V4_MAX_STATIC_GATE_REPAIR_ATTEMPTS
from runtime.validation import inspect_solution_contract, repair_static_gate_failure


def _trained_solution() -> str:
    return '''from __future__ import annotations
import os
import pandas as pd
from sklearn.linear_model import LogisticRegression

data_dir = os.environ.get("DATA_DIR")
model = LogisticRegression()
model.fit([[0.0], [1.0]], [0, 1])
submission = pd.read_csv(os.path.join(data_dir, "sample_submission.csv"))
submission["prediction"] = model.predict_proba([[0.0]] * len(submission))[:, 1]
assert submission.shape[0] > 0
submission.to_csv("submission.csv", index=False)
'''


def test_legacy_internal_deadline_scaffolding_does_not_affect_contract() -> None:
    base = inspect_solution_contract(_trained_solution())
    legacy_code = _trained_solution() + '''
import time
VALIDATION_TIMEOUT_SECONDS = 999999
SOLUTION_INTERNAL_BUDGET_SECONDS = 999999
deadline = time.time() + SOLUTION_INTERNAL_BUDGET_SECONDS
if time.time() >= deadline:
    raise RuntimeError("BudgetExhausted")
'''
    legacy = inspect_solution_contract(legacy_code)

    assert legacy["checks"] == base["checks"]
    assert legacy["blockers"] == base["blockers"]
    assert legacy["status"] == base["status"]
    assert "runtime_budget" not in legacy
    assert not any("budget" in name or "deadline" in name for name in legacy["checks"])


def test_external_timeout_constant_does_not_affect_contract() -> None:
    base = inspect_solution_contract(_trained_solution())
    contract = inspect_solution_contract(_trained_solution() + "\nVALIDATION_TIMEOUT_SECONDS = 999999\n")

    assert contract == base


def test_high_cost_score_first_report_has_no_removed_budget_dependency() -> None:
    code = _trained_solution() + '''
import torch
from torch.utils.data import DataLoader
IMAGE_SIZE = 384
EPOCHS = 4
'''

    contract = inspect_solution_contract(
        code,
        search_state="score_first_timeout_recovery",
        strict_score_first_required=True,
    )

    assert "score_first_envelope" in contract
    assert "effective_budget_seconds" not in contract["score_first_envelope"]


def test_real_hard_safety_failure_still_blocks_with_legacy_timer_code() -> None:
    code = (_trained_solution() + "\nVALIDATION_TIMEOUT_SECONDS = 999999\n").replace(
        'data_dir = os.environ.get("DATA_DIR")',
        'data_dir = "input"',
    )
    contract = inspect_solution_contract(code)

    assert "uses_data_dir_env" in contract["blockers"]
    assert not any("budget" in name or "deadline" in name for name in contract["soft_warnings"])
    assert contract["submission_eligible"] is False
    assert contract["status"] == "block"


def test_static_gate_allows_many_large_model_hyperparameters() -> None:
    hyperparameters = "\n".join(
        f"WORD_MAX_FEATURES_{index} = {100_000 + index * 10_000}"
        for index in range(30)
    )
    code = _trained_solution() + "\nSEED = 20260713\n" + hyperparameters

    contract = inspect_solution_contract(code)

    assert contract["checks"]["avoids_hardcoded_data_cardinality"] is True
    assert contract["hardcoded_data_cardinality_evidence"] == []
    assert "few_large_public_constants" not in contract["checks"]
    assert contract["blockers"] == []


def test_static_gate_blocks_named_fixed_data_cardinality_with_evidence() -> None:
    code = _trained_solution() + "\nEXPECTED_TEST_ROWS = 153164\n"

    contract = inspect_solution_contract(code)

    assert contract["checks"]["avoids_hardcoded_data_cardinality"] is False
    assert contract["blockers"] == ["avoids_hardcoded_data_cardinality"]
    assert contract["hardcoded_data_cardinality_evidence"][0]["kind"] == "fixed_cardinality_assignment"
    assert contract["hardcoded_data_cardinality_evidence"][0]["name"] == "EXPECTED_TEST_ROWS"
    assert contract["hardcoded_data_cardinality_evidence"][0]["value"] == 153164


def test_static_gate_blocks_exact_literal_cardinality_comparisons() -> None:
    code = _trained_solution() + "\nassert len(test_df) == 153164\nassert submission.shape[0] != 153164\n"

    contract = inspect_solution_contract(code)

    assert contract["checks"]["avoids_hardcoded_data_cardinality"] is False
    assert [item["kind"] for item in contract["hardcoded_data_cardinality_evidence"]] == [
        "exact_cardinality_comparison",
        "exact_cardinality_comparison",
    ]
    assert [item["name"] for item in contract["hardcoded_data_cardinality_evidence"]] == [
        "len(test_df)",
        "submission.shape[0]",
    ]


def test_static_gate_allows_general_row_caps() -> None:
    code = _trained_solution() + """
MAX_TRAIN_ROWS = 100000
if len(train_df) > MAX_TRAIN_ROWS:
    train_df = train_df.sample(MAX_TRAIN_ROWS, random_state=1)
"""

    contract = inspect_solution_contract(code)

    assert contract["checks"]["avoids_hardcoded_data_cardinality"] is True
    assert contract["hardcoded_data_cardinality_evidence"] == []


def test_static_gate_has_two_same_round_repair_attempts() -> None:
    assert V4_MAX_STATIC_GATE_REPAIR_ATTEMPTS == 2


def test_draft_repair_keeps_complete_current_solution_as_only_base(tmp_path, monkeypatch) -> None:
    current_code = _trained_solution() + "\n# CURRENT_ROUND_UNIQUE_METHOD_MARKER\n" + ("# detail\n" * 2000)
    repaired_code = current_code.replace(
        "LogisticRegression()",
        "LogisticRegression(C=0.8)",
    )
    solution_path = tmp_path / "solution.py"
    solution_path.write_text(current_code, encoding="utf-8")
    observed: dict[str, str] = {}

    async def fake_call_codex_cli(**kwargs):
        observed["gate_context"] = kwargs["refinement_context"]
        observed["current_file"] = solution_path.read_text(encoding="utf-8")
        solution_path.write_text(repaired_code, encoding="utf-8")
        return "repaired", {"input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(validation, "call_codex_cli", fake_call_codex_cli)
    returned, response, usage = asyncio.run(repair_static_gate_failure(
        work_dir=tmp_path,
        prompt_messages=[],
        metadata={"branch": "draft"},
        model="test-model",
        reasoning_level="low",
        max_tokens=100,
        temperature=0.0,
        trace_file=tmp_path / "trace.json",
        refinement_context="round context",
        skill_context=None,
        code=current_code,
        solution_contract={"status": "block", "blockers": ["uses_data_dir_env"]},
    ))

    assert observed["current_file"] == current_code
    assert "CURRENT_ROUND_UNIQUE_METHOD_MARKER" in observed["current_file"]
    assert "[DRAFT REPAIR LINEAGE GUARD]" in observed["gate_context"]
    assert "only implementation base" in observed["gate_context"]
    assert "Do not inspect, copy, or reconstruct from commits/" in observed["gate_context"]
    assert "Only entries in solution_contract.blockers are repair targets." in observed["gate_context"]
    assert "Do not change code to address solution_contract.missing" in observed["gate_context"]
    assert "[PREVIOUS SOLUTION SNIPPET]" not in observed["gate_context"]
    assert "CURRENT SOLUTION EXCERPT" not in observed["gate_context"]
    assert "CURRENT_ROUND_UNIQUE_METHOD_MARKER" not in observed["gate_context"]
    assert returned == repaired_code
    assert response == "repaired"
    assert usage == {"input_tokens": 1, "output_tokens": 1}


def test_repair_restores_current_solution_when_agent_deletes_it(tmp_path, monkeypatch) -> None:
    current_code = _trained_solution()
    solution_path = tmp_path / "solution.py"
    solution_path.write_text(current_code, encoding="utf-8")

    async def fake_call_codex_cli(**kwargs):
        solution_path.unlink()
        return "No code was written.", {"input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(validation, "call_codex_cli", fake_call_codex_cli)
    returned, _, _ = asyncio.run(repair_static_gate_failure(
        work_dir=tmp_path,
        prompt_messages=[],
        metadata={"branch": "draft"},
        model="test-model",
        reasoning_level="low",
        max_tokens=100,
        temperature=0.0,
        trace_file=tmp_path / "trace.json",
        refinement_context=None,
        skill_context=None,
        code=current_code,
        solution_contract={"status": "block", "blockers": ["uses_data_dir_env"]},
    ))

    assert returned == current_code
    assert solution_path.read_text(encoding="utf-8") == current_code


def test_repair_restores_current_solution_when_cli_fails(tmp_path, monkeypatch) -> None:
    current_code = _trained_solution()
    solution_path = tmp_path / "solution.py"
    solution_path.write_text(current_code, encoding="utf-8")

    async def fake_call_codex_cli(**kwargs):
        solution_path.unlink()
        raise CodexCliError(
            "repair failed",
            failure_type="llm_cli_error",
            return_code=1,
            stderr="failed",
            usage={"input_tokens": 1, "output_tokens": 0},
        )

    monkeypatch.setattr(validation, "call_codex_cli", fake_call_codex_cli)
    try:
        asyncio.run(repair_static_gate_failure(
            work_dir=tmp_path,
            prompt_messages=[],
            metadata={"branch": "draft"},
            model="test-model",
            reasoning_level="low",
            max_tokens=100,
            temperature=0.0,
            trace_file=tmp_path / "trace.json",
            refinement_context=None,
            skill_context=None,
            code=current_code,
            solution_contract={"status": "block", "blockers": ["uses_data_dir_env"]},
        ))
    except CodexCliError:
        pass
    else:
        raise AssertionError("expected repair infrastructure failure")

    assert solution_path.read_text(encoding="utf-8") == current_code
