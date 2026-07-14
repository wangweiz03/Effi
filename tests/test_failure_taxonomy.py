from __future__ import annotations

from runtime.branch_policy import choose_branch_state_for_round, row_is_timeout
from runtime.validation import classify_validation_failure


def _code_error_row(*, feedback: str, run_time: float, primary: str = "runtime_exception") -> dict:
    return {
        "round": 0,
        "branch": "draft",
        "status": "code_execution_error",
        "code": "print('generated solution')",
        "validation": {
            "status": "code_execution_error",
            "score": None,
            "run_time": run_time,
            "feedback_excerpt": feedback,
            "failure_taxonomy": {"primary": primary},
        },
        "branch_decision": {"validation_timeout_seconds": 7200},
    }


def test_budget_variable_name_does_not_turn_value_error_into_timeout() -> None:
    feedback = """[repro] validation_timeout_seconds=1800 solution_internal_budget_seconds=1500
Traceback (most recent call last):
ValueError: cannot reindex on an axis with duplicate labels
"""

    taxonomy = classify_validation_failure("code_execution_error", feedback)

    assert taxonomy["primary"] == "runtime_exception"
    assert not row_is_timeout(_code_error_row(feedback=feedback, run_time=11.2))


def test_structured_or_event_timeout_remains_timeout() -> None:
    assert classify_validation_failure("timeout", "")["primary"] == "timeout"
    taxonomy = classify_validation_failure(
        "code_execution_error",
        "CANDIDATE_ABORT reason=Internal deadline reached before fold completion",
    )
    assert taxonomy["primary"] == "timeout"
    assert taxonomy["evidence"] == "runtime_event"


def test_legacy_budget_exhausted_trace_is_classified_as_timeout() -> None:
    feedback = "BudgetExhausted: deadline_guard phase=test_predict remaining=-0.2s required>0.0s"
    taxonomy = classify_validation_failure("code_execution_error", feedback)

    assert taxonomy["primary"] == "timeout"
    assert row_is_timeout(_code_error_row(feedback=feedback, run_time=2150.0))


def test_background_inference_and_csv_text_do_not_imply_output_format_failure() -> None:
    feedback = "inference batch complete; writing submission.csv\nRuntimeError: model execution failed"
    taxonomy = classify_validation_failure("code_execution_error", feedback)

    assert taxonomy["primary"] == "runtime_exception"


def test_scheduler_routes_code_error_to_repair_and_real_timeout_to_recovery(tmp_path) -> None:
    fast = _code_error_row(
        feedback="validation_timeout_seconds=1800\nValueError: Fold 2 is empty",
        run_time=4.2,
    )
    repair = choose_branch_state_for_round(
        task_dir=tmp_path,
        round_num=1,
        all_rounds=[fast],
        higher_is_better=True,
        elapsed_fraction=0.1,
        remaining_budget=40_000,
        budget_state={},
        portfolio_state={},
    )
    timed_out = _code_error_row(
        feedback="Sandbox time limit reached",
        run_time=1500.0,
    )
    recovery = choose_branch_state_for_round(
        task_dir=tmp_path,
        round_num=1,
        all_rounds=[timed_out],
        higher_is_better=True,
        elapsed_fraction=0.1,
        remaining_budget=40_000,
        budget_state={},
        portfolio_state={},
    )

    assert repair["branch_state"] == "repair_failure"
    assert recovery["branch_state"] == "timeout_recovery"
