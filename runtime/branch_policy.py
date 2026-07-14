from __future__ import annotations

from .common import *
from .constants import *

def row_is_llm_infra_failure(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    failure_type = str((row.get("llm_failure") or {}).get("failure_type") or "").lower()
    return status in LLM_INFRA_FAILURE_STATUSES or failure_type in LLM_INFRA_FAILURE_STATUSES


def row_is_llm_transient_infra_failure(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    failure_type = str((row.get("llm_failure") or {}).get("failure_type") or "").lower()
    transient_statuses = {"llm_transient_infra", "llm_cli_timeout"}
    return status in transient_statuses or failure_type in transient_statuses


def consecutive_llm_transient_infra_failures(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in reversed(rows):
        if not row_is_llm_transient_infra_failure(row):
            break
        count += 1
    return count


def latest_round_failed(all_rounds: list[dict[str, Any]]) -> bool:
    """Return whether the latest round failed to produce a validation score."""
    if not all_rounds:
        return False
    latest = all_rounds[-1]
    if row_is_llm_infra_failure(latest):
        return False
    if validation_status(latest) in NON_DEBUG_NO_SCORE_STATUSES:
        return False
    return validation_score(latest) is None


def row_has_generated_code(row: dict[str, Any]) -> bool:
    """Return whether a failed round has concrete generated code that debug can repair."""
    code = row.get("code")
    return isinstance(code, str) and bool(code.strip())


def get_round_branch(round_result: dict[str, Any]) -> str:
    """Read branch name from a round result or its branch decision."""
    return normalize_branch_name(str(
        round_result.get("branch")
        or round_result.get("branch_decision", {}).get("branch")
        or ""
    ))


def consecutive_branch_count(all_rounds: list[dict[str, Any]], branch: str) -> int:
    """Count consecutive trailing rounds on a branch."""
    count = 0
    for round_result in reversed(all_rounds):
        if get_round_branch(round_result) != branch:
            break
        count += 1
    return count


def recent_valid_scores(all_rounds: list[dict[str, Any]], limit: int = 3) -> list[float]:
    """Return recent successful validation scores, newest first."""
    scores: list[float] = []
    for round_result in reversed(all_rounds):
        score = validation_score(round_result)
        if score is None:
            continue
        scores.append(score)
        if len(scores) >= limit:
            break
    return scores


def recent_valid_no_best_improvement(
    all_rounds: list[dict[str, Any]],
    best_score: float | None,
    higher_is_better: bool,
    limit: int = 3,
) -> bool:
    """Return whether enough post-best successful rounds failed to strictly improve best."""
    if best_score is None:
        return False
    since_best = successful_rounds_since_best(all_rounds, best_score, higher_is_better)
    if since_best < limit:
        return False
    scores = recent_valid_scores(all_rounds, limit=limit)
    if len(scores) < limit:
        return False
    best_score_float = float(best_score)
    tolerance = max(V4_MATERIAL_SCORE_ABS_DELTA, abs(best_score_float) * V4_MATERIAL_SCORE_REL_DELTA)
    for score in scores:
        if higher_is_better and score > best_score_float + tolerance:
            return False
        if not higher_is_better and score < best_score_float - tolerance:
            return False
    return True


def recent_method_family_counts(all_rounds: list[dict[str, Any]], limit: int = 5) -> Counter[str]:
    """Count method families in recent completed rounds."""
    counts: Counter[str] = Counter()
    seen = 0
    for round_result in reversed(all_rounds):
        family = round_operator_family(round_result)
        if not family:
            continue
        counts[family] += 1
        seen += 1
        if seen >= limit:
            break
    return counts


def repeated_recent_method_family(all_rounds: list[dict[str, Any]], limit: int = 5, threshold: int = 3) -> str | None:
    """Find a repeated recent method family that should be avoided for alternative exploration."""
    counts = recent_method_family_counts(all_rounds, limit=limit)
    if not counts:
        return None
    family, count = counts.most_common(1)[0]
    return family if count >= threshold else None


def round_operator_payload(round_result: dict[str, Any]) -> dict[str, Any]:
    operator = round_result.get("search_operator")
    if not isinstance(operator, dict):
        operator = round_result.get("operator")
    if not isinstance(operator, dict):
        operator = (round_result.get("branch_decision") or {}).get("search_operator")
    return operator if isinstance(operator, dict) else {}


def round_effective_lineage(round_result: dict[str, Any]) -> dict[str, Any]:
    lineage = round_result.get("effective_lineage")
    return lineage if isinstance(lineage, dict) else {}


def round_effective_operator_payload(round_result: dict[str, Any]) -> dict[str, Any]:
    lineage = round_effective_lineage(round_result)
    operator = lineage.get("effective_operator")
    if isinstance(operator, dict) and operator:
        return operator
    operator = round_result.get("effective_operator")
    if isinstance(operator, dict) and operator:
        return operator
    return round_operator_payload(round_result)


def round_operator_name(round_result: dict[str, Any]) -> str:
    return str(round_effective_operator_payload(round_result).get("name") or "").strip()


def operator_anchor_name(name: str | None) -> str:
    """Normalize scheduler wrapper names to the underlying task-skill operator."""
    clean = str(name or "").strip()
    for prefix in ("frontload_draft_", "fresh_draft_", "portfolio_seed_", "portfolio_strengthen_"):
        if clean.startswith(prefix):
            return clean[len(prefix):]
    return clean


def attempted_operator_anchor_names(all_rounds: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for row in all_rounds:
        payloads = [
            round_operator_payload(row),
            round_effective_operator_payload(row),
        ]
        execution = row.get("execution_operator")
        if isinstance(execution, dict):
            payloads.append(execution)
        for payload in payloads:
            name = operator_anchor_name(str(payload.get("name") or ""))
            if name:
                names.add(name)
    return names


def round_operator_family(round_result: dict[str, Any]) -> str:
    return round_effective_method_family(round_result)


def round_effective_method_family(round_result: dict[str, Any]) -> str:
    lineage = round_effective_lineage(round_result)
    family = str(lineage.get("effective_method_family") or round_result.get("effective_method_family") or "").strip()
    if family:
        return canonical_method_family(family)
    family = str((round_result.get("round_summary") or {}).get("method_family") or "").strip()
    if family:
        return canonical_method_family(family)
    payload = round_effective_operator_payload(round_result)
    op = search_operator_from_dict(payload) if payload else None
    return canonical_method_family(str(payload.get("family") or payload.get("method_family") or "").strip(), op)


def round_search_intent(round_result: dict[str, Any]) -> str:
    decision = round_result.get("branch_decision") if isinstance(round_result.get("branch_decision"), dict) else {}
    operator = round_operator_payload(round_result)
    return str(
        decision.get("search_intent")
        or round_result.get("search_intent")
        or operator.get("intent")
        or ""
    ).strip()


def round_effective_search_intent(round_result: dict[str, Any]) -> str:
    lineage = round_effective_lineage(round_result)
    return str(
        lineage.get("effective_search_intent")
        or round_result.get("effective_search_intent")
        or round_search_intent(round_result)
        or ""
    ).strip()


def round_effective_branch(round_result: dict[str, Any]) -> str:
    lineage = round_effective_lineage(round_result)
    return normalize_branch_name(str(
        lineage.get("effective_branch")
        or round_result.get("effective_branch")
        or get_round_branch(round_result)
        or ""
    ))


def build_effective_lineage(
    *,
    round_num: int,
    commit_hash: str | None,
    branch: str,
    branch_decision: dict[str, Any],
    search_operator: SearchOperator,
    round_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the experiment identity used for search statistics and seed tracking.

    A debug round is only a repair execution. If it fixes a failed round, its
    effective identity remains the failed round's operator/family/intent.
    """
    summary = round_summary or {}
    binding = branch_decision.get("parent_binding")
    parent = (
        binding
        if isinstance(binding, dict) and binding.get("role") == "debug_parent"
        else branch_decision.get("debug_parent_fallback")
    )
    actual_operator = search_operator_to_dict(search_operator)
    actual_family = canonical_method_family(summary.get("method_family") or search_operator.family, search_operator)
    if normalize_branch_name(branch) == "debug" and isinstance(parent, dict) and parent:
        parent_lineage = parent.get("effective_lineage") if isinstance(parent.get("effective_lineage"), dict) else {}
        parent_operator = parent_lineage.get("effective_operator")
        if not isinstance(parent_operator, dict) or not parent_operator:
            parent_operator = parent.get("operator") if isinstance(parent.get("operator"), dict) else {}
        if not parent_operator:
            parent_operator = actual_operator
        parent_family = (
            parent_lineage.get("effective_method_family")
            or parent.get("method_family")
            or parent_operator.get("family")
            or actual_family
        )
        parent_intent = (
            parent_lineage.get("effective_search_intent")
            or parent.get("search_intent")
            or parent_operator.get("intent")
            or branch_decision.get("search_intent")
        )
        parent_branch = (
            parent_lineage.get("effective_branch")
            or parent.get("branch")
            or branch
        )
        origin_round = parent_lineage.get("origin_round", parent.get("round"))
        origin_commit = parent_lineage.get("origin_commit", parent.get("commit"))
        seed_id = parent_lineage.get("seed_id") or build_seed_id(origin_round, origin_commit, parent_family, parent_operator)
        return {
            "execution_branch": "debug",
            "execution_search_intent": branch_decision.get("search_intent"),
            "execution_operator": actual_operator,
            "execution_method_family": actual_family,
            "repair_of_round": parent.get("round"),
            "repair_of_commit": parent.get("commit"),
            "repair_failure_primary": parent.get("failure_primary"),
            "effective_branch": normalize_branch_name(str(parent_branch or branch)),
            "effective_search_intent": str(parent_intent or ""),
            "effective_operator": parent_operator,
            "effective_method_family": canonical_method_family(str(parent_family or ""), search_operator_from_dict(parent_operator) if parent_operator else None),
            "origin_round": origin_round,
            "origin_commit": origin_commit,
            "seed_id": seed_id,
            "is_debug_repair": True,
            "is_draft_origin_seed": bool(parent_lineage.get("is_draft_origin_seed") or parent.get("search_intent") in {INTENT_PORTFOLIO_SEED, INTENT_FRONTLOAD_DRAFT, INTENT_FRESH_DRAFT} or parent.get("branch") == "draft"),
        }
    seed_id = build_seed_id(round_num, commit_hash, actual_family, actual_operator)
    return {
        "execution_branch": normalize_branch_name(branch),
        "execution_search_intent": branch_decision.get("search_intent"),
        "execution_operator": actual_operator,
        "execution_method_family": actual_family,
        "effective_branch": normalize_branch_name(branch),
        "effective_search_intent": branch_decision.get("search_intent"),
        "effective_operator": actual_operator,
        "effective_method_family": actual_family,
        "origin_round": round_num,
        "origin_commit": commit_hash,
        "seed_id": seed_id,
        "is_debug_repair": False,
        "is_draft_origin_seed": normalize_branch_name(branch) == "draft",
    }


def build_seed_id(round_num: Any, commit_hash: Any, family: Any, operator: dict[str, Any] | None) -> str:
    op = operator if isinstance(operator, dict) else {}
    if commit_hash:
        return f"seed:{commit_hash}"
    return f"seed:r{round_num}:{canonical_method_family(str(family or op.get('family') or 'unknown'))}:{op.get('name') or 'unknown'}"


def frontload_attempt_count(all_rounds: list[dict[str, Any]]) -> int:
    """Count completed broad-search attempts; failed attempts count, debug repairs do not."""
    count = 0
    for row in all_rounds:
        if round_search_intent(row) in V37_FRONTLOAD_ATTEMPT_INTENTS:
            count += 1
    return count


def frontload_quality_exit_has_fired(all_rounds: list[dict[str, Any]]) -> bool:
    """Return whether initial breadth search was already closed for quality."""
    for row in all_rounds:
        reason = str(row.get("reason") or "").strip()
        if reason.startswith("frontload_quality_exit"):
            return True
    return False


def successful_structural_family_counts(all_rounds: list[dict[str, Any]]) -> Counter[str]:
    """Count scored rounds by real structural family, excluding blend/calibration/control routes."""
    counts: Counter[str] = Counter()
    for row in all_rounds:
        if validation_score(row) is None:
            continue
        family = round_operator_family(row)
        if is_structural_portfolio_family(family):
            counts[family] += 1
    return counts


def round_method_family_components(round_result: dict[str, Any]) -> list[str]:
    """Return concrete structural families covered inside a round's implementation."""
    values: list[Any] = [round_effective_method_family(round_result)]
    components = round_result.get("method_family_components")
    if isinstance(components, list):
        values.extend(components)

    families: list[str] = []
    for value in values:
        family = canonical_method_family(str(value or ""))
        if is_structural_portfolio_family(family) and family not in families:
            families.append(family)
    return families


def covered_family_usage_counts_from_rounds(all_rounds: list[dict[str, Any]]) -> Counter[str]:
    """Count structural method families that were materially covered by scored rounds."""
    counts: Counter[str] = Counter()
    for row in all_rounds:
        if validation_score(row) is None:
            continue
        for family in round_method_family_components(row):
            counts[family] += 1
    return counts


def round_seed_id(round_result: dict[str, Any]) -> str:
    lineage = round_effective_lineage(round_result)
    seed_id = str(lineage.get("seed_id") or round_result.get("seed_id") or "").strip()
    if seed_id:
        return seed_id
    return build_seed_id(
        _round_value(round_result),
        _round_commit(round_result),
        round_effective_method_family(round_result),
        round_effective_operator_payload(round_result),
    )


def is_draft_origin_seed_round(round_result: dict[str, Any]) -> bool:
    lineage = round_effective_lineage(round_result)
    if bool(lineage.get("is_draft_origin_seed")):
        return True
    branch = round_effective_branch(round_result)
    return branch == "draft"


def successful_draft_origin_seed_rows(all_rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one best scored representative per draft-origin structural seed."""
    by_seed: dict[str, dict[str, Any]] = {}
    for row in all_rounds:
        if validation_score(row) is None:
            continue
        if not is_draft_origin_seed_round(row):
            continue
        family = round_effective_method_family(row)
        if not is_structural_portfolio_family(family):
            continue
        seed_id = round_seed_id(row)
        current = by_seed.get(seed_id)
        if current is None:
            by_seed[seed_id] = row
            continue
        # Direction is unknown here; use earlier successful representative for stable identity.
        if _round_value(row) < _round_value(current):
            by_seed[seed_id] = row
    rows = list(by_seed.values())
    rows.sort(key=lambda row: (_round_value(row), _round_commit(row)))
    return rows


def successful_draft_origin_diverse_seed_rows(all_rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one successful draft-origin seed per real structural method family."""
    by_family: dict[str, dict[str, Any]] = {}
    for row in successful_draft_origin_seed_rows(all_rounds):
        family = round_effective_method_family(row)
        if not is_structural_portfolio_family(family):
            continue
        current = by_family.get(family)
        if current is None or _round_value(row) < _round_value(current):
            by_family[family] = row
    rows = list(by_family.values())
    rows.sort(key=lambda row: (_round_value(row), _round_commit(row)))
    return rows


def successful_draft_origin_seed_count(all_rounds: list[dict[str, Any]]) -> int:
    return len(successful_draft_origin_diverse_seed_rows(all_rounds))


def successful_draft_origin_seed_families(all_rounds: list[dict[str, Any]]) -> list[str]:
    return sorted({
        round_effective_method_family(row)
        for row in successful_draft_origin_diverse_seed_rows(all_rounds)
        if round_effective_method_family(row)
    })


def score_worse_by(
    candidate_score: float | None,
    best_score: float | None,
    higher_is_better: bool,
    tolerance: float,
) -> bool:
    """Return whether a scored candidate is materially worse than the current best."""
    if candidate_score is None or best_score is None:
        return False
    if higher_is_better:
        return float(candidate_score) < float(best_score) - tolerance
    return float(candidate_score) > float(best_score) + tolerance


def _score_improvement(candidate_score: float | None, reference_score: float | None, higher_is_better: bool) -> float | None:
    """Positive means candidate is better than reference."""
    if candidate_score is None or reference_score is None:
        return None
    try:
        candidate = float(candidate_score)
        reference = float(reference_score)
    except Exception:
        return None
    return candidate - reference if higher_is_better else reference - candidate


def _score_diag_tolerance(reference_score: float | None) -> float:
    base = abs(float(reference_score)) if isinstance(reference_score, (int, float)) else 1.0
    return max(V4_SCORE_DIAGNOSIS_MATERIAL_ABS_DELTA, base * V4_SCORE_DIAGNOSIS_MATERIAL_REL_DELTA)


def _round_validation_diagnostics(row: dict[str, Any], task_dir: Path | None = None) -> dict[str, Any]:
    diagnostics = row.get("validation_diagnostics")
    if isinstance(diagnostics, dict) and diagnostics:
        return diagnostics
    summary = row.get("round_summary") if isinstance(row.get("round_summary"), dict) else {}
    diagnostics = summary.get("validation_diagnostics") if isinstance(summary, dict) else {}
    if isinstance(diagnostics, dict):
        if diagnostics:
            return diagnostics
    if task_dir is not None:
        commit = _round_commit(row)
        feedback_path = task_dir / "commits" / str(commit) / "validation_feedback.txt" if commit else None
        parser = globals().get("extract_validation_log_diagnostics")
        if feedback_path and feedback_path.exists() and callable(parser):
            try:
                parsed = parser(feedback_path.read_text(encoding="utf-8", errors="replace"), validation_score(row))
            except Exception:
                parsed = {}
            if isinstance(parsed, dict) and parsed:
                return parsed
    if isinstance(diagnostics, dict):
        return diagnostics
    return {}


def _round_identity_for_score_feedback(row: dict[str, Any], score: float | None, task_dir: Path | None = None) -> dict[str, Any]:
    operator = round_effective_operator_payload(row)
    diagnostics = _round_validation_diagnostics(row, task_dir=task_dir)
    return {
        "round": row.get("round"),
        "commit": _round_commit(row),
        "branch": round_effective_branch(row),
        "intent": round_effective_search_intent(row),
        "score": score,
        "method_family": round_effective_method_family(row),
        "operator": operator.get("name"),
        "selected_candidate": diagnostics.get("selected_candidate"),
        "local_metric": diagnostics.get("local_metric"),
        "best_local_score": diagnostics.get("best_local_score"),
        "selected_local_score": diagnostics.get("selected_local_score"),
        "local_validation_gap": diagnostics.get("local_validation_gap"),
        "large_local_validation_gap": diagnostics.get("large_local_validation_gap"),
    }


def build_validation_score_feedback(
    all_rounds: list[dict[str, Any]],
    best_score: float | None,
    higher_is_better: bool,
    task_dir: Path | None = None,
) -> dict[str, Any]:
    """Create a compact, score-centered diagnosis for the next coding prompt.

    This is deliberately advisory, not a static gate. It exists to keep the next
    round focused on why validation score is weak or stagnant instead of only on
    code validity and route bookkeeping.
    """
    scored: list[tuple[int, dict[str, Any], float]] = []
    for idx, row in enumerate(all_rounds):
        score = validation_score(row)
        if score is not None:
            scored.append((idx, row, score))
    if not scored:
        return {
            "status": "no_scored_rounds_yet",
            "required_response": [
                "Build the strongest practical trained candidate; do not optimize around runtime scaffolding alone."
            ],
        }

    latest_idx, latest_row, latest_score = scored[-1]
    previous_scored = scored[:-1]
    previous_best_score = None
    previous_best_row: dict[str, Any] | None = None
    if previous_scored:
        previous_best_idx, previous_best_row, previous_best_score = max(
            previous_scored,
            key=lambda item: score_sort_key(item[2], higher_is_better),
        )
        _ = previous_best_idx
    best_idx, best_row, observed_best_score = max(
        scored,
        key=lambda item: score_sort_key(item[2], higher_is_better),
    )
    _ = best_idx
    reference_best_score = best_score if best_score is not None else observed_best_score
    latest_delta_vs_previous_best = _score_improvement(latest_score, previous_best_score, higher_is_better)
    latest_delta_vs_best = _score_improvement(latest_score, reference_best_score, higher_is_better)
    material_tolerance = _score_diag_tolerance(reference_best_score)
    latest_diag = _round_validation_diagnostics(latest_row, task_dir=task_dir)
    selected_candidate = str(latest_diag.get("selected_candidate") or "").lower()
    issues: list[dict[str, Any]] = []
    required_response: list[str] = []

    local_gap = latest_diag.get("local_validation_gap")
    if (
        latest_diag.get("large_local_validation_gap")
        or (
            isinstance(local_gap, (int, float))
            and float(local_gap) >= V4_SCORE_DIAGNOSIS_LOCAL_GAP_ABS
        )
    ):
        issues.append({
            "type": "local_remote_score_gap",
            "severity": "high",
            "detail": "Local OOF/CV score and remote validation score disagree materially.",
            "gap": local_gap,
        })
        required_response.append(
            "Before adding model complexity, audit validation split, group leakage, row/order alignment, metric direction, selector logic, and final submission mapping."
        )

    if selected_candidate and any(token in selected_candidate for token in ("fallback", "prior", "template", "constant")):
        issues.append({
            "type": "fallback_selected",
            "severity": "high",
            "detail": f"Selected candidate looks like fallback or prior route: {selected_candidate}.",
        })
        required_response.append(
            "Do not treat a fallback/prior selection as a strong seed; make the next round expose or replace the failed trained route."
        )

    latest_identity = _round_identity_for_score_feedback(latest_row, latest_score, task_dir=task_dir)
    route_text = " ".join(
        str(value or "")
        for value in (
            latest_identity.get("method_family"),
            latest_identity.get("operator"),
            round_search_intent(latest_row),
        )
    ).lower()
    affordable_route = any(token in route_text for token in (
        "sparse",
        "text",
        "tfidf",
        "linear",
        "tabular",
        "gbdt",
        "logreg",
        "ridge",
    ))
    sparse_text_route = any(token in route_text for token in ("sparse", "text", "tfidf", "nbsvm", "ngram"))
    min_base_candidates = 4 if sparse_text_route else 3
    base_candidate_count = latest_diag.get("base_candidate_count")
    if (
        affordable_route
        and isinstance(base_candidate_count, int)
        and 0 < base_candidate_count < min_base_candidates
        and validation_score(latest_row) is not None
    ):
        issues.append({
            "type": "underbuilt_affordable_recipe",
            "severity": "medium",
            "detail": "An affordable text/tabular-style route finished with too few independent base candidates.",
            "base_candidate_count": base_candidate_count,
            "min_expected_base_candidates": min_base_candidates,
            "candidate_names": latest_diag.get("candidate_names") or [],
        })
        required_response.append(
            "Expand the current-run mini-portfolio with additional cheap high-ROI base variants before relying on blends: e.g. alternate text views, regularization strengths, NB-SVM/SGD/Ridge/LinearSVC-style margins, train+test-vocabulary variants where target-free and task-appropriate, then OOF rank/weight/stack selection."
        )

    recent_scores = [score for _idx, _row, score in scored[-4:]]
    if len(recent_scores) >= 3:
        recent_best = max(recent_scores) if higher_is_better else min(recent_scores)
        recent_worst = min(recent_scores) if higher_is_better else max(recent_scores)
        spread = abs(float(recent_best) - float(recent_worst))
        if spread <= material_tolerance:
            issues.append({
                "type": "repeated_near_identical_scores",
                "severity": "medium",
                "detail": "Recent scored rounds are effectively tied under the material-score tolerance.",
                "recent_scores": recent_scores,
                "material_tolerance": material_tolerance,
            })
            required_response.append(
                "Make a material route change or a targeted diagnostic ablation; avoid one-knob tweaks that preserve the same prediction behavior."
            )

    if (
        previous_best_score is not None
        and latest_delta_vs_previous_best is not None
        and latest_delta_vs_previous_best < material_tolerance
    ):
        issues.append({
            "type": "latest_not_material_improvement",
            "severity": "medium",
            "detail": "Latest scored round did not materially improve the previous best.",
            "delta_vs_previous_best": latest_delta_vs_previous_best,
            "material_tolerance": material_tolerance,
        })
        if not required_response:
            required_response.append(
                "Explain why the next change can move validation score materially; otherwise switch to a higher-ceiling route."
            )

    if not latest_diag:
        issues.append({
            "type": "missing_candidate_score_diagnostics",
            "severity": "low",
            "detail": "Latest validation log did not expose selected candidate and local/OOF score diagnostics in compact memory.",
        })
        required_response.append(
            "Print a candidate comparison table with selected candidate, local metric, and fallback activation so the following round can reason from evidence."
        )

    return {
        "status": "score_feedback_available",
        "latest": _round_identity_for_score_feedback(latest_row, latest_score, task_dir=task_dir),
        "best": _round_identity_for_score_feedback(best_row, observed_best_score, task_dir=task_dir),
        "previous_best": (
            _round_identity_for_score_feedback(previous_best_row, previous_best_score, task_dir=task_dir)
            if previous_best_row is not None else {}
        ),
        "latest_delta_vs_previous_best": latest_delta_vs_previous_best,
        "latest_delta_vs_current_best": latest_delta_vs_best,
        "material_tolerance": material_tolerance,
        "recent_scores": recent_scores,
        "issues": issues[:4],
        "required_response": required_response[:4],
    }


def latest_failed_seed_repair_count(all_rounds: list[dict[str, Any]]) -> int:
    """Count debug attempts already spent on the latest failed round's seed."""
    if not all_rounds:
        return 0
    latest = all_rounds[-1]
    target_seed = round_seed_id(latest)
    if not target_seed:
        return 0
    count = 0
    for row in all_rounds:
        if get_round_branch(row) != "debug":
            continue
        if round_seed_id(row) == target_seed:
            count += 1
    return count


def recent_operator_counts_from_rounds(
    all_rounds: list[dict[str, Any]],
    limit: int = V35_NOVELTY_RECENT_LIMIT,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    seen = 0
    for round_result in reversed(all_rounds):
        name = round_operator_name(round_result)
        if not name:
            continue
        counts[name] += 1
        seen += 1
        if seen >= limit:
            break
    return counts


def family_usage_counts_from_rounds(all_rounds: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for round_result in all_rounds:
        family = round_operator_family(round_result)
        if family:
            counts[family] += 1
    return counts


def operator_usage_counts_from_rounds(all_rounds: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for round_result in all_rounds:
        name = round_operator_name(round_result)
        if name:
            counts[name] += 1
    return counts


def scored_success_count_for_family(all_rounds: list[dict[str, Any]], family: str) -> int:
    """Count scored rounds that materially covered a concrete method family."""
    canonical = canonical_method_family(str(family or ""))
    if not canonical:
        return 0
    count = 0
    for row in all_rounds:
        if validation_score(row) is None:
            continue
        if canonical in round_method_family_components(row):
            count += 1
    return count


def scored_success_count_for_operator_anchor(all_rounds: list[dict[str, Any]], operator_name: str) -> int:
    """Count scored rounds using the same underlying task-skill operator anchor."""
    anchor = operator_anchor_name(operator_name)
    if not anchor:
        return 0
    count = 0
    for row in all_rounds:
        if validation_score(row) is None:
            continue
        if operator_anchor_name(round_operator_name(row)) == anchor:
            count += 1
    return count


def build_novelty_policy(
    all_rounds: list[dict[str, Any]],
    best_score: float | None,
    higher_is_better: bool,
) -> NoveltyPolicy:
    """Build pre-selection novelty constraints from current search state."""
    if not all_rounds:
        return NoveltyPolicy()

    since_best = successful_rounds_since_best(all_rounds, best_score, higher_is_better)
    no_recent_best_improvement = recent_valid_no_best_improvement(
        all_rounds,
        best_score,
        higher_is_better,
        limit=3,
    )
    recent_operator_counts = recent_operator_counts_from_rounds(all_rounds)
    recent_family_counts = recent_method_family_counts(all_rounds, limit=V35_NOVELTY_RECENT_LIMIT)
    avoid_operators: set[str] = set()
    avoid_families: set[str] = set()
    reasons: list[str] = []

    latest = all_rounds[-1]
    latest_score = validation_score(latest)
    latest_intent = round_effective_search_intent(latest)
    if (
        latest_score is not None
        and since_best > 0
        and latest_intent not in {INTENT_REPAIR_FAILURE, INTENT_SUBMISSION_AUDIT, INTENT_TIMEOUT_SAFE}
    ):
        latest_name = round_operator_name(latest)
        if latest_name:
            avoid_operators.add(latest_name)
            reasons.append(f"latest_non_improving_operator:{latest_name}")

    for name, count in recent_operator_counts.items():
        if count >= V37_OPERATOR_REPEAT_HARD_LIMIT:
            avoid_operators.add(name)
            reasons.append(f"hard_recent_operator_repeated:{name}:{count}")
    for family, count in recent_family_counts.items():
        if family not in {"portfolio_seed", "debug"} and count >= V37_FAMILY_REPEAT_HARD_LIMIT:
            avoid_families.add(family)
            reasons.append(f"hard_recent_family_repeated:{family}:{count}")

    signature_counts: Counter[str] = Counter()
    signature_owner: dict[str, tuple[str, str]] = {}
    for row in reversed(all_rounds[-V35_NOVELTY_RECENT_LIMIT:]):
        signature = (((row.get("validation") or {}).get("experiment_signature") or {}).get("hash") or "")
        if not signature:
            continue
        signature_counts[signature] += 1
        signature_owner.setdefault(signature, (round_operator_name(row), round_operator_family(row)))
    for signature, count in signature_counts.items():
        if count < 2:
            continue
        name, family = signature_owner.get(signature, ("", ""))
        if name:
            avoid_operators.add(name)
        if family:
            avoid_families.add(family)
        reasons.append(f"repeated_validation_signature:{signature[:12]}:{count}")

    if no_recent_best_improvement or since_best >= V31_LOCAL_PLATEAU_AFTER_BEST:
        for name, count in recent_operator_counts.items():
            if count >= V35_NOVELTY_OPERATOR_REPEAT_THRESHOLD:
                avoid_operators.add(name)
                reasons.append(f"recent_operator_repeated:{name}:{count}")
        for family, count in recent_family_counts.items():
            if count >= V35_NOVELTY_FAMILY_REPEAT_THRESHOLD:
                avoid_families.add(family)
                reasons.append(f"recent_family_repeated:{family}:{count}")

    for row in reversed(all_rounds[-V35_NOVELTY_RECENT_LIMIT:]):
        status = validation_status(row)
        if status not in NON_DEBUG_NO_SCORE_STATUSES:
            continue
        name = round_operator_name(row)
        family = round_operator_family(row)
        if name:
            avoid_operators.add(name)
            reasons.append(f"{status}_operator:{name}")
        if family:
            avoid_families.add(family)
            reasons.append(f"{status}_family:{family}")

    return NoveltyPolicy(
        avoid_operators=tuple(sorted(avoid_operators)),
        avoid_families=tuple(sorted(avoid_families)),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def choose_alternative_branch(summary: dict[str, Any]) -> str:
    """Choose the branch used for novelty-seeking rounds."""
    return "improve"


def branch_needs_early_eda(branch: str, early_eda_branches: tuple[str, ...]) -> bool:
    """Run EDA only for explicitly enabled branches; v3 scheduling avoids repeated draft resets."""
    return normalize_branch_name(branch) in set(early_eda_branches)


def round_has_deep_eda(row: dict[str, Any]) -> bool:
    eda = row.get("early_eda") or {}
    return bool(eda.get("enabled")) and str(eda.get("mode") or "") == "deep_bottleneck"


def deep_eda_count(all_rounds: list[dict[str, Any]]) -> int:
    return sum(1 for row in all_rounds if round_has_deep_eda(row))


def round_is_fresh_draft(row: dict[str, Any]) -> bool:
    decision = row.get("branch_decision") or {}
    operator = round_operator_payload(row)
    branch_state = str(row.get("branch_state") or decision.get("branch_state") or "")
    return (
        (get_round_branch(row) == "draft" and branch_state == BRANCH_STATE_PLATEAU_NEW_SEED)
        or
        str(decision.get("search_intent") or "") == INTENT_FRESH_DRAFT
        or str((row.get("search_operator") or {}).get("intent") or "") == INTENT_FRESH_DRAFT
        or str(row.get("search_intent") or "") == INTENT_FRESH_DRAFT
        or str(operator.get("intent") or "") == INTENT_FRESH_DRAFT
    )


def fresh_draft_count(all_rounds: list[dict[str, Any]]) -> int:
    return sum(1 for row in all_rounds if round_is_fresh_draft(row))


def rounds_since_last_fresh_draft(all_rounds: list[dict[str, Any]]) -> int | None:
    for idx, row in enumerate(reversed(all_rounds), start=1):
        if round_is_fresh_draft(row):
            return idx - 1
    return None


def rounds_since_last_deep_eda(all_rounds: list[dict[str, Any]]) -> int | None:
    for idx, row in enumerate(reversed(all_rounds), start=1):
        if round_has_deep_eda(row):
            return idx - 1
    return None


def should_trigger_deep_eda(
    *,
    all_rounds: list[dict[str, Any]],
    since_best: int,
    valid_successes: int,
    no_recent_best_improvement: bool,
    repeated_family: str | None,
    recent_timeouts: int,
    elapsed_fraction: float,
    remaining_budget: float,
) -> tuple[bool, str]:
    """Trigger EDA only when the search is information-starved, not as routine overhead."""
    if valid_successes < V33_DEEP_EDA_MIN_VALID_SUCCESSES:
        return False, "insufficient_valid_history"
    if deep_eda_count(all_rounds) >= V33_MAX_DEEP_EDA_RUNS:
        return False, "deep_eda_budget_exhausted"
    since_last = rounds_since_last_deep_eda(all_rounds)
    if since_last is not None and since_last < V33_DEEP_EDA_COOLDOWN_ROUNDS:
        return False, "deep_eda_cooldown"
    if recent_timeouts >= V31_TIMEOUT_TRAP_RECENT_THRESHOLD:
        return False, "timeout_debug_has_priority"
    if elapsed_fraction >= (1.0 - V3_FINAL_AUDIT_FRACTION) or remaining_budget <= 3600:
        return False, "final_window_or_low_budget"
    if since_best >= V33_DEEP_EDA_AFTER_BEST and no_recent_best_improvement:
        return True, "after_best_plateau_needs_new_data_evidence"
    if repeated_family and no_recent_best_improvement and since_best >= V31_LOCAL_PLATEAU_AFTER_BEST:
        return True, f"repeated_family_{repeated_family}_needs_data_diagnosis"
    return False, "no_bottleneck_signal"


def should_trigger_fresh_draft(
    *,
    all_rounds: list[dict[str, Any]],
    since_best: int,
    valid_successes: int,
    no_recent_best_improvement: bool,
    repeated_family: str | None,
    recent_timeouts: int,
    elapsed_fraction: float,
    remaining_budget: float,
    portfolio_state: dict[str, Any],
) -> tuple[bool, str]:
    """Trigger an independent non-repeating seed before spending a plateau round on deep EDA."""
    if valid_successes < V37_FRESH_DRAFT_MIN_VALID_SUCCESSES:
        return False, "frontload_diverse_portfolio_not_complete"
    if int(portfolio_state.get("candidate_count") or 0) < V36_STRONG_CANDIDATE_COUNT:
        return False, "portfolio_has_too_few_scored_candidates"
    if fresh_draft_count(all_rounds) >= V38_MAX_FRESH_DRAFT_RUNS:
        return False, "fresh_draft_budget_exhausted"
    since_last = rounds_since_last_fresh_draft(all_rounds)
    if since_last is not None and since_last < V37_FRESH_DRAFT_COOLDOWN_ROUNDS:
        return False, "fresh_draft_cooldown"
    if recent_timeouts >= V31_TIMEOUT_TRAP_RECENT_THRESHOLD:
        return False, "timeout_debug_has_priority"
    if elapsed_fraction >= (1.0 - V3_FINAL_AUDIT_FRACTION) or remaining_budget <= V37_FRESH_DRAFT_MIN_REMAINING_BUDGET:
        return False, "final_window_or_low_budget"
    if no_recent_best_improvement and since_best >= V37_FRESH_DRAFT_AFTER_BEST:
        if repeated_family:
            return True, f"plateau_after_best_avoid_repeated_family:{repeated_family}"
        return True, "multi_round_no_best_improvement"
    return False, "no_fresh_draft_signal"


def eda_mode_for_round(branch_decision: dict[str, Any], branch: str, early_eda_branches: tuple[str, ...]) -> str | None:
    explicit = str(branch_decision.get("eda_mode") or "").strip().lower()
    if explicit == "early":
        return explicit
    if explicit == "deep_bottleneck":
        return None
    if explicit in {"none", "false", "skip", "skipped"}:
        return None
    intent = str(branch_decision.get("search_intent") or "")
    information_action = str(branch_decision.get("information_action") or "").strip().lower()
    if information_action in {"deep_eda", "deep_bottleneck"}:
        return None
    if information_action in {"early_eda", "early"}:
        return "early"
    if intent == INTENT_DEEP_EDA:
        return None
    if intent == INTENT_PORTFOLIO_SEED and int(branch_decision.get("round") or 0) == 0:
        return "early"
    if intent in {INTENT_FRONTLOAD_DRAFT, INTENT_FRESH_DRAFT}:
        return None
    if branch_needs_early_eda(branch, early_eda_branches):
        return "early"
    return None


def load_tag_registry(task_dir: Path) -> dict[str, Any]:
    """Load tag registry."""
    registry_file = task_dir / "index" / "tag_registry.json"
    if not registry_file.exists():
        return {}
    return json.loads(registry_file.read_text(encoding="utf-8"))


def successful_rounds_since_best(all_rounds: list[dict[str, Any]], best_score: float | None, higher_is_better: bool) -> int:
    if best_score is None:
        return 0
    best_score_float = float(best_score)
    best_score_tol = max(V4_MATERIAL_SCORE_ABS_DELTA, abs(best_score_float) * V4_MATERIAL_SCORE_REL_DELTA)
    found_best = False
    count = 0
    for row in all_rounds:
        score = validation_score(row)
        if score is None:
            continue
        score_float = score
        if not found_best:
            if abs(score_float - best_score_float) <= best_score_tol:
                found_best = True
            elif score_better(score_float, best_score_float, higher_is_better):
                found_best = True
            continue
        count += 1
    if found_best:
        return count

    count = 0
    for row in reversed(all_rounds):
        score = validation_score(row)
        if score is None:
            continue
        score_float = score
        if score_better(score_float, best_score_float, higher_is_better):
            break
        count += 1
    return count


def consecutive_status_count(all_rounds: list[dict[str, Any]], status: str) -> int:
    count = 0
    for row in reversed(all_rounds):
        if str(row.get("status") or row.get("validation", {}).get("status") or "") != status:
            break
        count += 1
    return count


def validation_status(row: dict[str, Any]) -> str:
    return str(row.get("status") or row.get("validation", {}).get("status") or "").lower()


def row_is_timeout(row: dict[str, Any]) -> bool:
    validation = row.get("validation", {}) if isinstance(row.get("validation"), dict) else {}
    status = validation_status(row)
    score = validation_score(row)
    if score is not None and status == "success":
        return False
    taxonomy = validation.get("failure_taxonomy", {}) or {}
    primary = str(taxonomy.get("primary") or "").lower()
    feedback = "\n".join(str(value or "") for value in (
        validation.get("feedback"),
        validation.get("feedback_excerpt"),
        row.get("feedback"),
        row.get("error_feedback"),
        row.get("error_excerpt"),
    ))
    return score is None and is_actual_timeout_failure(
        status,
        feedback,
        legacy_primary=primary,
    )


def recent_timeout_count(all_rounds: list[dict[str, Any]], limit: int = V31_TIMEOUT_TRAP_RECENT_LIMIT) -> int:
    return sum(1 for row in all_rounds[-limit:] if row_is_timeout(row))


def consecutive_timeout_count(all_rounds: list[dict[str, Any]]) -> int:
    count = 0
    for row in reversed(all_rounds):
        if not row_is_timeout(row):
            break
        count += 1
    return count


def timeout_family_counts(nodes: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in nodes:
        validation = node.get("validation") or {}
        status = str(validation.get("status") or "").lower()
        failure = str(validation.get("failure_primary") or "").lower()
        if "timeout" not in status and "timeout" not in failure:
            continue
        family = (node.get("method") or {}).get("family_canonical") or (node.get("operator") or {}).get("family")
        if family:
            counts[str(family)] += 1
    return counts


def timeout_operator_counts(nodes: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in nodes:
        validation = node.get("validation") or {}
        status = str(validation.get("status") or "").lower()
        failure = str(validation.get("failure_primary") or "").lower()
        if "timeout" not in status and "timeout" not in failure:
            continue
        name = (node.get("operator") or {}).get("name")
        if name:
            counts[str(name)] += 1
    return counts


def summarize_round_outcomes(all_rounds: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = len(all_rounds)
    successful_validations = sum(1 for row in all_rounds if validation_score(row) is not None)
    timeout_count = sum(1 for row in all_rounds if row_is_timeout(row))
    no_solution_count = sum(1 for row in all_rounds if validation_status(row) == "no_solution")
    static_gate_blocked_count = sum(1 for row in all_rounds if validation_status(row) == "static_gate_blocked")
    duplicate_solution_count = sum(1 for row in all_rounds if validation_status(row) == DUPLICATE_SOLUTION_STATUS)
    deep_eda_rounds = deep_eda_count(all_rounds)
    failed_validations = attempts - successful_validations
    return {
        "attempts": attempts,
        "successful_validations": successful_validations,
        "failed_or_non_scored_attempts": failed_validations,
        "timeout_count": timeout_count,
        "no_solution_count": no_solution_count,
        "static_gate_blocked_count": static_gate_blocked_count,
        "duplicate_solution_count": duplicate_solution_count,
        "deep_eda_rounds": deep_eda_rounds,
    }


def operator_usage_counts(nodes: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in nodes:
        name = (node.get("operator") or {}).get("name")
        if name:
            counts[str(name)] += 1
    return counts


def family_usage_counts(nodes: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in nodes:
        family = (node.get("method") or {}).get("family_canonical") or (node.get("operator") or {}).get("family")
        if family:
            counts[str(family)] += 1
    return counts


def select_operator_for_round(
    task_dir: Path,
    task_name: str,
    task_skills_dir: Path,
    desired_intent: str,
    elapsed_fraction: float,
    remaining_budget: float,
    all_rounds: list[dict[str, Any]],
    higher_is_better: bool,
    novelty_policy: NoveltyPolicy | None = None,
    portfolio_state: dict[str, Any] | None = None,
) -> SearchOperator:
    operators = extract_skill_operators(task_name, task_skills_dir)
    nodes = load_graph_nodes(task_dir)
    novelty_policy = novelty_policy or NoveltyPolicy()
    op_counts = operator_usage_counts_from_rounds(all_rounds) if all_rounds else operator_usage_counts(nodes)
    fam_counts = family_usage_counts_from_rounds(all_rounds) if all_rounds else family_usage_counts(nodes)
    covered_fam_counts = covered_family_usage_counts_from_rounds(all_rounds)
    attempted_anchor_ops = attempted_operator_anchor_names(all_rounds)
    timeout_ops = timeout_operator_counts(nodes)
    timeout_fams = timeout_family_counts(nodes)
    timed_out_family_list = ", ".join(sorted(timeout_fams)) or "none"
    valid_scores = [score for score in (validation_score(r) for r in all_rounds) if score is not None]
    timeout_count = sum(1 for row in all_rounds if row_is_timeout(row))
    score_first_timeout_recovery = len(valid_scores) == 0 and timeout_count >= V31_TIMEOUT_TRAP_RECENT_THRESHOLD
    avoid_ops = set(novelty_policy.avoid_operators)
    avoid_anchor_ops = {operator_anchor_name(name) for name in avoid_ops}
    avoid_fams = set(novelty_policy.avoid_families)
    portfolio_state = portfolio_state or {}
    portfolio_family_counts = Counter({
        canonical_method_family(str(k)): int(v)
        for k, v in (portfolio_state.get("family_counts") or {}).items()
    })
    portfolio_covered_family_counts = Counter({
        canonical_method_family(str(k)): int(v)
        for k, v in (portfolio_state.get("covered_family_counts") or {}).items()
    })
    used_families = {
        family
        for family, count in (
            fam_counts
            + portfolio_family_counts
        ).items()
        if count > 0
    }
    structural_family_counts = successful_structural_family_counts(all_rounds)
    portfolio_structural_family_counts = Counter({
        canonical_method_family(str(k)): int(v)
        for k, v in (portfolio_state.get("structural_family_counts") or {}).items()
        if is_structural_portfolio_family(str(k))
    })
    structural_family_count = len(set(structural_family_counts) | set(portfolio_structural_family_counts))
    frontload_attempts = frontload_attempt_count(all_rounds)
    frontload_budget_remaining = frontload_attempts < V37_FRONTLOAD_MAX_ATTEMPTS
    repeated_family = repeated_recent_method_family(all_rounds, threshold=V37_FAMILY_REPEAT_HARD_LIMIT)
    hard_diversity = (
        desired_intent in {INTENT_PORTFOLIO_EXPAND, INTENT_FRONTLOAD_DRAFT, INTENT_STRATEGY_REPLACE, INTENT_EXPLORE_ALTERNATIVE, INTENT_FRESH_DRAFT}
        and frontload_budget_remaining
        and (
            bool(portfolio_state.get("diversity_gap"))
            or int(portfolio_state.get("candidate_count") or 0) < V36_STRONG_CANDIDATE_COUNT
            or structural_family_count < V37_MIN_DIVERSE_PORTFOLIO_FAMILIES
            or bool(repeated_family)
        )
    )

    def conflicts_with_novelty(op: SearchOperator) -> bool:
        family = canonical_method_family(op.family, op)
        return (
            op.name in avoid_ops
            or operator_anchor_name(op.name) in avoid_anchor_ops
            or op.family in avoid_fams
            or family in avoid_fams
        )

    def is_late_or_high_risk(op: SearchOperator) -> bool:
        description = (op.description or "").lower()
        return op.risk == "high" or is_late_round_operator(op)

    def is_late_round_operator(op: SearchOperator) -> bool:
        description = (op.description or "").lower()
        return "late round" in description or "pseudo" in description

    def is_incremental_refinement(op: SearchOperator) -> bool:
        text = f"{op.name} {op.family}".lower()
        return any(token in text for token in (
            "calibration", "temperature", "threshold", "clip", "stack", "blend",
            "selector", "ensemble", "postprocess",
        ))

    def is_control_or_repair_family(op: SearchOperator) -> bool:
        return canonical_method_family(op.family, op) in V37_CONTROL_METHOD_FAMILIES

    def is_generic_prior_operator(op: SearchOperator) -> bool:
        return op.family in {"model_prior_freeform", "eda_prior"} or op.source in {
            "v4_model_prior_controller",
            "v4_eda_prior_controller",
        }

    def is_nonstructural_method_family(op: SearchOperator) -> bool:
        return canonical_method_family(op.family, op) in V37_NONSTRUCTURAL_METHOD_FAMILIES

    def family_attempt_count(op: SearchOperator) -> int:
        family = canonical_method_family(op.family, op)
        return max(
            int(fam_counts[op.family] or 0),
            int(fam_counts[family] or 0),
            int(covered_fam_counts[family] or 0),
            int(portfolio_family_counts[family] or 0),
            int(portfolio_covered_family_counts[family] or 0),
        )

    def is_unused_method_family(op: SearchOperator) -> bool:
        family = canonical_method_family(op.family, op)
        return family not in used_families and not is_control_or_repair_family(op)

    def is_unused_structural_method_family(op: SearchOperator) -> bool:
        return (
            is_unused_method_family(op)
            and not is_generic_prior_operator(op)
            and not is_nonstructural_method_family(op)
            and is_structural_portfolio_family(canonical_method_family(op.family, op))
        )

    def is_uncovered_seed_method_family(op: SearchOperator) -> bool:
        """Return whether an operator can count as a genuinely new independent seed."""
        return is_unused_structural_method_family(op) and family_attempt_count(op) == 0

    def is_unattempted_anchor_operator(op: SearchOperator) -> bool:
        return operator_anchor_name(op.name) not in attempted_anchor_ops

    def novelty_filtered(pool: list[SearchOperator]) -> list[SearchOperator]:
        filtered = [op for op in pool if not conflicts_with_novelty(op)]
        return filtered or pool

    def operator_priority(op: SearchOperator, *, reward_new_family: float = 1.0, allow_risk: bool = False) -> tuple[float, ...]:
        return (
            reward_new_family if is_unused_method_family(op) else 0.0,
            0.7 if op.intent == INTENT_EXPLORE_ALTERNATIVE and hard_diversity else 0.0,
            0.5 if op.intent == INTENT_IMPROVE_BEST else 0.35 if op.intent == INTENT_EXPLORE_ALTERNATIVE else 0.2,
            0.45 if op.cost == "low" else 0.2 if op.cost == "medium" else (-0.1 if allow_risk else -0.8),
            0.35 if op.risk == "low" else 0.1 if op.risk == "medium" else (-0.05 if allow_risk else -0.8),
            -1.0 if conflicts_with_novelty(op) else 0.0,
            -0.8 * timeout_ops[op.name],
            -0.5 * timeout_fams[canonical_method_family(op.family, op)],
            -0.45 * op_counts[op.name],
            -0.35 * family_attempt_count(op),
            -0.25 * covered_fam_counts[canonical_method_family(op.family, op)],
        )

    def wrap_stagnation_operator(op: SearchOperator) -> SearchOperator:
        return SearchOperator(
            name=op.name,
            intent=INTENT_STAGNATION_BREAK,
            family=op.family,
            description=(
                "Use this concrete task-skill operator as the plateau-break action. "
                f"Keep it bounded and change one hypothesis relative to the best candidate. Original operator: {op.description}"
            )[:900],
            source=f"runtime_stagnation_controller:{op.source}",
            cost=op.cost,
            risk=op.risk,
        )

    def wrap_fresh_draft_operator(op: SearchOperator) -> SearchOperator:
        return SearchOperator(
            name=f"fresh_draft_{op.name}"[:80],
            intent=INTENT_FRESH_DRAFT,
            family=op.family,
            description=(
                "Create an independent non-repeating draft seed after multi-round no-improvement. "
                "Do not patch or prefill the incumbent; use task contract, existing EDA, memory, and this "
                f"anchor operator to build a new scored frontier candidate. Anchor operator: {op.description}"
            )[:900],
            source=f"v4_fresh_draft_controller:{op.source}",
            cost=op.cost,
            risk=op.risk,
        )

    def wrap_frontload_draft_operator(op: SearchOperator) -> SearchOperator:
        return SearchOperator(
            name=f"frontload_draft_{op.name}"[:80],
            intent=INTENT_FRONTLOAD_DRAFT,
            family=op.family,
            description=(
                "Create an independent frontload breadth-search seed. Do not patch or prefill the incumbent; "
                "use task contract, existing EDA findings, memory, and this anchor operator to build a distinct "
                f"scored candidate. Anchor operator: {op.description}"
            )[:900],
            source=f"v4_frontload_draft_controller:{op.source}",
            cost=op.cost,
            risk=op.risk,
        )

    def wrap_strengthen_operator(op: SearchOperator) -> SearchOperator:
        return SearchOperator(
            name=f"portfolio_strengthen_{op.name}"[:80],
            intent=INTENT_PORTFOLIO_STRENGTHEN,
            family=op.family,
            description=(
                "Use the current best candidate as the validation anchor, then implement a self-contained "
                "bounded strengthening route around this concrete task-skill operator. Compare against the "
                "parent or reproduce its key candidate inside the round when practical; keep the route only "
                f"if local/OOF evidence supports it. Anchor operator: {op.description}"
            )[:1100],
            source=f"v4_portfolio_strengthen_controller:{op.source}",
            cost=op.cost,
            risk=op.risk,
        )

    if desired_intent == INTENT_REPAIR_FAILURE:
        latest = all_rounds[-1] if all_rounds else {}
        latest_failure = (latest.get("validation", {}).get("failure_taxonomy", {}) if latest else {}) or {}
        status = validation_status(latest)
        primary = str(latest_failure.get("primary") or latest.get("failure_primary") or status or "runtime_exception")
        latest_operator = latest.get("operator") or latest.get("execution_operator") or latest.get("effective_operator") or {}
        parent_cost = str(latest_operator.get("cost") or "").lower()
        parent_risk = str(latest_operator.get("risk") or "").lower()
        parent_family = canonical_method_family(str(latest.get("method_family") or latest_operator.get("family") or ""))
        is_runtime_timeout = row_is_timeout(latest) or "timeout" in primary.lower() or "oom" in primary.lower()
        high_value_parent = parent_cost == "high" or parent_risk == "high"
        if high_value_parent and not is_runtime_timeout:
            inherited_family = parent_family or str(latest_operator.get("family") or "high_value_repair")
            inherited_cost = parent_cost if parent_cost in {"low", "medium", "high"} else "high"
            inherited_risk = parent_risk if parent_risk in {"low", "medium", "high"} else "medium"
            return SearchOperator(
                name=f"debug_high_value_{primary}"[:80],
                intent=INTENT_REPAIR_FAILURE,
                family=inherited_family,
                description=(
                    f"Repair the latest {primary} failure for a high-upside parent route ({parent_family or 'unknown family'}). "
                    "Preserve that route, but make it finish exactly one repaired bounded trained primary candidate before optional extras: inspect the parent traceback, "
                    "fix the concrete code/schema/fold/dependency issue, cap folds/features/iterations/epochs/models before expensive library calls, and write a valid submission. "
                    "If the blocker is has_fast_score_first_envelope, move a trained cheap/descriptor/thumbnail/frozen-feature or sharply bounded primary candidate before duplicate scans, "
                    "full-data media prescans, broad candidate tables, CNN/transformer siblings, TTA, ensembles, or other heavy optional tiers. "
                    "Do not run a broad candidate table, wide ensemble, or full optional recipe before the first successful validation score. Later improve rounds can expand a repaired seed."
                )[:1100],
                source="runtime_failure_taxonomy:high_value_route_repair",
                cost=inherited_cost,
                risk=inherited_risk,
            )
        return SearchOperator(
            name=f"debug_{primary}"[:80],
            intent=INTENT_REPAIR_FAILURE,
            family="debug",
            description=f"Repair the latest {primary} failure with the smallest code change; preserve the current method if possible.",
            source="runtime_failure_taxonomy",
            cost="low",
            risk="low",
        )

    if desired_intent == INTENT_TIMEOUT_SAFE:
        if score_first_timeout_recovery:
            return SearchOperator(
                name="score_first_timeout_recovery",
                intent=INTENT_TIMEOUT_SAFE,
                family="runtime_safety",
                description=(
                    "Repeated timeout occurred before any scored validation. The only goal of this repair is to get a valid score fast. "
                    f"Timed-out method families: {timed_out_family_list}. Avoid those families/operators for this round. "
                    "Implement a small trained, schema-safe candidate with hard caps: sampled or downscaled data, one lightweight model, "
                    "short training, no full-resolution/full-data training, no large ensemble, no TTA, and a guaranteed submission.csv. "
                    "After a valid score exists, later rounds may rebuild stronger methods."
                )[:1100],
                source="runtime_timeout_ledger:score_first",
                cost="low",
                risk="low",
            )
        return SearchOperator(
            name="timeout_safe_bounded_family_repair",
            intent=INTENT_TIMEOUT_SAFE,
            family="runtime_safety",
            description=(
                "Recover from timeout by producing a fast trained score-first path before any risky retry, then preserve the failed "
                "parent high-value method family only as a smaller bounded tier: fewer folds/features/iterations/epochs/files/models, "
                "strict early stopping, no unbounded full-data decoding/hashing/embedding before the score-first path, and a guaranteed trained submission. "
                "If this is not the first timeout for the seed, stop preserving expensive details and produce a fast scored trained candidate."
            ),
            source="runtime_timeout_ledger",
            cost="low",
            risk="low",
        )

    if desired_intent == INTENT_SCORE_GAP_AUDIT:
        scored_rows = [row for row in all_rounds if validation_score(row) is not None]
        best_row = max(
            scored_rows,
            key=lambda row: score_sort_key(validation_score(row), higher_is_better),
        ) if scored_rows else {}
        best_operator_payload = round_effective_operator_payload(best_row) if best_row else {}
        best_operator = search_operator_from_dict(best_operator_payload) if best_operator_payload else SearchOperator(
            name="validation_best_route",
            intent=INTENT_SCORE_GAP_AUDIT,
            family=round_effective_method_family(best_row) if best_row else "score_gap_audit",
            description="Audit the validation-best route's local/OOF-to-remote score gap.",
            source="runtime_score_diagnosis",
            cost="low",
            risk="low",
        )
        best_family = round_effective_method_family(best_row) if best_row else canonical_method_family(best_operator.family, best_operator)
        return SearchOperator(
            name=f"score_gap_audit_{operator_anchor_name(best_operator.name)}"[:80],
            intent=INTENT_SCORE_GAP_AUDIT,
            family=best_family or canonical_method_family(best_operator.family, best_operator),
            description=(
                "Use the validation-best candidate as the anchor and diagnose why local OOF/CV evidence overstates or disagrees "
                "with remote validation. Inspect the best code and validation feedback, then audit split construction, group leakage, "
                "row/order alignment, metric direction, candidate selector logic, blend weights, fallback activation, and final submission mapping. "
                "Preserve the anchor route unless the audit proves it is invalid; do not switch to a new task-skill family or add heavy model complexity "
                "before the score gap has a concrete explanation and targeted fix. "
                f"Anchor operator: {best_operator.description}"
            )[:1100],
            source=f"runtime_score_diagnosis:{best_operator.source}",
            cost=best_operator.cost if best_operator.cost in {"low", "medium", "high"} else "low",
            risk="low",
        )

    if desired_intent == INTENT_FRONTLOAD_DRAFT:
        if score_first_timeout_recovery:
            return SearchOperator(
                name="frontload_score_first_timeout_recovery",
                intent=INTENT_FRONTLOAD_DRAFT,
                family="score_first_recovery",
                description=(
                    "Create an independent replacement seed because repeated timeouts produced no score. "
                    f"Timed-out method families: {timed_out_family_list}. Do not reuse them here. "
                    "The seed must be small but trained and valid: inspect schema, preserve sample_submission, use bounded samples/downscaled features/metadata or other cheap representations, "
                    "train one lightweight candidate, write submission.csv, and finish inside the short validation cap. "
                    "This is a scoring foothold, not the final high-score route."
                )[:1100],
                source="v4_frontload_draft_controller:score_first_timeout_recovery",
                cost="low",
                risk="low",
            )
        base_pool = [
            op for op in operators
            if op.intent in {INTENT_EXPLORE_ALTERNATIVE, INTENT_IMPROVE_BEST, INTENT_ABLATE_BEST}
            and timeout_fams[canonical_method_family(op.family, op)] == 0
            and not conflicts_with_novelty(op)
            and not is_control_or_repair_family(op)
            and not is_nonstructural_method_family(op)
        ]
        structural_pool = [
            op for op in base_pool
            if is_uncovered_seed_method_family(op) and is_unattempted_anchor_operator(op)
        ]
        bounded_structural_pool = [
            op for op in structural_pool
            if op.cost != "high" and not is_late_or_high_risk(op)
        ]
        if bounded_structural_pool:
            return wrap_frontload_draft_operator(max(
                bounded_structural_pool,
                key=lambda op: operator_priority(op, reward_new_family=3.0, allow_risk=False),
            ))
        high_upside_structural_pool = [
            op for op in structural_pool
            if not is_late_round_operator(op)
        ]
        if (
            high_upside_structural_pool
            and structural_family_count < V38_REQUIRED_DRAFT_ORIGIN_SEEDS
            and remaining_budget >= (V37_FRESH_DRAFT_MIN_REMAINING_BUDGET * 2)
        ):
            return wrap_frontload_draft_operator(max(
                high_upside_structural_pool,
                key=lambda op: operator_priority(op, reward_new_family=2.4, allow_risk=True),
            ))
        if structural_family_count < V38_REQUIRED_DRAFT_ORIGIN_SEEDS:
            return SearchOperator(
                name="frontload_draft_model_prior_seed",
                intent=INTENT_FRONTLOAD_DRAFT,
                family="model_prior_freeform",
                description=(
                    "Create an independent early breadth-search seed from task contract, existing EDA findings, memory, "
                    "and general ML/Kaggle prior because no safe low/medium-risk uncovered task-skill family is available. "
                    "Prefer a real non-repeating method family, but do not force fake diversity or late/high-risk tricks. "
                    "If the task has one dominant high-ROI family, build a stronger composite candidate in that family: "
                    "multiple compatible variants, OOF candidate table, and a selected blend/stack/calibration when feasible. "
                    "Name the concrete method_family in context_readiness.md before code."
                ),
                source="v4_frontload_draft_controller:model_prior",
                cost="medium",
                risk="medium",
            )
        unattempted_pool = [op for op in base_pool if is_unattempted_anchor_operator(op)]
        if unattempted_pool:
            return wrap_frontload_draft_operator(max(
                unattempted_pool,
                key=lambda op: operator_priority(op, reward_new_family=1.7, allow_risk=True),
            ))
        if base_pool:
            return wrap_frontload_draft_operator(max(
                base_pool,
                key=lambda op: operator_priority(op, reward_new_family=1.4, allow_risk=True),
            ))
        return SearchOperator(
            name="frontload_draft_model_prior_seed",
            intent=INTENT_FRONTLOAD_DRAFT,
            family="model_prior_freeform",
            description=(
                "Create an independent early breadth-search seed from task contract, existing EDA findings, memory, "
                "and general ML/Kaggle prior. This fallback is allowed only during frontload breadth search, and "
                "must name a concrete method family in context_readiness.md before code."
            ),
            source="v4_frontload_draft_controller",
            cost="medium",
            risk="medium",
        )

    if desired_intent == INTENT_FRESH_DRAFT:
        base_pool = [
            op for op in operators
            if op.intent in {INTENT_EXPLORE_ALTERNATIVE, INTENT_IMPROVE_BEST, INTENT_ABLATE_BEST}
            and timeout_fams[canonical_method_family(op.family, op)] == 0
            and not conflicts_with_novelty(op)
        ]
        bounded_base_pool = [
            op for op in base_pool
            if op.cost != "high" and not is_late_or_high_risk(op)
        ]
        structural_pool = [
            op for op in base_pool
            if is_uncovered_seed_method_family(op) and is_unattempted_anchor_operator(op)
        ]
        bounded_structural_pool = [
            op for op in bounded_base_pool
            if is_uncovered_seed_method_family(op) and is_unattempted_anchor_operator(op)
        ]
        if bounded_structural_pool:
            return wrap_fresh_draft_operator(max(
                bounded_structural_pool,
                key=lambda op: operator_priority(op, reward_new_family=2.6, allow_risk=False),
            ))
        high_risk_fresh_is_justified = (
            bool(portfolio_state.get("weak_start"))
            or bool(portfolio_state.get("diversity_gap"))
            or structural_family_count < V37_MIN_DIVERSE_PORTFOLIO_FAMILIES
        )
        if structural_pool and high_risk_fresh_is_justified and remaining_budget >= (V37_FRESH_DRAFT_MIN_REMAINING_BUDGET * 2):
            return wrap_fresh_draft_operator(max(
                structural_pool,
                key=lambda op: operator_priority(op, reward_new_family=2.2, allow_risk=True),
            ))
        if structural_family_count < V38_REQUIRED_DRAFT_ORIGIN_SEEDS or bool(repeated_family):
            return SearchOperator(
                name="fresh_draft_model_prior_seed",
                intent=INTENT_FRESH_DRAFT,
                family="model_prior_freeform",
                description=(
                    "Create an independent post-plateau draft seed from task contract, memory, EDA evidence, and "
                    "general ML/Kaggle prior because task-skill structural anchors are exhausted, repeated, or already represented. "
                    "The agent must name a concrete non-repeating low/medium-risk method_family in context_readiness.md before writing code; "
                    "do not spend this plateau break on expensive deep training unless the scheduler explicitly selected a high-risk operator."
                ),
                source="v4_fresh_draft_controller:model_prior",
                cost="medium",
                risk="medium",
            )
        unattempted_pool = [op for op in bounded_base_pool if is_unattempted_anchor_operator(op)]
        if unattempted_pool:
            return wrap_fresh_draft_operator(max(
                unattempted_pool,
                key=lambda op: operator_priority(op, reward_new_family=1.5, allow_risk=False),
            ))
        return SearchOperator(
            name="fresh_draft_model_prior_seed",
            intent=INTENT_FRESH_DRAFT,
            family="model_prior_freeform",
            description=(
                "Create an independent post-plateau draft seed from task contract, memory, EDA evidence, and "
                "general ML/Kaggle prior because task-skill structural anchors are exhausted or filtered. "
                "The agent must name a concrete new low/medium-risk method family in context_readiness.md before writing code; "
                "do not patch, prefill, blend, calibrate, or only tune the incumbent."
            ),
            source="v4_fresh_draft_controller:model_prior",
            cost="medium",
            risk="medium",
        )

    if desired_intent == INTENT_PORTFOLIO_SEED:
        source_priority = {
            "skill_priorities": 4.0,
            "skill_strategy": 3.0,
            "skill_first_run": 2.0,
            "skill_upgrade_menu": 1.0,
        }
        operator_position = {id(op): idx for idx, op in enumerate(operators)}
        primary_pool = [
            op for op in operators
            if op.intent in {INTENT_IMPROVE_BEST, INTENT_EXPLORE_ALTERNATIVE, INTENT_ABLATE_BEST}
            and timeout_fams[canonical_method_family(op.family, op)] == 0
            and not is_generic_prior_operator(op)
            and not is_control_or_repair_family(op)
            and not is_nonstructural_method_family(op)
        ]
        if primary_pool:
            selected = max(
                primary_pool,
                key=lambda op: (
                    source_priority.get(op.source, 0.0),
                    -operator_position.get(id(op), 9999),
                    0.5 if op.intent == INTENT_IMPROVE_BEST else 0.3 if op.intent == INTENT_EXPLORE_ALTERNATIVE else 0.1,
                    0.25 if op.cost == "medium" else 0.1 if op.cost == "low" else -0.2,
                    0.15 if op.risk == "medium" else 0.05 if op.risk == "low" else -0.1,
                    -op_counts[op.name],
                    -family_attempt_count(op),
                ),
            )
        return SearchOperator(
            name=f"portfolio_seed_{selected.name}"[:80],
            intent=INTENT_PORTFOLIO_SEED,
            family=selected.family,
            description=(
                "Build the strongest first-round candidate around this selected task-skill primary route. "
                "Do not replace a higher-expected-score structural model with an untrained or weak toy baseline, "
                "but if the selected route is expensive, first protect the round with a trained score-first candidate "
                "and then run only a sharply bounded version of the high-value route that can finish inside the validation timeout. "
                "Operationalize the anchor route's named recipe items instead of using one generic representative. "
                "Preserve naturally composite recipes: if the anchor route combines compatible views/components, "
                "include at least one primary candidate that keeps them together in one estimator/pipeline or OOF composite, "
                "rather than replacing the route with only isolated ablations. "
                "Implement the anchor route's faithful core before adding substitute learner families from generic prior; "
                "cheap OOF blend/stack/calibration steps named by the route should be compared when their inputs already exist. "
                "For rich cheap/moderate routes, spend early candidate slots on several faithful joint variants of the primary family "
                "before adding unrelated substitute learners. "
                "Keep optional auxiliary blocks out of at least one pure core candidate, and compare weighted blend plus regularized "
                "stack/calibrator when three or more OOF candidates exist. "
                "For cheap/small-data families, implement several complementary variants from the route; for expensive/large-data "
                "families, write a sequential budget ladder and defer heavy siblings with explicit reasons. "
                f"Anchor operator: {selected.description}"
            )[:1100],
            source=f"v4_portfolio_controller:{selected.source}",
            cost=selected.cost,
            risk=selected.risk,
            )
        return SearchOperator(
            name="portfolio_strong_first_run",
            intent=INTENT_PORTFOLIO_SEED,
            family="portfolio_seed",
            description=(
                "Build the strongest first-round candidate from the task-skill highest-expected-score strategy, not a toy baseline. "
                "Use EDA findings and model prior to implement the main structural route first; include cheap views/models only "
                "as smoke checks, support candidates, or fallbacks, then compare by OOF/local validation and print the candidate table."
            ),
            source="v4_portfolio_controller",
            cost="medium",
            risk="low",
        )

    if desired_intent == INTENT_PORTFOLIO_EXPAND:
        candidate_count = int(portfolio_state.get("candidate_count") or 0)
        early_or_unstable = (
            candidate_count < V36_STRONG_CANDIDATE_COUNT
            or len(valid_scores) < V36_EARLY_RISK_GATE_SUCCESS_LIMIT
            or bool(portfolio_state.get("weak_start"))
            or elapsed_fraction < V3_EXPLORATION_FRACTION
        )
        base_pool = [
            op for op in operators
            if op.intent in {INTENT_EXPLORE_ALTERNATIVE, INTENT_IMPROVE_BEST}
            and op.family not in avoid_fams
            and op.name not in avoid_ops
            and timeout_fams[canonical_method_family(op.family, op)] == 0
        ]
        if hard_diversity:
            fresh_pool = [op for op in base_pool if is_unused_structural_method_family(op)]
            if fresh_pool:
                return max(fresh_pool, key=lambda op: operator_priority(op, reward_new_family=2.4, allow_risk=True))
            fresh_pool = [
                op for op in base_pool
                if is_unused_method_family(op)
                and not is_generic_prior_operator(op)
                and not is_nonstructural_method_family(op)
                and op.cost != "high"
            ]
            if not fresh_pool:
                fresh_pool = [
                    op for op in base_pool
                    if is_unused_method_family(op)
                    and not is_generic_prior_operator(op)
                    and not is_nonstructural_method_family(op)
                ]
            if not fresh_pool:
                fresh_pool = [
                    op for op in base_pool
                    if is_unused_method_family(op) and not is_nonstructural_method_family(op)
                ]
            if fresh_pool:
                return max(fresh_pool, key=lambda op: operator_priority(op, reward_new_family=2.0, allow_risk=True))
            return SearchOperator(
                name=V37_MODEL_PRIOR_OPERATOR_NAME,
                intent=INTENT_PORTFOLIO_EXPAND,
                family="model_prior_freeform",
                description=(
                    "Task-skill structural operators are exhausted or already represented during frontload. "
                    "Use general ML/Kaggle prior to name and implement one concrete structural method family; "
                    "do not satisfy frontload diversity with blend, calibration, pseudo-labeling, or metadata-only diagnostics."
                ),
                source="v4_frontload_controller",
                cost="medium",
                risk="medium",
            )

        pool = [op for op in base_pool if op.cost != "high"]
        if early_or_unstable and not hard_diversity:
            safe_pool = [op for op in pool if not is_late_or_high_risk(op)]
            if safe_pool:
                pool = safe_pool
            primary_pool = [
                op for op in pool
                if op.intent == INTENT_IMPROVE_BEST and not is_incremental_refinement(op)
            ]
            if primary_pool:
                pool = primary_pool
        if not pool:
            pool = [
                op for op in operators
                if op.cost != "high"
                and not conflicts_with_novelty(op)
                and (not early_or_unstable or not is_late_or_high_risk(op))
            ] or [
                op for op in operators
                if op.cost != "high" and (not early_or_unstable or not is_late_or_high_risk(op))
            ] or operators
        if pool:
            return max(pool, key=lambda op: operator_priority(op, reward_new_family=1.4, allow_risk=hard_diversity))
        return SearchOperator(
            name=V37_MODEL_PRIOR_OPERATOR_NAME,
            intent=INTENT_PORTFOLIO_EXPAND,
            family="model_prior_freeform",
            description="Write an independent high-confidence recipe that adds a new real method family to the portfolio and logs its internal comparisons.",
            source="v4_portfolio_controller",
            cost="medium",
            risk="medium",
        )

    if desired_intent == INTENT_PORTFOLIO_STRENGTHEN:
        candidate_count = int(portfolio_state.get("candidate_count") or 0)
        base_pool = [
            op for op in operators
            if op.intent in {INTENT_IMPROVE_BEST, INTENT_ABLATE_BEST, INTENT_ENSEMBLE}
            and timeout_fams[canonical_method_family(op.family, op)] == 0
            and not conflicts_with_novelty(op)
            and not is_generic_prior_operator(op)
            and not is_control_or_repair_family(op)
        ]

        def strengthen_priority(op: SearchOperator) -> tuple[float, ...]:
            return (
                1.0 if op.source == "skill_strategy" else 0.45 if "skill" in op.source else 0.0,
                0.8 if is_unused_structural_method_family(op) else 0.0,
                0.45 if op.intent == INTENT_IMPROVE_BEST else 0.25 if op.intent == INTENT_ENSEMBLE else 0.1,
                0.35 if op.cost == "low" else 0.2 if op.cost == "medium" else -0.4,
                0.25 if op.risk == "low" else 0.1 if op.risk == "medium" else -0.15,
                -0.6 * family_attempt_count(op),
                -0.45 * op_counts[op.name],
            )

        structural_pool = [
            op for op in base_pool
            if op.intent == INTENT_IMPROVE_BEST
            and is_unused_structural_method_family(op)
            and (op.cost != "high" or remaining_budget >= V37_FRESH_DRAFT_MIN_REMAINING_BUDGET)
        ]
        if structural_pool:
            return wrap_strengthen_operator(max(structural_pool, key=strengthen_priority))

        if candidate_count >= 2:
            blend_pool = [
                op for op in base_pool
                if op.intent == INTENT_ENSEMBLE and op.cost != "high"
            ]
            if blend_pool:
                return wrap_strengthen_operator(max(blend_pool, key=strengthen_priority))

        improve_pool = [
            op for op in base_pool
            if op.intent == INTENT_IMPROVE_BEST
            and op.cost != "high"
            and not is_incremental_refinement(op)
        ]
        if improve_pool:
            return wrap_strengthen_operator(max(improve_pool, key=strengthen_priority))

        return SearchOperator(
            name="portfolio_strengthen_best_with_internal_ablation",
            intent=INTENT_PORTFOLIO_STRENGTHEN,
            family="portfolio_strengthen",
            description=(
                "Use the current best candidate as evidence, but run a meaningful in-round ablation/variant table around it. "
                "Keep only changes that improve OOF/local validation or harden the final submission."
            ),
            source="v4_portfolio_controller",
            cost="medium",
            risk="low",
        )

    if desired_intent == INTENT_PORTFOLIO_BLEND:
        return SearchOperator(
            name="portfolio_inround_blend_or_selector",
            intent=INTENT_PORTFOLIO_BLEND,
            family="blend_ensemble",
            description=(
                "Build a robust selector/blend inside this round from cheap comparable candidates, or reproduce a small "
                "set of prior code routes before comparing them. Do not depend on cross-round prediction files."
            ),
            source="v4_portfolio_controller",
            cost="low",
            risk="low",
        )

    if desired_intent == INTENT_STRATEGY_REPLACE:
        structural_pool = [
            op for op in operators
            if op.intent in {INTENT_EXPLORE_ALTERNATIVE, INTENT_IMPROVE_BEST, INTENT_ABLATE_BEST}
            and family_attempt_count(op) == 0
            and timeout_fams[canonical_method_family(op.family, op)] == 0
            and (op.cost != "high" or hard_diversity)
            and not conflicts_with_novelty(op)
            and is_unused_structural_method_family(op)
        ]
        if structural_pool:
            return max(structural_pool, key=lambda op: operator_priority(op, reward_new_family=2.4, allow_risk=True))
        fresh_pool = [
            op for op in operators
            if op.intent in {INTENT_EXPLORE_ALTERNATIVE, INTENT_IMPROVE_BEST, INTENT_ABLATE_BEST}
            and family_attempt_count(op) == 0
            and timeout_fams[canonical_method_family(op.family, op)] == 0
            and (op.cost != "high" or hard_diversity)
            and not conflicts_with_novelty(op)
            and not is_control_or_repair_family(op)
            and not is_generic_prior_operator(op)
        ]
        if not fresh_pool:
            fresh_pool = [
                op for op in operators
                if op.intent in {INTENT_EXPLORE_ALTERNATIVE, INTENT_IMPROVE_BEST}
                and timeout_fams[canonical_method_family(op.family, op)] == 0
                and (op.cost != "high" or hard_diversity)
                and not conflicts_with_novelty(op)
                and not is_control_or_repair_family(op)
                and not is_generic_prior_operator(op)
            ]
        if not fresh_pool:
            fresh_pool = novelty_filtered([
                op for op in operators
                if op.intent in {INTENT_EXPLORE_ALTERNATIVE, INTENT_IMPROVE_BEST, INTENT_ABLATE_BEST}
                and timeout_fams[canonical_method_family(op.family, op)] == 0
                and (op.cost != "high" or hard_diversity)
            ])
        if fresh_pool:
            return max(fresh_pool, key=lambda op: operator_priority(op, reward_new_family=2.0, allow_risk=True))
        return SearchOperator(
            name=V37_MODEL_PRIOR_OPERATOR_NAME,
            intent=INTENT_STRATEGY_REPLACE,
            family="model_prior_freeform",
            description=(
                "Replace the repeated non-improving local family with a bounded distinct recipe from compact task-skill, "
                "EDA, memory, and model prior. Keep runtime caps and a trained fallback."
            ),
            source="v4_runtime_stagnation_controller",
            cost="medium",
            risk="medium",
            )

    if desired_intent == INTENT_STAGNATION_BREAK:
        plateau_pool = [
            op for op in operators
            if op.intent in {INTENT_IMPROVE_BEST, INTENT_ABLATE_BEST, INTENT_ENSEMBLE, INTENT_EXPLORE_ALTERNATIVE}
            and op.cost != "high"
            and timeout_fams[canonical_method_family(op.family, op)] == 0
        ]
        filtered_plateau_pool = [op for op in plateau_pool if not conflicts_with_novelty(op)]
        if filtered_plateau_pool:
            selected = max(
                filtered_plateau_pool,
                key=lambda op: (
                    0.4 if op.intent in {INTENT_IMPROVE_BEST, INTENT_ABLATE_BEST} else 0.2,
                    0.3 if op.risk == "low" else 0.0,
                    -op_counts[op.name],
                    -family_attempt_count(op),
                ),
            )
            return wrap_stagnation_operator(selected)
        return SearchOperator(
            name="portfolio_strengthen_ablation",
            intent=INTENT_STAGNATION_BREAK,
            family="plateau_break",
            description=(
                "Break a local plateau with one targeted ablation or low-risk change that clarifies whether the best candidate "
                "should be strengthened, blended, or replaced by a more diverse portfolio member."
            ),
            source="runtime_stagnation_controller",
            cost="low",
            risk="low",
        )

    if desired_intent == INTENT_DEEP_EDA:
        return SearchOperator(
            name="bottleneck_deep_eda_to_data_driven_route",
            intent=INTENT_DEEP_EDA,
            family="eda_diagnostics",
            description=(
                "Run targeted, resource-bounded EDA because recent validated search is stalled; use the findings to choose "
                "one concrete data-driven modeling, validation, feature, or postprocessing change in this round."
            ),
            source="runtime_bottleneck_controller",
            cost="low",
            risk="low",
        )

    if desired_intent == INTENT_RESET_BASELINE:
        return next((op for op in operators if op.intent == INTENT_RESET_BASELINE), SearchOperator(
            "strong_first_run", INTENT_RESET_BASELINE, "baseline",
            "Execute the skill's strong first implementation plan with strict fallback and a quick valid submission.",
            "runtime_bootstrap", "medium", "low",
        ))

    if desired_intent == INTENT_SUBMISSION_AUDIT:
        return SearchOperator(
            "submission_audit_and_reproduce",
            INTENT_SUBMISSION_AUDIT,
            "audit",
            "Freeze risky modeling changes; reproduce or simplify the best candidate, verify DATA_DIR/schema/submission, and preserve a robust final submission.",
            "runtime_final_audit",
            "low",
            "low",
        )

    if desired_intent == INTENT_ENSEMBLE:
        return next((op for op in operators if op.intent == INTENT_ENSEMBLE), SearchOperator(
            "portfolio_blend", INTENT_ENSEMBLE, "ensemble",
            "Blend or select among top diverse local-CV candidates inside the current round, or reproduce small prior routes from code.",
            "runtime_portfolio", "low", "low",
        ))

    if desired_intent == INTENT_IMPROVE_BEST:
        pool = [op for op in operators if op.intent in {INTENT_IMPROVE_BEST, INTENT_ENSEMBLE}]
    elif desired_intent == INTENT_EXPLORE_ALTERNATIVE:
        pool = [op for op in operators if op.intent == INTENT_EXPLORE_ALTERNATIVE]
        if not pool:
            pool = [op for op in operators if op.intent == INTENT_IMPROVE_BEST and family_attempt_count(op) == 0]
    elif desired_intent == INTENT_ABLATE_BEST:
        pool = [op for op in operators if op.intent == INTENT_ABLATE_BEST]
    else:
        pool = [op for op in operators if op.intent == INTENT_IMPROVE_BEST]
    if not pool:
        pool = operators
    pool = novelty_filtered(pool)

    def op_priority(op: SearchOperator) -> float:
        priority = 1.0
        priority -= 0.25 * op_counts[op.name]
        priority -= 0.15 * family_attempt_count(op)
        priority -= 0.75 * timeout_ops[op.name]
        priority -= 0.45 * timeout_fams[canonical_method_family(op.family, op)]
        if op.cost == "low":
            priority += 0.25
        elif op.cost == "high":
            priority -= 0.35
        if op.risk == "low":
            priority += 0.20
        elif op.risk == "high":
            priority -= 0.35
        if desired_intent == INTENT_EXPLORE_ALTERNATIVE and family_attempt_count(op) == 0:
            priority += 0.45
        if elapsed_fraction > (1.0 - V3_FINAL_AUDIT_FRACTION) and (op.risk != "low" or op.cost == "high"):
            priority -= 1.0
        if remaining_budget < 3600 and op.cost != "low":
            priority -= 1.0
        if len(valid_scores) < 2 and op.intent == INTENT_EXPLORE_ALTERNATIVE:
            priority -= 0.25
        if op.name in avoid_ops:
            priority -= 1.25
        if op.family in avoid_fams:
            priority -= 1.0
        return priority

    return max(pool, key=op_priority)


def choose_v3_policy_state(
    round_num: int,
    all_rounds: list[dict[str, Any]],
    best_score: float | None,
    higher_is_better: bool,
    elapsed_fraction: float,
    remaining_budget: float,
    portfolio_state: dict[str, Any] | None = None,
) -> tuple[str, str, str, str, dict[str, Any]]:
    """Return branch, intent, reason, state, diagnostics for the next v4 portfolio action."""
    portfolio_state = portfolio_state or {}
    since_best = successful_rounds_since_best(all_rounds, best_score, higher_is_better)
    valid_successes = sum(1 for row in all_rounds if validation_score(row) is not None)
    frontload_attempts = frontload_attempt_count(all_rounds)
    structural_success_counts = successful_structural_family_counts(all_rounds)
    portfolio_structural_counts = Counter({
        canonical_method_family(str(k)): int(v)
        for k, v in (portfolio_state.get("structural_family_counts") or {}).items()
        if is_structural_portfolio_family(str(k))
    })
    structural_success_families = sorted(set(structural_success_counts) | set(portfolio_structural_counts))
    structural_success_family_count = len(structural_success_families)
    frontload_attempt_budget_exhausted = frontload_attempts >= V37_FRONTLOAD_MAX_ATTEMPTS
    frontload_quality_exit_persisted = frontload_quality_exit_has_fired(all_rounds)
    all_draft_origin_seed_rows = successful_draft_origin_seed_rows(all_rounds)
    draft_origin_seed_rows = successful_draft_origin_diverse_seed_rows(all_rounds)
    draft_origin_seed_count = len(draft_origin_seed_rows)
    draft_origin_seed_families = successful_draft_origin_seed_families(all_rounds)
    latest_seed_repair_count = latest_failed_seed_repair_count(all_rounds)
    recent_timeouts = recent_timeout_count(all_rounds)
    consecutive_timeouts = consecutive_timeout_count(all_rounds)
    repeated_family = repeated_recent_method_family(all_rounds)
    recent_scores = recent_valid_scores(all_rounds, limit=V31_STAGNATION_RECENT_LIMIT)
    no_recent_best_improvement = recent_valid_no_best_improvement(
        all_rounds,
        best_score,
        higher_is_better,
        limit=min(3, max(1, len(recent_scores))),
    ) if best_score is not None and recent_scores else False
    latest_score = validation_score(all_rounds[-1]) if all_rounds else None
    frontload_quality_exit = False
    frontload_quality_exit_reason = "not_applicable"
    frontload_quality_exit_gap: float | None = None
    frontload_quality_exit_tolerance: float | None = None
    if 0 < draft_origin_seed_count < V38_REQUIRED_DRAFT_ORIGIN_SEEDS:
        frontload_quality_exit_reason = "need_required_draft_origin_seed_count"
        if (
            draft_origin_seed_count >= V4_FRONTLOAD_MIN_SEEDS_BEFORE_QUALITY_EXIT
            and latest_score is not None
            and best_score is not None
        ):
            frontload_quality_exit_tolerance = max(
                V4_FRONTLOAD_QUALITY_EXIT_ABS_GAP,
                abs(float(best_score)) * V4_FRONTLOAD_QUALITY_EXIT_REL_GAP,
            )
            frontload_quality_exit_gap = (
                float(best_score) - float(latest_score)
                if higher_is_better else
                float(latest_score) - float(best_score)
            )
            if score_worse_by(latest_score, best_score, higher_is_better, frontload_quality_exit_tolerance):
                frontload_quality_exit = True
                frontload_quality_exit_reason = "latest_seed_materially_worse_than_best"
    trigger_deep_eda, deep_eda_reason = should_trigger_deep_eda(
        all_rounds=all_rounds,
        since_best=since_best,
        valid_successes=valid_successes,
        no_recent_best_improvement=no_recent_best_improvement,
        repeated_family=repeated_family,
        recent_timeouts=recent_timeouts,
        elapsed_fraction=elapsed_fraction,
        remaining_budget=remaining_budget,
    )
    trigger_fresh_draft, fresh_draft_reason = should_trigger_fresh_draft(
        all_rounds=all_rounds,
        since_best=since_best,
        valid_successes=valid_successes,
        no_recent_best_improvement=no_recent_best_improvement,
        repeated_family=repeated_family,
        recent_timeouts=recent_timeouts,
        elapsed_fraction=elapsed_fraction,
        remaining_budget=remaining_budget,
        portfolio_state=portfolio_state,
    )
    diagnostics = {
        "since_best_successes": since_best,
        "valid_successes": valid_successes,
        "frontload_attempts": frontload_attempts,
        "frontload_max_attempts": V37_FRONTLOAD_MAX_ATTEMPTS,
        "frontload_attempt_budget_exhausted": frontload_attempt_budget_exhausted,
        "frontload_quality_exit": frontload_quality_exit,
        "frontload_quality_exit_persisted": frontload_quality_exit_persisted,
        "frontload_quality_exit_reason": frontload_quality_exit_reason,
        "frontload_quality_exit_gap": frontload_quality_exit_gap,
        "frontload_quality_exit_tolerance": frontload_quality_exit_tolerance,
        "frontload_quality_exit_min_seeds": V4_FRONTLOAD_MIN_SEEDS_BEFORE_QUALITY_EXIT,
        "successful_draft_origin_seed_count": draft_origin_seed_count,
        "successful_draft_origin_seed_total": len(all_draft_origin_seed_rows),
        "required_draft_origin_seeds": V38_REQUIRED_DRAFT_ORIGIN_SEEDS,
        "successful_draft_origin_seed_families": draft_origin_seed_families,
        "latest_failed_seed_repair_count": latest_seed_repair_count,
        "max_debug_repairs_per_seed": V38_MAX_DEBUG_REPAIRS_PER_SEED,
        "plateau_scored_rounds_before_new_draft": V38_PLATEAU_SCORED_ROUNDS_BEFORE_NEW_DRAFT,
        "structural_success_family_count": structural_success_family_count,
        "structural_success_families": structural_success_families,
        "structural_success_target": V37_MIN_DIVERSE_PORTFOLIO_FAMILIES,
        "recent_timeouts": recent_timeouts,
        "consecutive_timeouts": consecutive_timeouts,
        "repeated_method_family": repeated_family,
        "recent_valid_scores": recent_scores,
        "no_recent_best_improvement": no_recent_best_improvement,
        "deep_eda_count": deep_eda_count(all_rounds),
        "rounds_since_last_deep_eda": rounds_since_last_deep_eda(all_rounds),
        "deep_eda_reason": deep_eda_reason,
        "fresh_draft_count": fresh_draft_count(all_rounds),
        "rounds_since_last_fresh_draft": rounds_since_last_fresh_draft(all_rounds),
        "fresh_draft_reason": fresh_draft_reason,
        "remaining_budget": remaining_budget,
        "elapsed_fraction": elapsed_fraction,
        "portfolio": {
            "candidate_count": portfolio_state.get("candidate_count", 0),
            "best_score": portfolio_state.get("best_score"),
            "family_counts": portfolio_state.get("family_counts") or {},
            "structural_family_counts": portfolio_state.get("structural_family_counts") or {},
            "structural_family_count": portfolio_state.get("structural_family_count"),
            "successful_draft_origin_seed_count": portfolio_state.get("successful_draft_origin_seed_count", 0),
            "successful_draft_origin_seed_total": portfolio_state.get("successful_draft_origin_seed_total", 0),
            "required_draft_origin_seeds": portfolio_state.get("required_draft_origin_seeds", V38_REQUIRED_DRAFT_ORIGIN_SEEDS),
            "successful_draft_origin_seed_families": portfolio_state.get("successful_draft_origin_seed_families") or [],
            "diversity_gap": bool(portfolio_state.get("diversity_gap")),
            "weak_start": bool(portfolio_state.get("weak_start")),
        },
    }
    if round_num == 0:
        return "draft", INTENT_PORTFOLIO_SEED, "bootstrap_portfolio_strong_first_run", STATE_PORTFOLIO_SEED, diagnostics
    latest_round = all_rounds[-1] if all_rounds else {}
    latest_status = validation_status(latest_round) if latest_round else ""
    if latest_status == "static_gate_blocked" and row_has_generated_code(latest_round):
        if latest_seed_repair_count < V38_MAX_DEBUG_REPAIRS_PER_SEED:
            return "debug", INTENT_REPAIR_FAILURE, "debug_static_gate_blocked", STATE_DEBUG_REPAIR, diagnostics
        if draft_origin_seed_count < V38_REQUIRED_DRAFT_ORIGIN_SEEDS:
            return (
                "draft",
                INTENT_FRONTLOAD_DRAFT,
                "static_gate_debug_budget_exhausted_collect_new_seed",
                STATE_FRONTLOAD_DRAFT,
                diagnostics,
            )
        return (
            "improve",
            INTENT_STRATEGY_REPLACE,
            "static_gate_debug_budget_exhausted_replace_route",
            STATE_STRATEGY_REPLACE,
            diagnostics,
        )
    if latest_status in NON_DEBUG_NO_SCORE_STATUSES:
        if latest_status in PARENTLESS_NON_DEBUG_STATUSES and draft_origin_seed_count < V38_REQUIRED_DRAFT_ORIGIN_SEEDS:
            return (
                "draft",
                INTENT_FRONTLOAD_DRAFT,
                f"parentless_failure_collect_new_seed:{latest_status}",
                STATE_FRONTLOAD_DRAFT,
                diagnostics,
            )
        return "improve", INTENT_STRATEGY_REPLACE, f"failed_information_gain_replace:{latest_status}", STATE_STRATEGY_REPLACE, diagnostics
    if latest_round_failed(all_rounds):
        if valid_successes == 0 and consecutive_timeouts >= V31_TIMEOUT_TRAP_RECENT_THRESHOLD:
            return (
                "draft",
                INTENT_FRONTLOAD_DRAFT,
                "score_first_timeout_trap_new_seed",
                STATE_FRONTLOAD_DRAFT,
                diagnostics,
            )
        if latest_seed_repair_count >= V38_MAX_DEBUG_REPAIRS_PER_SEED:
            if draft_origin_seed_count < V38_REQUIRED_DRAFT_ORIGIN_SEEDS:
                return (
                    "draft",
                    INTENT_FRONTLOAD_DRAFT,
                    "debug_budget_exhausted_collect_new_draft_seed",
                    STATE_FRONTLOAD_DRAFT,
                    diagnostics,
                )
            return (
                "draft",
                INTENT_FRESH_DRAFT,
                "debug_budget_exhausted_replace_dead_seed",
                STATE_FRESH_DRAFT,
                diagnostics,
            )
        if consecutive_timeouts >= 1:
            return "debug", INTENT_TIMEOUT_SAFE, "debug_timeout_safe_downgrade", STATE_TIMEOUT_TRAP, diagnostics
        return "debug", INTENT_REPAIR_FAILURE, "debug_latest_failure", STATE_DEBUG_REPAIR, diagnostics
    if consecutive_status_count(all_rounds, "no_solution") >= 2:
        return "debug", INTENT_REPAIR_FAILURE, "debug_no_solution_repair", STATE_DEBUG_REPAIR, diagnostics
    if consecutive_timeouts >= V31_TIMEOUT_TRAP_RECENT_THRESHOLD:
        return "debug", INTENT_TIMEOUT_SAFE, "consecutive_timeout_trap_downgrade", STATE_TIMEOUT_TRAP, diagnostics
    if elapsed_fraction >= (1.0 - V3_FINAL_AUDIT_FRACTION) or remaining_budget <= 1800:
        return "improve", INTENT_SUBMISSION_AUDIT, "final_submission_audit_window", STATE_FINAL_AUDIT, diagnostics

    candidate_count = int(portfolio_state.get("candidate_count") or 0)
    if (
        draft_origin_seed_count < V38_REQUIRED_DRAFT_ORIGIN_SEEDS
        and not frontload_quality_exit
        and not frontload_quality_exit_persisted
    ):
        if frontload_attempt_budget_exhausted and draft_origin_seed_count > 0:
            return (
                "improve",
                INTENT_PORTFOLIO_STRENGTHEN,
                "frontload_attempt_budget_exhausted_strengthen_best",
                STATE_PORTFOLIO_STRENGTHEN,
                diagnostics,
            )
        return "draft", INTENT_FRONTLOAD_DRAFT, "collect_required_strong_draft_origin_seed", STATE_FRONTLOAD_DRAFT, diagnostics
    if frontload_quality_exit:
        return (
            "improve",
            INTENT_PORTFOLIO_STRENGTHEN,
            f"frontload_quality_exit:{frontload_quality_exit_reason}",
            STATE_PORTFOLIO_STRENGTHEN,
            diagnostics,
        )
    if (
        trigger_fresh_draft
        and no_recent_best_improvement
        and since_best >= V38_PLATEAU_SCORED_ROUNDS_BEFORE_NEW_DRAFT
    ):
        return "draft", INTENT_FRESH_DRAFT, "five_scored_rounds_without_best_improvement_new_draft_seed", STATE_FRESH_DRAFT, diagnostics
    if (
        bool(portfolio_state.get("weak_start"))
        and valid_successes >= V36_WEAK_START_SUCCESS_LIMIT
    ):
        return "improve", INTENT_STRATEGY_REPLACE, "seed_pool_ready_weak_start_replace", STATE_STRATEGY_REPLACE, diagnostics
    if candidate_count < V36_STRONG_CANDIDATE_COUNT:
        return "improve", INTENT_PORTFOLIO_STRENGTHEN, "seed_pool_ready_but_portfolio_strengthen_best", STATE_PORTFOLIO_STRENGTHEN, diagnostics
    if bool(portfolio_state.get("diversity_gap")) and structural_success_family_count < V37_MIN_DIVERSE_PORTFOLIO_FAMILIES:
        return "improve", INTENT_STRATEGY_REPLACE, "seed_pool_ready_family_diversity_gap_replace", STATE_STRATEGY_REPLACE, diagnostics
    if trigger_deep_eda:
        return "improve", INTENT_DEEP_EDA, f"portfolio_bottleneck_deep_eda:{deep_eda_reason}", STATE_PORTFOLIO_DIAGNOSE, diagnostics
    if (
        no_recent_best_improvement
        and repeated_family
        and since_best >= V31_LOCAL_PLATEAU_AFTER_BEST
        and valid_successes >= 3
    ):
        return "improve", INTENT_STRATEGY_REPLACE, f"plateau_replace_repeated_family:{repeated_family}", STATE_STRATEGY_REPLACE, diagnostics
    if since_best >= V31_STRATEGY_REPLACE_AFTER_BEST and valid_successes >= 3:
        return "improve", INTENT_STRATEGY_REPLACE, "after_best_strategy_replacement", STATE_STRATEGY_REPLACE, diagnostics
    if (
        repeated_family == "portfolio_strengthen"
        or recent_method_family_counts(all_rounds, limit=3).get("portfolio_strengthen", 0) >= V37_MAX_STRENGTHEN_BEFORE_REPLACE
    ):
        return "improve", INTENT_STRATEGY_REPLACE, "portfolio_strengthen_repetition_replace", STATE_STRATEGY_REPLACE, diagnostics
    if (
        candidate_count >= V36_STRONG_CANDIDATE_COUNT
        and valid_successes >= V37_FRONTLOAD_DIVERSE_SUCCESS_LIMIT
        and structural_success_family_count >= 2
        and (round_num % 4 == 3 or since_best >= 3)
    ):
        return "improve", INTENT_PORTFOLIO_BLEND, "portfolio_inround_blend_or_selector_checkpoint", STATE_PORTFOLIO_BLEND, diagnostics
    if since_best >= V31_LOCAL_PLATEAU_AFTER_BEST and valid_successes >= V37_FRONTLOAD_DIVERSE_SUCCESS_LIMIT:
        return "improve", INTENT_PORTFOLIO_STRENGTHEN, "after_best_strengthen_with_internal_ablation", STATE_PORTFOLIO_STRENGTHEN, diagnostics
    return "improve", INTENT_PORTFOLIO_STRENGTHEN, "strengthen_portfolio_frontier", STATE_PORTFOLIO_STRENGTHEN, diagnostics


def _operator_timeout_profile(operator: SearchOperator) -> str:
    text = " ".join(
        str(getattr(operator, field, "") or "")
        for field in ("name", "intent", "family", "description", "source")
    ).lower()
    if canonical_method_family(operator.family, operator) == "model_prior_freeform":
        return "model_prior"

    def has_any(patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text) for pattern in patterns)

    if any(token in text for token in (
        "cnn",
        "efficientnet",
        "resnet",
        "convnext",
        "vit",
        "vision",
        "image",
        "retina",
        "fundus",
        "melanoma",
        "spectrogram_cnn",
        "torch",
        "pretrained",
    )):
        return "deep_media"
    if has_any((
        r"\bsparse(?:_text)?\b",
        r"\btf[-_]?idf\b",
        r"\bnb[-_]?svm\b",
        r"\blog(?:istic)?reg\b",
        r"\btext\b",
        r"\btoxic\b",
        r"\bchar(?:_wb)?\b",
        r"\bword\b",
        r"\bcountvectorizer\b",
        r"\bn[-_]?gram\b",
    )):
        return "sparse_text"
    if any(token in text for token in (
        "gbdt",
        "lightgbm",
        "xgboost",
        "catboost",
        "randomforest",
        "extratrees",
        "tabular",
        "ensemble",
    )):
        return "tabular_ensemble"
    return "general"


def compute_validation_timeout(
    remaining_budget: float,
    operator: SearchOperator | None = None,
    search_state: str | None = None,
    branch_state: str | None = None,
    runtime_profile: str | None = None,
) -> int:
    """Return the framework-owned external timeout envelope for one validation."""
    del search_state, branch_state, runtime_profile
    remaining_seconds = max(0, int(remaining_budget))
    if remaining_seconds == 0:
        return 0
    if operator is None:
        operator = neutral_branch_operator("improve", BRANCH_STATE_FRONTIER_IMPROVE)
    timeout_profile = _operator_timeout_profile(operator)
    if operator.cost == "low":
        cap = V4_EXTERNAL_TIMEOUT_CAP_SECONDS["low"]
    elif timeout_profile == "deep_media":
        cap = V4_EXTERNAL_TIMEOUT_CAP_SECONDS["deep"]
    elif timeout_profile == "sparse_text":
        cap = V4_EXTERNAL_TIMEOUT_CAP_SECONDS["sparse"]
    else:
        cap = V4_EXTERNAL_TIMEOUT_CAP_SECONDS["general"]
    return min(cap, remaining_seconds)


def resolve_sandbox_run_budget(time_budget: float, sandbox_run_budget: float | None) -> float:
    """Default sandbox run budget to the main budget for backwards-compatible 12h runs."""
    if sandbox_run_budget is None or sandbox_run_budget <= 0:
        return float(time_budget)
    return float(sandbox_run_budget)


def compute_budget_state(
    budget_mode: str,
    time_budget: float,
    sandbox_run_budget: float,
    spent_wall_time: float,
    spent_sandbox_run_time: float,
) -> dict[str, Any]:
    """Return the active scheduler budget plus both raw accounting views."""
    if budget_mode not in BUDGET_MODES:
        raise ValueError(f"budget_mode must be one of {sorted(BUDGET_MODES)}")

    wall_budget = max(float(time_budget), 0.0)
    sandbox_budget = max(float(sandbox_run_budget), 0.0)
    wall_remaining = max(0.0, wall_budget - float(spent_wall_time))
    sandbox_remaining = max(0.0, sandbox_budget - float(spent_sandbox_run_time))
    wall_elapsed_fraction = min(1.0, float(spent_wall_time) / wall_budget) if wall_budget > 0 else 1.0
    sandbox_elapsed_fraction = (
        min(1.0, float(spent_sandbox_run_time) / sandbox_budget) if sandbox_budget > 0 else 1.0
    )

    active_budget = sandbox_budget
    active_spent = float(spent_sandbox_run_time)
    active_remaining = sandbox_remaining
    active_elapsed_fraction = sandbox_elapsed_fraction

    return {
        "mode": budget_mode,
        "active_budget": active_budget,
        "active_spent": active_spent,
        "remaining_budget": active_remaining,
        "elapsed_fraction": active_elapsed_fraction,
        "wall_budget": wall_budget,
        "spent_wall_time": float(spent_wall_time),
        "wall_remaining": wall_remaining,
        "wall_elapsed_fraction": wall_elapsed_fraction,
        "sandbox_run_budget": sandbox_budget,
        "spent_sandbox_run_time": float(spent_sandbox_run_time),
        "sandbox_run_remaining": sandbox_remaining,
        "sandbox_elapsed_fraction": sandbox_elapsed_fraction,
    }


def should_stop_after_final_audit(all_rounds: list[dict[str, Any]], budget_state: dict[str, Any]) -> bool:
    """A successful final audit is a terminal verification step, not a search operator."""
    if not all_rounds:
        return False
    latest = all_rounds[-1]
    decision = latest.get("branch_decision") or {}
    if decision.get("branch_state") != BRANCH_STATE_FINAL_AUDIT and decision.get("search_intent") != INTENT_SUBMISSION_AUDIT:
        return False
    if validation_score(latest) is None:
        return False
    if validation_status(latest) != "success":
        return False
    elapsed_fraction = float(budget_state.get("elapsed_fraction") or 0.0)
    remaining_budget = float(budget_state.get("remaining_budget") or 0.0)
    return elapsed_fraction >= (1.0 - V3_FINAL_AUDIT_FRACTION) or remaining_budget <= 2400


def neutral_branch_operator(branch: str, branch_state: str) -> SearchOperator:
    """Compatibility operator: the scheduler no longer chooses a modeling route."""
    return SearchOperator(
        name="agent_selected_after_context",
        intent="branch_only",
        family="agent_selected_after_context",
        description=(
            f"Branch-only scheduling selected branch={branch}, state={branch_state}. "
            "The coding agent must choose the concrete modeling route after reading required context paths."
        ),
        source="branch_decision_v2_compat",
        cost="medium",
        risk="medium",
    )


def _candidate_from_best_vault(task_dir: Path) -> dict[str, Any] | None:
    path = task_dir / "index" / "best_validation_candidate.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    commit = payload.get("commit_hash") or payload.get("commit")
    return {
        "role": "best",
        "round": payload.get("round"),
        "commit": commit,
        "score": payload.get("validation_score") if payload.get("validation_score") is not None else payload.get("score"),
        "branch": payload.get("branch") or payload.get("effective_branch"),
        "effective_branch": payload.get("effective_branch") or payload.get("branch"),
        "method_family": payload.get("effective_method_family") or payload.get("method_family"),
        "run_time": (payload.get("validation") or {}).get("run_time") if isinstance(payload.get("validation"), dict) else payload.get("run_time"),
        "wall_time": payload.get("round_wall_time") or payload.get("wall_time"),
        "card_path": payload.get("memory_card_path") or payload.get("card_path"),
        "memory_card_path": payload.get("memory_card_path") or payload.get("card_path"),
        "diff_path": payload.get("memory_diff_path") or payload.get("diff_path"),
        "memory_diff_path": payload.get("memory_diff_path") or payload.get("diff_path"),
        "code_path": payload.get("code_path") or (f"commits/{commit}/solution.py" if commit else None),
        "feedback_path": f"commits/{commit}/validation_feedback.txt" if commit else None,
        "status": "success",
    }


def _validation_best_candidate_for_branch_v3(
    task_dir: Path,
    all_rounds: list[dict[str, Any]],
    portfolio_state: dict[str, Any],
    higher_is_better: bool,
) -> dict[str, Any] | None:
    """Resolve one validation-best, submit-eligible parent across all stores."""
    candidates: list[dict[str, Any]] = []
    candidate = portfolio_state.get("best_candidate") if isinstance(portfolio_state.get("best_candidate"), dict) else None
    if candidate and candidate.get("score") is not None and bool(candidate.get("submit_eligible", True)):
        commit = candidate.get("commit")
        candidates.append({
            "round": candidate.get("round"),
            "commit": commit,
            "score": candidate.get("score"),
            "branch": candidate.get("branch"),
            "effective_branch": candidate.get("effective_branch") or candidate.get("branch"),
            "method_family": candidate.get("method_family"),
            "method_family_components": candidate.get("method_family_components") or [],
            "run_time": candidate.get("run_time"),
            "wall_time": candidate.get("wall_time"),
            "card_path": candidate.get("memory_card_path") or candidate.get("card_path"),
            "memory_card_path": candidate.get("memory_card_path") or candidate.get("card_path"),
            "diff_path": candidate.get("memory_diff_path") or candidate.get("diff_path"),
            "memory_diff_path": candidate.get("memory_diff_path") or candidate.get("diff_path"),
            "code_path": ((candidate.get("commit_paths") or {}).get("solution_path") if isinstance(candidate.get("commit_paths"), dict) else None)
                or (f"commits/{commit}/solution.py" if commit else None),
            "feedback_path": f"commits/{commit}/validation_feedback.txt" if commit else None,
            "commit_paths": candidate.get("commit_paths") or {},
            "status": "success",
        })
    vault_candidate = _candidate_from_best_vault(task_dir)
    if vault_candidate:
        candidates.append(vault_candidate)
    for row in all_rounds:
        if not is_submission_eligible_round(row):
            continue
        commit = row.get("commit_hash") or row.get("commit")
        candidates.append({
            "round": row.get("round"),
            "commit": commit,
            "score": validation_score(row),
            "branch": get_round_branch(row),
            "effective_branch": row.get("effective_branch") or get_round_branch(row),
            "method_family": row.get("effective_method_family") or row.get("method_family"),
            "card_path": row.get("memory_card_path") or row.get("card_path"),
            "memory_card_path": row.get("memory_card_path") or row.get("card_path"),
            "code_path": row.get("code_path") or (f"commits/{commit}/solution.py" if commit else None),
            "feedback_path": row.get("validation_feedback_path") or (f"commits/{commit}/validation_feedback.txt" if commit else None),
            "status": validation_status(row) or "success",
        })
    if not candidates:
        return None
    deduplicated: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = str(item.get("commit") or f"round:{item.get('round')}")
        existing = deduplicated.get(key)
        if existing is None or (not existing.get("code_path") and item.get("code_path")):
            deduplicated[key] = item

    def candidate_key(item: dict[str, Any]) -> tuple[float, int]:
        try:
            round_num = int(item.get("round") or 0)
        except (TypeError, ValueError):
            round_num = 0
        return score_sort_key(validation_score(item), higher_is_better), -round_num

    return max(deduplicated.values(), key=candidate_key)


def _latest_debug_parent_for_branch_v3(
    task_dir: Path,
    all_rounds: list[dict[str, Any]],
) -> dict[str, Any] | None:
    try:
        from .text_context import find_latest_failed_parent_candidate
        candidate = find_latest_failed_parent_candidate(task_dir)
    except Exception:
        candidate = None
    if not candidate:
        for row in reversed(all_rounds):
            if row_is_llm_infra_failure(row) or validation_score(row) is not None:
                continue
            if not (row_has_generated_code(row) or row.get("code_path") or row.get("failure_artifact_dir")):
                continue
            commit = row.get("commit_hash") or row.get("commit")
            candidate = {
                "round": row.get("round"),
                "commit": commit,
                "score": validation_score(row),
                "status": validation_status(row),
                "failure_primary": row.get("failure_primary")
                    or (((row.get("validation") or {}).get("failure_taxonomy") or {}).get("primary")),
                "card_path": row.get("memory_card_path") or row.get("card_path"),
                "code_path": row.get("code_path") or (f"commits/{commit}/solution.py" if commit else None),
                "validation_feedback_path": row.get("validation_feedback_path")
                    or (f"commits/{commit}/validation_feedback.txt" if commit else None),
                "method_family": row.get("effective_method_family") or row.get("method_family"),
                "seed_id": (row.get("effective_lineage") or {}).get("seed_id"),
            }
            break
    if not candidate:
        return None
    return {
        "role": "debug_parent",
        "round": candidate.get("round"),
        "commit": candidate.get("commit"),
        "score": candidate.get("score"),
        "status": candidate.get("status"),
        "failure_primary": candidate.get("failure_primary"),
        "card_path": candidate.get("card_path"),
        "code_path": candidate.get("code_path"),
        "feedback_path": candidate.get("validation_feedback_path"),
        "method_family": candidate.get("method_family"),
        "seed_id": candidate.get("seed_id"),
    }


def _parent_binding(role: str, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the non-recursive parent contract persisted in v3 decisions."""
    if role == "none" or not candidate:
        return {"role": "none"}
    score = validation_score(candidate)
    binding = {
        "role": role,
        "round": candidate.get("round"),
        "commit": candidate.get("commit"),
        "status": candidate.get("status"),
        "score": score,
        "method_family": candidate.get("method_family"),
        "memory_card_path": candidate.get("memory_card_path") or candidate.get("card_path"),
        "code_path": candidate.get("code_path"),
        "feedback_path": candidate.get("feedback_path") or candidate.get("validation_feedback_path"),
    }
    if role == "debug_parent":
        binding["failure_primary"] = candidate.get("failure_primary")
        binding["seed_id"] = candidate.get("seed_id")
    return {key: value for key, value in binding.items() if value is not None}


def _memory_card_method_summary(task_dir: Path, card_path: Any) -> str:
    """Read the Method Portrait summary from one completed memory card."""
    if not card_path:
        return "unavailable"
    path = Path(str(card_path))
    if not path.is_absolute():
        path = task_dir / path
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unavailable"
    for line in text.splitlines():
        match = re.match(r"^\s*[-*]\s*method_summary\s*:\s*(.*)$", line, flags=re.IGNORECASE)
        if match and match.group(1).strip():
            return re.sub(r"\s+", " ", match.group(1).strip())
    return "unavailable"


def _frozen_draft_prior_memory(
    task_dir: Path,
    all_rounds: list[dict[str, Any]],
    higher_is_better: bool,
    limit: int = 4,
) -> dict[str, Any]:
    """Freeze bounded draft-card portraits without inheriting prior code."""
    indexed: dict[int, dict[str, Any]] = {}
    index_path = task_dir / "memory_bank" / "card_index.jsonl"
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                round_num = int(row.get("round"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(row, dict) and normalize_branch_name(str(row.get("branch") or "")) == "draft":
                indexed[round_num] = row

    candidates: list[dict[str, Any]] = []
    for row in all_rounds:
        if get_round_branch(row) != "draft":
            continue
        try:
            round_num = int(row.get("round"))
        except (TypeError, ValueError):
            continue
        card = indexed.get(round_num, {})
        family = (
            card.get("method_family")
            or row.get("effective_method_family")
            or row.get("method_family")
            or "unknown"
        )
        keywords = card.get("method_keywords") if isinstance(card.get("method_keywords"), list) else []
        card_path = row.get("memory_card_path") or card.get("card_path")
        candidates.append({
            "round": round_num,
            "score": validation_score(row) if validation_score(row) is not None else card.get("score"),
            "method_summary": _memory_card_method_summary(task_dir, card_path),
            "card_path": card_path,
            "_status": validation_status(row) or row.get("status") or card.get("status") or "unknown",
            "_signature": "|".join([str(family).strip().lower(), *(str(item).strip().lower() for item in keywords[:3])]),
        })
    candidates.sort(key=lambda row: row["round"])
    if not candidates:
        return {
            "schema_version": "draft_prior_memory_v2",
            "status": "no_prior_rounds",
            "evidence_cutoff_round": None,
            "cards": [],
            "omitted_count": 0,
        }

    selected: dict[int, dict[str, Any]] = {}

    def add(row: dict[str, Any]) -> None:
        if len(selected) < limit or row["round"] in selected:
            selected[row["round"]] = row

    scored = [row for row in candidates if isinstance(row.get("score"), (int, float))]
    if scored:
        add((max if higher_is_better else min)(scored, key=lambda row: float(row["score"])))
    add(candidates[-1])
    for row in reversed(candidates):
        if str(row.get("_status") or "").lower() not in {"success", "completed"}:
            add(row)
    seen_signatures = {str(row.get("_signature") or "unknown") for row in selected.values()}
    for row in reversed(candidates):
        signature = str(row.get("_signature") or "unknown")
        if signature not in seen_signatures:
            add(row)
            seen_signatures.add(signature)
    for row in [candidates[0], *reversed(candidates)]:
        add(row)
    cards = [
        {
            "round": row["round"],
            "score": row.get("score"),
            "method_summary": row.get("method_summary") or "unavailable",
            "card_path": row.get("card_path"),
        }
        for row in sorted(selected.values(), key=lambda row: row["round"])
    ]
    return {
        "schema_version": "draft_prior_memory_v2",
        "status": "available",
        "evidence_cutoff_round": candidates[-1]["round"],
        "cards": cards,
        "omitted_count": max(0, len(candidates) - len(cards)),
    }


def _latest_round_needs_debug(all_rounds: list[dict[str, Any]]) -> tuple[bool, str]:
    if not all_rounds:
        return False, ""
    latest = all_rounds[-1]
    if row_is_llm_infra_failure(latest):
        return False, ""
    status = validation_status(latest)
    score = validation_score(latest)
    if score is not None:
        return False, ""
    if status in {DUPLICATE_SOLUTION_STATUS, "no_solution", "agent_error"}:
        return False, ""
    if row_is_timeout(latest):
        return True, "latest_timeout_failure"
    if row_has_generated_code(latest) or latest.get("code_path") or latest.get("failure_artifact_dir"):
        return True, f"latest_generated_code_failed:{status or 'unknown'}"
    return False, ""


def _non_debug_scored_rounds_since_best(
    all_rounds: list[dict[str, Any]],
    best_score: float | None,
    higher_is_better: bool,
) -> int:
    if best_score is None:
        return 0
    tol = max(V4_MATERIAL_SCORE_ABS_DELTA, abs(float(best_score)) * V4_MATERIAL_SCORE_REL_DELTA)
    found_best = False
    count = 0
    for row in all_rounds:
        score = validation_score(row)
        if score is None:
            continue
        if not found_best:
            if abs(float(score) - float(best_score)) <= tol or score_better(float(score), float(best_score), higher_is_better):
                found_best = True
            continue
        decision = row.get("branch_decision") if isinstance(row.get("branch_decision"), dict) else {}
        branch_state = str(row.get("branch_state") or decision.get("branch_state") or "")
        if get_round_branch(row) == "draft" and branch_state == BRANCH_STATE_PLATEAU_NEW_SEED:
            # A plateau draft is the exploration response to the accumulated
            # stagnation. Start a new improve window after it instead of
            # satisfying the same threshold forever.
            count = 0
            continue
        if get_round_branch(row) != "debug":
            count += 1
    return count if found_best else 0


def choose_branch_state_for_round(
    *,
    task_dir: Path,
    round_num: int,
    all_rounds: list[dict[str, Any]],
    higher_is_better: bool,
    elapsed_fraction: float,
    remaining_budget: float,
    budget_state: dict[str, Any] | None,
    portfolio_state: dict[str, Any],
) -> dict[str, Any]:
    """Hard branch-only scheduler for v2 decisions."""
    best_candidate = _validation_best_candidate_for_branch_v3(task_dir, all_rounds, portfolio_state, higher_is_better)
    best_score = best_candidate.get("score") if best_candidate else None
    try:
        best_score_float = float(best_score) if best_score is not None else None
    except Exception:
        best_score_float = None
    debug_needed, debug_reason = _latest_round_needs_debug(all_rounds)
    consecutive_timeouts = consecutive_timeout_count(all_rounds)
    scored_count = len([row for row in all_rounds if validation_score(row) is not None])
    seed_count = int(portfolio_state.get("successful_draft_origin_seed_count") or 0)
    after_best_non_debug = _non_debug_scored_rounds_since_best(all_rounds, best_score_float, higher_is_better)
    plateau_draft_count = fresh_draft_count(all_rounds)
    rounds_after_plateau_draft = rounds_since_last_fresh_draft(all_rounds)
    final_window = elapsed_fraction >= (1.0 - V3_FINAL_AUDIT_FRACTION) or remaining_budget <= 2400

    branch = "improve"
    branch_state = BRANCH_STATE_FRONTIER_IMPROVE
    branch_reason = "default_improve_after_two_scored_draft_seeds"
    runtime_profile = RUNTIME_PROFILE_STANDARD
    eda_mode = "none"
    deep_eda_advice = ""
    parent_binding = _parent_binding("none")

    if round_num == 0:
        branch = "draft"
        branch_state = BRANCH_STATE_INITIAL_SEED
        branch_reason = "round_0_initial_seed"
        runtime_profile = RUNTIME_PROFILE_NEW_SEED_SCORE_FIRST
        eda_mode = "early"
    elif debug_needed:
        branch = "debug"
        branch_state = BRANCH_STATE_TIMEOUT_RECOVERY if consecutive_timeouts >= 1 else BRANCH_STATE_REPAIR_FAILURE
        branch_reason = debug_reason or "latest_failed_generated_code"
        runtime_profile = RUNTIME_PROFILE_TIMEOUT_RECOVERY if branch_state == BRANCH_STATE_TIMEOUT_RECOVERY else RUNTIME_PROFILE_DEBUG_REPAIR
        parent_binding = _parent_binding("debug_parent", _latest_debug_parent_for_branch_v3(task_dir, all_rounds))
        deep_eda_advice = (
            "If the parent feedback mentions parsing, schema, shape, missing files, labels, "
            "or submission alignment, do a bounded read-only deep EDA during context acquisition."
        )
    elif consecutive_timeouts >= V31_TIMEOUT_TRAP_RECENT_THRESHOLD and scored_count == 0:
        branch = "debug"
        branch_state = BRANCH_STATE_TIMEOUT_RECOVERY
        branch_reason = "repeated_timeout_before_any_score"
        runtime_profile = RUNTIME_PROFILE_TIMEOUT_RECOVERY
        parent_binding = _parent_binding("debug_parent", _latest_debug_parent_for_branch_v3(task_dir, all_rounds))
        deep_eda_advice = "Use bounded read-only deep EDA only to confirm file sizes and cheap contract facts before shrinking the route."
    elif seed_count < V38_REQUIRED_DRAFT_ORIGIN_SEEDS:
        branch = "draft"
        branch_state = BRANCH_STATE_REQUIRED_SEED
        branch_reason = "need_two_successful_independent_draft_origin_seeds"
        runtime_profile = RUNTIME_PROFILE_NEW_SEED_SCORE_FIRST
    elif final_window and best_candidate:
        branch = "improve"
        branch_state = BRANCH_STATE_FINAL_AUDIT
        branch_reason = "final_budget_window_audit_best_candidate"
        runtime_profile = RUNTIME_PROFILE_FINAL_AUDIT
        parent_binding = _parent_binding("validation_best", best_candidate)
    elif (
        after_best_non_debug >= V38_PLATEAU_SCORED_ROUNDS_BEFORE_NEW_DRAFT
        and plateau_draft_count < V38_MAX_FRESH_DRAFT_RUNS
        and (
            rounds_after_plateau_draft is None
            or rounds_after_plateau_draft >= V37_FRESH_DRAFT_COOLDOWN_ROUNDS
        )
    ):
        branch = "draft"
        branch_state = BRANCH_STATE_PLATEAU_NEW_SEED
        branch_reason = f"plateau_{after_best_non_debug}_non_debug_scored_rounds_without_best_improvement"
        runtime_profile = RUNTIME_PROFILE_NEW_SEED_SCORE_FIRST
        deep_eda_advice = (
            "Plateau detected. The framework will not launch a separate deep EDA phase; "
            "the coding agent may do bounded read-only deep EDA if data-contract uncertainty blocks a higher-ceiling seed."
        )
    else:
        branch = "improve"
        branch_state = BRANCH_STATE_FRONTIER_IMPROVE
        branch_reason = "frontier_improve_after_seed_pool_ready"
        runtime_profile = RUNTIME_PROFILE_STANDARD
        parent_binding = _parent_binding("validation_best", best_candidate)

    if branch == "improve" and parent_binding.get("role") == "none" and best_candidate:
        parent_binding = _parent_binding("validation_best", best_candidate)

    return {
        "branch": branch,
        "branch_state": branch_state,
        "branch_reason": branch_reason,
        "runtime_profile": runtime_profile,
        "eda_mode": eda_mode,
        "parent_binding": parent_binding,
        "best_candidate": best_candidate,
        "diagnostics": {
            "successful_draft_origin_seed_count": seed_count,
            "required_draft_origin_seeds": V38_REQUIRED_DRAFT_ORIGIN_SEEDS,
            "scored_round_count": scored_count,
            "non_debug_scored_since_best": after_best_non_debug,
            "plateau_draft_count": plateau_draft_count,
            "max_plateau_draft_runs": V38_MAX_FRESH_DRAFT_RUNS,
            "rounds_since_last_plateau_draft": rounds_after_plateau_draft,
            "plateau_draft_cooldown_rounds": V37_FRESH_DRAFT_COOLDOWN_ROUNDS,
            "consecutive_timeouts": consecutive_timeouts,
            "final_window": final_window,
            "historical_deep_eda_count": deep_eda_count(all_rounds),
            "max_historical_deep_eda_runs": V33_MAX_DEEP_EDA_RUNS,
            "deep_eda_control": "codex_context_acquisition_only",
        },
        "deep_eda_advice": deep_eda_advice,
    }


def choose_branch_for_round(
    task_dir: Path,
    round_num: int,
    all_rounds: list[dict[str, Any]],
    higher_is_better: bool,
    branch_strategy: str,
    warmup_branches: tuple[str, ...],
    task_name: str | None = None,
    task_skills_dir: Path = DEFAULT_TASK_SKILLS_DIR,
    elapsed_fraction: float = 0.0,
    remaining_budget: float = 43200.0,
    budget_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Choose the branch and finite branch state to run for the next round.

    branch_strategy and warmup_branches are accepted only for older launcher
    compatibility; v4 always uses the portfolio-first policy below.
    """
    _ = (branch_strategy, warmup_branches)
    task_name = task_name or task_dir.name
    portfolio_state = load_portfolio_snapshot(task_dir, all_rounds, higher_is_better)
    state = choose_branch_state_for_round(
        task_dir=task_dir,
        round_num=round_num,
        all_rounds=all_rounds,
        higher_is_better=higher_is_better,
        elapsed_fraction=elapsed_fraction,
        remaining_budget=remaining_budget,
        budget_state=budget_state,
        portfolio_state=portfolio_state,
    )
    branch = normalize_branch_name(state["branch"])
    branch_state = str(state["branch_state"])
    spec = BRANCH_SPEC_BY_NAME.get(branch, BRANCH_SPEC_BY_NAME["draft"])
    parent_binding = state.get("parent_binding") if isinstance(state.get("parent_binding"), dict) else _parent_binding("none")
    best_candidate = state.get("best_candidate") if isinstance(state.get("best_candidate"), dict) else None
    source_policy: dict[str, list[str]] = {"must": [], "optional": []}
    if branch == "draft":
        source_policy["must"] = ["task_skill", "failure_prevention_skill", "eda_findings", "high_level_memory"]
        source_policy["optional"] = ["eda_full", "card_index", "best_card", "top_cards", "eda_insight_store"]
    elif branch == "debug":
        source_policy["must"] = ["failure_prevention_skill", "eda_findings", "debug_parent_card", "debug_parent_code", "debug_parent_feedback"]
        source_policy["optional"] = ["task_skill", "eda_full", "card_index", "top_cards", "eda_insight_store", "high_level_memory"]
    else:
        source_policy["must"] = ["task_skill", "eda_findings", "anchor_card", "anchor_code", "anchor_feedback", "high_level_memory"]
        source_policy["optional"] = ["eda_full", "card_index", "top_cards", "top_code", "top_feedback", "memory_diffs", "eda_insight_store"]
    runtime_profile = str(state.get("runtime_profile") or RUNTIME_PROFILE_STANDARD)
    strict_score_first_required = runtime_profile in {
        RUNTIME_PROFILE_NEW_SEED_SCORE_FIRST,
        RUNTIME_PROFILE_TIMEOUT_RECOVERY,
        RUNTIME_PROFILE_HIGH_RISK_PARENT,
    }
    runtime_control = {
        "runtime_profile": runtime_profile,
        "strict_score_first_required": bool(strict_score_first_required),
        "strict_score_first_reason": (
            "runtime profile requires a trained score-first path"
            if strict_score_first_required else
            "standard branch runtime profile"
        ),
    }
    validation_timeout = compute_validation_timeout(
        remaining_budget,
        neutral_branch_operator(branch, branch_state),
        search_state=branch_state,
        branch_state=branch_state,
        runtime_profile=runtime_profile,
    )
    external_timeout_plan = {
        "schema_version": "external_timeout_plan_v1",
        "validation_timeout_seconds": validation_timeout,
        "remaining_sandbox_runtime_seconds": max(0, int(remaining_budget)),
        "runtime_profile": runtime_profile,
        "allocation_basis": "framework_operator_cap",
        "policy": V4_EXTERNAL_TIMEOUT_POLICY,
    }
    score_feedback = build_validation_score_feedback(
        all_rounds=all_rounds,
        best_score=float(best_candidate["score"]) if best_candidate and isinstance(best_candidate.get("score"), (int, float)) else None,
        higher_is_better=higher_is_better,
        task_dir=task_dir,
    )
    draft_prior_memory = (
        _frozen_draft_prior_memory(task_dir, all_rounds, higher_is_better)
        if branch == "draft" else None
    )
    decision = {
        "schema_version": "branch_decision_v3",
        "round": round_num,
        "branch": spec.name,
        "branch_title": spec.title,
        "branch_state": branch_state,
        "branch_reason": state.get("branch_reason"),
        "reason": state.get("branch_reason"),
        "runtime_profile": runtime_profile,
        "eda_mode": state.get("eda_mode") or "none",
        "deep_eda_advice": state.get("deep_eda_advice") or "",
        "parent_binding": parent_binding,
        **({"draft_prior_memory": draft_prior_memory} if draft_prior_memory is not None else {}),
        "source_policy": source_policy,
        "state_diagnostics": state.get("diagnostics") or {},
        "score_feedback": score_feedback,
        "budget": {
            "elapsed_fraction": elapsed_fraction,
            "remaining_budget": remaining_budget,
            "state": budget_state or {},
        },
        "validation_timeout_seconds": validation_timeout,
        "external_timeout_plan": external_timeout_plan,
        "goal": spec.goal,
        "instructions": spec.instructions,
        "portfolio_action": spec.name,
        "portfolio_slot": {
            "target": branch_state,
            "candidate_count": portfolio_state.get("candidate_count", 0),
            "family_counts": portfolio_state.get("family_counts") or {},
            "successful_draft_origin_seed_count": portfolio_state.get("successful_draft_origin_seed_count", 0),
            "successful_draft_origin_seed_total": portfolio_state.get("successful_draft_origin_seed_total", 0),
            "required_draft_origin_seeds": portfolio_state.get("required_draft_origin_seeds", V38_REQUIRED_DRAFT_ORIGIN_SEEDS),
            "successful_draft_origin_seed_families": portfolio_state.get("successful_draft_origin_seed_families") or [],
            "diversity_gap": bool(portfolio_state.get("diversity_gap")),
            "weak_start": bool(portfolio_state.get("weak_start")),
        },
        "runtime_control": runtime_control,
        "search_state": branch_state,
        "timestamp": datetime.now().isoformat(),
    }
    index_dir = task_dir / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "current_branch_decision.json").write_text(
        json.dumps(decision, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return decision


def build_refinement_context(task_dir: Path, round_num: int, higher_is_better: bool) -> str | None:
    """Build git-style navigation context for planning or coding."""
    if round_num == 0:
        current_branch = get_current_branch(task_dir)
        spec = BRANCH_SPEC_BY_NAME.get(current_branch, BRANCH_SPEC_BY_NAME["draft"])
        return f"""
=== Round {round_num + 1} - Branch Search Start ===

Current branch: {current_branch}
Branch goal: {spec.goal}
Branch instructions: {spec.instructions}

This is the first attempt on this branch. Use the branch goal to decide the current round's focused direction.
"""

    current_branch = get_current_branch(task_dir)
    spec = BRANCH_SPEC_BY_NAME.get(current_branch, BRANCH_SPEC_BY_NAME["draft"])
    commit_log = shrink_text_middle(get_commit_log_summary(task_dir, limit=4), 1800)
    tag_summary = shrink_text_middle(get_tag_summary(task_dir), 900)
    latest_failure_context = shrink_text_middle(get_latest_failure_context(task_dir), 1400)
    branch_scoreboard = shrink_text_middle(get_branch_scoreboard(task_dir, higher_is_better=higher_is_better), 1200)
    decision_file = task_dir / "index" / "current_branch_decision.json"
    try:
        branch_decision_payload = json.loads(decision_file.read_text(encoding="utf-8")) if decision_file.exists() else {}
    except Exception:
        branch_decision_payload = {}
    branch_decision = compact_branch_state(branch_decision_payload)

    context = f"""
=== Round {round_num + 1} - V4 Compact Search Navigation ===

Current branch: {current_branch}
Branch title: {spec.title}
Branch goal: {spec.goal}
Branch instructions: {spec.instructions}

Current branch decision:
{branch_decision}

{branch_scoreboard}

{commit_log}

{tag_summary}

{latest_failure_context}

Execution rule:
- Let `[ROUND DIRECTIVE]` choose edit scale and evidence priority.
- For draft, keep prior code optional and avoid incumbent patching.
- For improve/blend/replacement, inspect best/parent code and the small top-diverse code set when listed; do not re-read full archives.
- For debug, inspect only the failed parent code and feedback unless the directive says otherwise.
"""
    return shrink_text_middle(context, V33_REFINEMENT_CONTEXT_LIMIT)



def build_integrated_planning_placeholder(branch: str, branch_decision: dict[str, Any], skill_route: SkillRoute) -> str:
    """Return archived placeholder text for the integrated context-first planning design."""
    spec = BRANCH_SPEC_BY_NAME.get(branch, BRANCH_SPEC_BY_NAME["draft"])
    return (
        "# Integrated Context-First Planning\n\n"
        "Standalone planning.md generation is disabled in v4. The coding agent must inspect the source-map files, "
        "write `context_readiness.md` as the final pre-code plan, then write `solution.py`.\n\n"
        "## Branch Objective\n"
        f"{spec.goal}\n\n"
        "## Branch State\n"
        f"{branch_decision.get('branch_state') or branch_decision.get('search_state') or 'unknown'}\n\n"
        "## Selected Knowledge\n"
        f"{skill_route.reason}\n\n"
        "## Integrated Coding Contract\n"
        "- Use the routed task skill paths, pinned hard contract, source-map EDA paths, memory cards, and branch state in one coding call.\n"
        "- Put inspected files, anchor/debug parent behavior, imported node ideas, validation route, and failure traps in `context_readiness.md` before code.\n"
        "- Preserve DATA_DIR loading, dataset-instance generality, and submission.csv contract.\n"
    )


def build_no_plan_placeholder(branch: str, branch_decision: dict[str, Any], skill_route: SkillRoute) -> str:
    """Backward-compatible wrapper for older result fields."""
    return build_integrated_planning_placeholder(branch, branch_decision, skill_route)
