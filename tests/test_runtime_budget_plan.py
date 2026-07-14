from __future__ import annotations

import pytest

from runtime.branch_policy import compute_validation_timeout
from runtime.constants import (
    BRANCH_STATE_TIMEOUT_RECOVERY,
    RUNTIME_PROFILE_TIMEOUT_RECOVERY,
    SearchOperator,
)


def _operator(*, family: str = "custom", cost: str = "medium", description: str = "") -> SearchOperator:
    return SearchOperator(
        name="test_operator",
        intent="test",
        family=family,
        description=description,
        source="unit_test",
        cost=cost,
    )


@pytest.mark.parametrize(
    ("operator", "expected_cap"),
    [
        (_operator(cost="low"), 3600),
        (_operator(), 10800),
        (_operator(family="vision_cnn", cost="high", description="pretrained image model"), 10800),
        (_operator(family="sparse_text", cost="high", description="word and char TF-IDF"), 7200),
    ],
    ids=("low", "general", "deep", "sparse"),
)
def test_external_timeout_uses_workload_profile_cap(operator: SearchOperator, expected_cap: int) -> None:
    assert compute_validation_timeout(50_000, operator) == expected_cap


@pytest.mark.parametrize("remaining", [300, 899, 1800, 5000])
def test_external_timeout_never_exceeds_remaining_sandbox_runtime(remaining: int) -> None:
    timeout = compute_validation_timeout(
        remaining,
        _operator(family="vision_cnn", cost="high", description="pretrained image model"),
    )

    assert timeout == remaining


def test_timeout_recovery_keeps_normal_external_envelope() -> None:
    operator = _operator(family="vision_cnn", cost="high", description="pretrained image model")

    timeout = compute_validation_timeout(
        20_000,
        operator,
        branch_state=BRANCH_STATE_TIMEOUT_RECOVERY,
        runtime_profile=RUNTIME_PROFILE_TIMEOUT_RECOVERY,
    )

    assert timeout == 10800
    assert timeout > 1800


def test_exhausted_sandbox_runtime_has_no_validation_envelope() -> None:
    assert compute_validation_timeout(0, _operator()) == 0
    assert compute_validation_timeout(-1, _operator()) == 0
