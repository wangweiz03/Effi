from __future__ import annotations

import atexit
import threading

from .common import *
from .constants import HIGH_LEVEL_MEMORY_FILENAME, POST_CODE_MEMORY_SUMMARY_FILENAME

_SOFT_THREADS: list[threading.Thread] = []
_SOFT_THREADS_LOCK = threading.Lock()


def _join_soft_threads() -> None:
    with _SOFT_THREADS_LOCK:
        threads = list(_SOFT_THREADS)
    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=2.0)


atexit.register(_join_soft_threads)


def _normalize_branch_name(branch: str) -> str:
    clean = str(branch or "").strip().lower()
    aliases = {
        "baseline": "draft",
        "repair": "debug",
        "feature": "improve",
        "model": "improve",
        "exploit": "improve",
    }
    return aliases.get(clean, clean if clean in {"draft", "debug", "improve"} else clean)


def _safe_slug(value: str | None, fallback: str = "unknown") -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("_")
    return (text or fallback)[:80]


def _stable_unique(values: Iterable[Any], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text[:80])
        if limit is not None and len(result) >= limit:
            break
    return result


def _compact_inline(text: Any, limit: int = 900) -> str:
    one_line = re.sub(r"\s+", " ", str(text or "").strip())
    if len(one_line) <= limit:
        return one_line
    return one_line[: max(0, limit - 3)].rstrip() + "..."


def _full_inline(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_task_path(task_dir: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else task_dir / path


def _relative_or_absolute(task_dir: Path, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(task_dir.resolve()))
    except Exception:
        return str(path)


def _round_score(result: dict[str, Any]) -> float | None:
    validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
    value = result.get("score")
    if value is None:
        value = validation.get("score")
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _metric_aligned_delta(current: float | None, parent: float | None, higher_is_better: bool) -> float | None:
    if current is None or parent is None:
        return None
    return float(current) - float(parent) if higher_is_better else float(parent) - float(current)


def _delta_label(delta: float | None) -> str:
    if delta is None:
        return "unknown"
    if delta > 1e-12:
        return "improved"
    if delta < -1e-12:
        return "worsened"
    return "unchanged"


def _material_delta(delta: float | None, score: float | None, parent_score: float | None) -> float:
    ref = parent_score if parent_score is not None else score
    return max(1e-6, abs(float(ref or 0.0)) * 1e-4)


def _cost_risk_signal(
    *,
    result: dict[str, Any],
    validation: dict[str, Any],
    solution_contract: dict[str, Any],
    failure_taxonomy: dict[str, Any],
    score: float | None,
    parent_score: float | None,
    delta: float | None,
) -> dict[str, Any]:
    run_time = validation.get("run_time")
    try:
        run_time_float = float(run_time) if run_time is not None else None
    except Exception:
        run_time_float = None
    timeout = validation.get("timeout") or (result.get("branch_decision") or {}).get("validation_timeout_seconds")
    try:
        timeout_float = float(timeout) if timeout is not None else None
    except Exception:
        timeout_float = None
    if run_time_float is None:
        cost_bucket = "unknown_cost"
    elif (timeout_float and run_time_float >= timeout_float * 0.75) or run_time_float >= 3600:
        cost_bucket = "high_cost"
    elif run_time_float >= 900:
        cost_bucket = "medium_cost"
    else:
        cost_bucket = "low_cost"

    tolerance = _material_delta(delta, score, parent_score)
    if delta is None:
        reward_bucket = "unknown_reward"
    elif delta > tolerance:
        reward_bucket = "material_gain"
    elif delta < -tolerance:
        reward_bucket = "material_loss"
    elif abs(delta) <= tolerance:
        reward_bucket = "zero_or_low_gain"
    else:
        reward_bucket = "low_gain"

    tags: list[str] = []
    status = str(result.get("status") or validation.get("status") or "unknown")
    if score is None:
        tags.append(f"no_score:{status}")
    if validation.get("timeout") or "timeout" in status.lower():
        tags.append("timeout_risk")
    missing = solution_contract.get("missing")
    if missing:
        tags.append("static_warning:" + ",".join(str(item) for item in list(missing)[:3]))
    blockers = solution_contract.get("blockers")
    if blockers:
        tags.append("static_blocker:" + ",".join(str(item) for item in list(blockers)[:3]))
    quality = validation.get("quality") if isinstance(validation.get("quality"), dict) else {}
    quality_kind = quality.get("kind")
    if quality_kind and quality_kind != "unknown":
        tags.append(f"quality_gate:{quality_kind}")
    failure_primary = failure_taxonomy.get("primary")
    if failure_primary and str(failure_primary).lower() not in {"none", ""}:
        tags.append(f"failure:{failure_primary}")
    if cost_bucket == "high_cost" and reward_bucket == "material_gain":
        tags.append("high_cost_high_reward")
    elif cost_bucket == "high_cost" and reward_bucket in {"zero_or_low_gain", "low_gain"}:
        tags.append("high_cost_low_or_zero_gain")
    elif cost_bucket == "high_cost" and score is None:
        tags.append("high_cost_no_score")
    return {
        "cost_bucket": cost_bucket,
        "reward_bucket": reward_bucket,
        "material_tolerance": tolerance,
        "risk_tags": _stable_unique(tags, limit=12),
        "sandbox_run_time": run_time_float,
        "timeout": timeout_float,
    }


def _anchor_parent(branch_decision: dict[str, Any]) -> dict[str, Any]:
    binding = branch_decision.get("parent_binding")
    if isinstance(binding, dict) and binding.get("role") == "validation_best":
        return binding
    anchor = branch_decision.get("anchor_parent")
    if isinstance(anchor, dict):
        return anchor
    return {}


def _debug_parent(branch_decision: dict[str, Any]) -> dict[str, Any]:
    binding = branch_decision.get("parent_binding")
    if isinstance(binding, dict) and binding.get("role") == "debug_parent":
        return binding
    parent = branch_decision.get("debug_parent_fallback")
    if isinstance(parent, dict):
        return parent
    out: dict[str, Any] = {}
    if branch_decision.get("debug_parent_round") is not None:
        out["round"] = branch_decision.get("debug_parent_round")
    if branch_decision.get("debug_parent_commit"):
        out["commit"] = branch_decision.get("debug_parent_commit")
    if branch_decision.get("debug_parent_code_path"):
        out["code_path"] = branch_decision.get("debug_parent_code_path")
    if branch_decision.get("debug_parent_validation_feedback_path"):
        out["feedback_path"] = branch_decision.get("debug_parent_validation_feedback_path")
    return out


def _primary_parent(branch: str, branch_decision: dict[str, Any]) -> dict[str, Any]:
    if branch == "debug":
        return _debug_parent(branch_decision)
    if branch == "improve":
        return _anchor_parent(branch_decision)
    return {}


def _artifact_paths(task_dir: Path, result: dict[str, Any]) -> dict[str, str]:
    commit = str(result.get("commit_hash") or result.get("commit") or "").strip()
    failure_dir = _resolve_task_path(task_dir, result.get("failure_artifact_dir"))
    solution_path = _resolve_task_path(task_dir, result.get("code_path"))
    feedback_path = _resolve_task_path(task_dir, result.get("validation_feedback_path"))
    context_path: Path | None = None
    memory_summary_path: Path | None = None
    result_path: Path | None = None
    if commit:
        commit_dir = task_dir / "commits" / commit
        solution_path = solution_path or commit_dir / "solution.py"
        feedback_path = feedback_path or commit_dir / "validation_feedback.txt"
        context_path = commit_dir / "context_readiness.md"
        memory_summary_path = commit_dir / POST_CODE_MEMORY_SUMMARY_FILENAME
        result_path = commit_dir / "result.json"
    elif failure_dir:
        solution_path = solution_path or failure_dir / "solution.py"
        feedback_path = feedback_path or failure_dir / "validation_feedback.txt"
        context_path = failure_dir / "context_readiness.md"
        memory_summary_path = failure_dir / POST_CODE_MEMORY_SUMMARY_FILENAME
        result_path = failure_dir / "result.json"
    return {
        "solution": _relative_or_absolute(task_dir, solution_path),
        "feedback": _relative_or_absolute(task_dir, feedback_path),
        "context": _relative_or_absolute(task_dir, context_path),
        "post_code_memory_summary": _relative_or_absolute(task_dir, memory_summary_path),
        "result": _relative_or_absolute(task_dir, result_path),
    }


def _parent_score(parent: dict[str, Any]) -> float | None:
    value = parent.get("score")
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _read_text(path: Path | None, limit: int = 20000) -> str:
    if path is None or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _upsert_card_index(task_dir: Path, record: dict[str, Any]) -> None:
    index_path = task_dir / "memory_bank" / "card_index.jsonl"
    rows = _load_jsonl(index_path)
    key = (record.get("round"), record.get("card_path"))
    filtered = [
        row for row in rows
        if (row.get("round"), row.get("card_path")) != key
        and row.get("round") != record.get("round")
    ]
    filtered.append(record)
    filtered.sort(key=lambda row: int(row.get("round") if row.get("round") is not None else -1))
    _write_jsonl(index_path, filtered)


def _build_soft_lines(
    *,
    task_dir: Path,
    round_num: int,
    round_summary: dict[str, Any],
    result: dict[str, Any],
    validation: dict[str, Any],
    failure_taxonomy: dict[str, Any],
    cost_risk: dict[str, Any],
    delta_label: str,
    status: str,
) -> list[str]:
    method_family = str(round_summary.get("method_family") or result.get("effective_method_family") or "unknown")
    core_components = (
        round_summary.get("core_components")
        if isinstance(round_summary.get("core_components"), list)
        else []
    )
    method_keywords = _stable_unique([method_family, *core_components], limit=10)
    score = _round_score(result)
    score_text = f"{score:.6f}" if score is not None else "N/A"
    method_summary = _full_inline(round_summary.get("method_summary"))
    method_profile = _compact_inline(round_summary.get("method_profile"), limit=1200)
    if not method_profile:
        summary = method_summary or _compact_inline("No method summary was produced.", limit=360)
        reflection = _compact_inline(
            round_summary.get("result_reflection") or validation.get("feedback") or "No validation reflection was produced.",
            limit=360,
        )
        novelty = _compact_inline(
            round_summary.get("novelty_vs_best")
            or "Use the linked code, feedback, and diff artifacts to compare against prior methods.",
            limit=300,
        )
        method_profile = " ".join([
            f"Method family `{method_family}` used components [{', '.join(method_keywords) or 'unknown'}] and ended with status `{result.get('status') or validation.get('status') or 'unknown'}` at score {score_text}.",
            summary,
            reflection,
            novelty,
        ])
    risk_tags = cost_risk.get("risk_tags") if isinstance(cost_risk.get("risk_tags"), list) else []
    validation_signal_source = str(
        round_summary.get("result_reflection")
        or validation.get("feedback")
        or "No validation signal was recorded."
    )
    validation_status = str(validation.get("status") or result.get("status") or "").lower()
    if score is not None and validation_status in {"success", "completed"}:
        validation_signal_source = re.split(
            r"\s*;?\s*diagnostics\s*:\s*",
            validation_signal_source,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].rstrip(" ;.")
    validation_signal = _compact_inline(validation_signal_source, limit=700)
    card_reuse_risk = _compact_inline(
        round_summary.get("card_reuse_risk")
        or round_summary.get("memory_reuse_signal")
        or round_summary.get("novelty_vs_best"),
        limit=700,
    )
    failure_primary = _compact_inline(failure_taxonomy.get("primary") or "none", limit=240)
    risk_text = "; ".join(risk_tags) or failure_primary or "none"
    return [
        "## Method Portrait",
        f"- soft_summary_status: {status}",
        f"- method_family: {method_family}",
        f"- core_components: {', '.join(method_keywords) or 'unknown'}",
        f"- method_summary: {method_summary or 'No method summary was produced.'}",
        f"- method_profile: {method_profile}",
        f"- reuse_risk: {card_reuse_risk or 'none recorded'}",
        "",
        "## Result Signal",
        f"- validation_signal: {validation_signal}",
        f"- cost: {cost_risk.get('cost_bucket')}; sandbox_run_time={cost_risk.get('sandbox_run_time')}",
        f"- risk: {risk_text}",
        "",
    ]


def _pending_soft_lines(delta_label: str) -> list[str]:
    return [
        "## Method Portrait",
        "- soft_summary_status: pending_local_async",
        "- method_family: pending",
        "- core_components: pending",
        "- method_summary: pending",
        "- method_profile: pending",
        "- reuse_risk: pending",
        "",
        "## Result Signal",
        "- validation_signal: pending",
        f"- cost: pending; hard delta label is {delta_label}",
        "- risk: pending",
        "",
    ]


def _replace_soft_block(card_path: Path, soft_lines: list[str]) -> None:
    text = card_path.read_text(encoding="utf-8", errors="replace")
    portrait_marker = "\n## Method Portrait\n"
    marker = "\n## Soft Summary\n"
    legacy_marker = "\n## 软总结\n"
    if portrait_marker in text:
        prefix = text.split(portrait_marker, 1)[0].rstrip()
    elif marker in text:
        prefix = text.split(marker, 1)[0].rstrip()
    elif legacy_marker in text:
        prefix = text.split(legacy_marker, 1)[0].rstrip()
    else:
        prefix = text.rstrip()
    text = prefix + "\n\n" + "\n".join(soft_lines)
    card_path.write_text(text, encoding="utf-8")


def _update_card_index_soft_status(
    *,
    task_dir: Path,
    round_num: int,
    card_rel: str,
    status: str,
    method_family: str | None = None,
) -> None:
    index_path = task_dir / "memory_bank" / "card_index.jsonl"
    rows = _load_jsonl(index_path)
    changed = False
    for row in rows:
        if row.get("round") == round_num and row.get("card_path") == card_rel:
            row["soft_summary_status"] = status
            if method_family:
                row["method_family"] = method_family
            row["updated_at"] = datetime.now().isoformat()
            changed = True
    if changed:
        _write_jsonl(index_path, rows)


def _schedule_soft_summary_update(
    *,
    task_dir: Path,
    card_path: Path,
    card_rel: str,
    round_num: int,
    soft_lines: list[str],
    method_family: str | None,
) -> None:
    def worker() -> None:
        try:
            _replace_soft_block(card_path, soft_lines)
            _update_card_index_soft_status(
                task_dir=task_dir,
                round_num=round_num,
                card_rel=card_rel,
                status="completed_local",
                method_family=method_family,
            )
        except Exception:
            try:
                _update_card_index_soft_status(
                    task_dir=task_dir,
                    round_num=round_num,
                    card_rel=card_rel,
                    status="failed",
                    method_family=method_family,
                )
            except Exception:
                pass

    thread = threading.Thread(
        target=worker,
        name=f"memory-card-soft-round-{round_num}",
        daemon=True,
    )
    with _SOFT_THREADS_LOCK:
        _SOFT_THREADS.append(thread)
    thread.start()


_CONTROL_METHOD_COMPONENTS = {
    "draft",
    "debug",
    "improve",
    "initial_seed",
    "required_seed",
    "plateau_new_seed",
    "new_seed_score_first",
    "final_audit",
    "standard",
    "timeout_recovery",
    "high_risk_parent",
}


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "", "none", "unknown", "N/A") else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "", "none", "unknown") else None
    except (TypeError, ValueError):
        return None


def _parse_markdown_sections(path: Path) -> dict[str, Any]:
    """Parse the framework's own stable Markdown bullets without accepting free-form structure."""
    if not path.exists():
        return {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    sections: dict[str, dict[str, Any]] = {}
    current = ""
    for line in lines:
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = re.sub(r"[^a-z0-9]+", "_", heading.group(1).lower()).strip("_")
            sections.setdefault(current, {"items": []})
            continue
        if not current:
            continue
        bullet = re.match(r"^\s*-\s+(.*)$", line)
        if not bullet:
            continue
        text = bullet.group(1).strip()
        keyed = re.match(r"^([a-z_]+)\s*:\s*(.*)$", text, flags=re.IGNORECASE)
        if keyed:
            sections[current][keyed.group(1).lower()] = keyed.group(2).strip()
        elif text:
            sections[current]["items"].append(text)
    return sections


def _card_portrait(
    task_dir: Path,
    row: dict[str, Any],
    *,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    card_path = _resolve_task_path(task_dir, row.get("card_path"))
    sections = _parse_markdown_sections(card_path) if card_path else {}
    meta = sections.get("meta") if isinstance(sections.get("meta"), dict) else {}
    portrait = sections.get("method_portrait") if isinstance(sections.get("method_portrait"), dict) else {}
    method_family = str((override or {}).get("method_family") or portrait.get("method_family") or row.get("method_family") or "unknown")
    method_summary = _full_inline(
        (override or {}).get("method_summary")
        or portrait.get("method_summary")
        or row.get("method_summary")
        or "No method summary was available."
    )
    raw_components = (override or {}).get("core_components")
    if not isinstance(raw_components, list):
        raw_components = [item.strip() for item in str(portrait.get("core_components") or "").split(",") if item.strip()]
    if not raw_components:
        raw_components = row.get("method_keywords") if isinstance(row.get("method_keywords"), list) else []
    excluded = {
        re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
        for value in (row.get("branch"), row.get("branch_state"), meta.get("branch"), meta.get("branch_state"))
    }
    excluded.update(_CONTROL_METHOD_COMPONENTS)
    components: list[str] = []
    for value in [method_family, *raw_components]:
        text = str(value or "").strip()
        normalized = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
        if text and normalized and normalized not in excluded:
            components.append(text)
    return {
        "method_family": method_family,
        "method_summary": method_summary,
        "core_components": _stable_unique(components),
    }


def _best_prior_draft_row(
    rows: list[dict[str, Any]],
    *,
    current_round: int,
    higher_is_better: bool,
) -> dict[str, Any] | None:
    candidates = [
        row for row in rows
        if _normalize_branch_name(str(row.get("branch") or "")) == "draft"
        and (_optional_int(row.get("round")) is not None)
        and int(row["round"]) < current_round
        and _optional_float(row.get("score")) is not None
        and str(row.get("card_path") or "").strip()
    ]
    if not candidates:
        return None
    if higher_is_better:
        return min(candidates, key=lambda row: (-float(row["score"]), int(row["round"])))
    return min(candidates, key=lambda row: (float(row["score"]), int(row["round"])))


def _draft_diff_path(task_dir: Path, current_round: int, reference_round: int) -> Path:
    return task_dir / "memory_bank" / "diffs" / f"round_{current_round:03d}_vs_draft_{reference_round}.md"


def _write_draft_comparison_diff(
    *,
    task_dir: Path,
    task_name: str,
    current: dict[str, Any],
    reference: dict[str, Any],
    higher_is_better: bool,
    portrait_overrides: dict[int, dict[str, Any]],
) -> str:
    current_round = int(current["round"])
    reference_round = int(reference["round"])
    current_score = float(current["score"])
    reference_score = float(reference["score"])
    delta = _metric_aligned_delta(current_score, reference_score, higher_is_better)
    label = _delta_label(delta)
    current_portrait = _card_portrait(task_dir, current, override=portrait_overrides.get(current_round))
    reference_portrait = _card_portrait(task_dir, reference, override=portrait_overrides.get(reference_round))

    current_components = current_portrait["core_components"]
    reference_components = reference_portrait["core_components"]
    current_keys = {re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") for item in current_components}
    reference_keys = {re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") for item in reference_components}
    shared = [item for item in current_components if re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") in reference_keys]
    current_only = [item for item in current_components if re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") not in reference_keys]
    reference_only = [item for item in reference_components if re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") not in current_keys]

    if delta is not None and delta > 1e-12:
        better, worse = current, reference
        better_score, worse_score = current_score, reference_score
    elif delta is not None and delta < -1e-12:
        better, worse = reference, current
        better_score, worse_score = reference_score, current_score
    else:
        better = worse = {}
        better_score = worse_score = None
    better_margin = (
        _metric_aligned_delta(better_score, worse_score, higher_is_better)
        if better_score is not None and worse_score is not None else None
    )
    diff_path = _draft_diff_path(task_dir, current_round, reference_round)
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Round {current_round:03d} Draft Method Comparison",
        "",
        "## Meta",
        "- schema_version: draft_method_diff_v1",
        "- comparison_type: draft_vs_best_prior_draft",
        f"- task: {task_name}",
        "- branch: draft",
        f"- reference_round: {reference_round}",
        f"- reference_commit: {reference.get('commit') or 'none'}",
        f"- reference_card: {reference.get('card_path') or 'none'}",
        f"- current_round: {current_round}",
        f"- current_commit: {current.get('commit') or 'none'}",
        f"- current_card: {current.get('card_path') or 'none'}",
        "",
        "## Method Comparison",
        f"- reference_method_family: {reference_portrait['method_family']}",
        f"- reference_method_summary: {reference_portrait['method_summary']}",
        f"- current_method_family: {current_portrait['method_family']}",
        f"- current_method_summary: {current_portrait['method_summary']}",
        f"- shared_components: {', '.join(shared) or 'none'}",
        f"- reference_only_components: {', '.join(reference_only) or 'none'}",
        f"- current_only_components: {', '.join(current_only) or 'none'}",
        "",
        "## Result",
        f"- reference_score: {reference_score}",
        f"- current_score: {current_score}",
        f"- metric_direction: {'higher' if higher_is_better else 'lower'}",
        f"- metric_aligned_delta: {delta if delta is not None else 'unknown'}",
        f"- score_change_label: {label}",
        f"- better_round: {better.get('round') if better else 'none'}",
        f"- better_score: {better_score if better_score is not None else 'none'}",
        f"- worse_round: {worse.get('round') if worse else 'none'}",
        f"- worse_score: {worse_score if worse_score is not None else 'none'}",
        f"- better_aligned_margin: {better_margin if better_margin is not None else 'none'}",
        "- result_basis: mechanical comparison of two independent scored draft methods; better/worse follows metric_direction.",
        "",
    ]
    diff_path.write_text("\n".join(lines), encoding="utf-8")
    return _relative_or_absolute(task_dir, diff_path)


def _ensure_draft_comparison_diffs(
    *,
    task_dir: Path,
    task_name: str,
    higher_is_better: bool,
    portrait_overrides: dict[int, dict[str, Any]] | None = None,
) -> None:
    """Backfill one best-prior comparison per scored draft and keep the index idempotent."""
    index_path = task_dir / "memory_bank" / "card_index.jsonl"
    rows = _load_jsonl(index_path)
    overrides = portrait_overrides or {}
    drafts = sorted(
        [
            row for row in rows
            if _normalize_branch_name(str(row.get("branch") or "")) == "draft"
            and _optional_int(row.get("round")) is not None
            and _optional_float(row.get("score")) is not None
            and str(row.get("card_path") or "").strip()
        ],
        key=lambda row: int(row["round"]),
    )
    changed = False
    prior: list[dict[str, Any]] = []
    for current in drafts:
        current_round = int(current["round"])
        reference = _best_prior_draft_row(prior, current_round=current_round, higher_is_better=higher_is_better)
        if reference is None:
            prior.append(current)
            continue
        reference_round = int(reference["round"])
        diff_path = _draft_diff_path(task_dir, current_round, reference_round)
        if not diff_path.exists() or current_round in overrides:
            _write_draft_comparison_diff(
                task_dir=task_dir,
                task_name=task_name,
                current=current,
                reference=reference,
                higher_is_better=higher_is_better,
                portrait_overrides=overrides,
            )
        comparison_delta = _metric_aligned_delta(float(current["score"]), float(reference["score"]), higher_is_better)
        expected = {
            "diff_kind": "draft_vs_best_prior_draft",
            "comparison_round": reference_round,
            "comparison_score": float(reference["score"]),
            "metric_aligned_delta_vs_comparison": comparison_delta,
            "diff_path": _relative_or_absolute(task_dir, diff_path),
        }
        for key, value in expected.items():
            if current.get(key) != value:
                current[key] = value
                changed = True
        prior.append(current)
    if changed:
        _write_jsonl(index_path, rows)


def _parent_diff_experience(task_dir: Path, path: Path, sections: dict[str, Any]) -> dict[str, Any] | None:
    meta = sections.get("meta") if isinstance(sections.get("meta"), dict) else {}
    result = sections.get("result") if isinstance(sections.get("result"), dict) else {}
    label = str(result.get("score_change_label") or "").lower()
    if label not in {"improved", "worsened"}:
        return None
    parent_score = _optional_float(result.get("parent_score"))
    current_score = _optional_float(result.get("current_score"))
    delta = _optional_float(result.get("metric_aligned_delta"))
    parent_round = _optional_int(meta.get("parent_round"))
    current_round = _optional_int(meta.get("current_round"))
    if None in {parent_score, current_score, delta, parent_round, current_round}:
        return None
    action_section = sections.get("action") if isinstance(sections.get("action"), dict) else {}
    reason_section = sections.get("reason") if isinstance(sections.get("reason"), dict) else {}
    action = "; ".join(action_section.get("items") or []) or "No method action was recorded."
    reason = "; ".join(reason_section.get("items") or []) or "No method reason was recorded."
    outcome = "improved" if label == "improved" else "worsened"
    return {
        "bucket": "positive" if label == "improved" else "negative",
        "sort_key": (int(current_round), int(parent_round), path.name),
        "title": f"parent_patch_r{current_round}_vs_r{parent_round}",
        "metadata": [
            ("comparison_type", "parent_patch"),
            ("source_diff", _relative_or_absolute(task_dir, path)),
            ("reference_round", parent_round),
            ("reference_commit", meta.get("parent_commit") or "none"),
            ("reference_score", parent_score),
            ("current_round", current_round),
            ("current_commit", meta.get("current_commit") or "none"),
            ("current_score", current_score),
            ("metric_direction", result.get("metric_direction") or "unknown"),
            ("metric_aligned_delta", delta),
        ],
        "experience": (
            f"The current method {outcome} the reference score after this recorded change: {action} "
            f"The pre-result rationale was: {reason} This is observed comparative evidence, not a causal claim."
        ),
    }


def _debug_diff_experience(task_dir: Path, path: Path, sections: dict[str, Any]) -> dict[str, Any] | None:
    meta = sections.get("meta") if isinstance(sections.get("meta"), dict) else {}
    result = sections.get("result") if isinstance(sections.get("result"), dict) else {}
    if _normalize_branch_name(str(meta.get("branch") or "")) != "debug":
        return None
    status_parts = re.split(r"\s*->\s*", str(result.get("status_change") or ""), maxsplit=1)
    if len(status_parts) != 2:
        return None
    parent_status, current_status = (part.strip().lower() for part in status_parts)
    successful_statuses = {"success", "completed"}
    if (
        current_status not in successful_statuses
        or parent_status in successful_statuses | {"", "none", "unknown"}
    ):
        return None
    current_score = _optional_float(result.get("current_score"))
    parent_round = _optional_int(meta.get("parent_round"))
    current_round = _optional_int(meta.get("current_round"))
    if current_score is None or parent_round is None or current_round is None:
        return None
    parent_score = _optional_float(result.get("parent_score"))
    action_section = sections.get("action") if isinstance(sections.get("action"), dict) else {}
    reason_section = sections.get("reason") if isinstance(sections.get("reason"), dict) else {}
    action = "; ".join(action_section.get("items") or []) or "No repair action was recorded."
    reason = "; ".join(reason_section.get("items") or []) or "No failure diagnosis was recorded."
    action_sentence = action if action.endswith((".", "!", "?")) else f"{action}."
    reason_sentence = reason if reason.endswith((".", "!", "?")) else f"{reason}."
    return {
        "bucket": "debug",
        "sort_key": (int(current_round), int(parent_round), path.name),
        "title": f"debug_recovery_r{current_round}_from_r{parent_round}",
        "metadata": [
            ("comparison_type", "debug_recovery"),
            ("source_diff", _relative_or_absolute(task_dir, path)),
            ("parent_round", parent_round),
            ("parent_commit", meta.get("parent_commit") or "none"),
            ("parent_status", parent_status),
            ("parent_score", parent_score if parent_score is not None else "unknown"),
            ("current_round", current_round),
            ("current_commit", meta.get("current_commit") or "none"),
            ("current_status", current_status),
            ("current_score", current_score),
            ("metric_direction", result.get("metric_direction") or "unknown"),
        ],
        "experience": (
            f"The debug round recovered the failed parent by applying: {action_sentence} "
            f"The recorded failure diagnosis and repair rationale was: {reason_sentence} "
            f"The repaired route completed validation with score {current_score}. "
            "This is observed recovery evidence, not a causal claim."
        ),
    }


def _draft_diff_experience(task_dir: Path, path: Path, sections: dict[str, Any]) -> dict[str, Any] | None:
    meta = sections.get("meta") if isinstance(sections.get("meta"), dict) else {}
    methods = sections.get("method_comparison") if isinstance(sections.get("method_comparison"), dict) else {}
    result = sections.get("result") if isinstance(sections.get("result"), dict) else {}
    better_round = _optional_int(result.get("better_round"))
    worse_round = _optional_int(result.get("worse_round"))
    better_score = _optional_float(result.get("better_score"))
    worse_score = _optional_float(result.get("worse_score"))
    margin = _optional_float(result.get("better_aligned_margin"))
    current_round = _optional_int(meta.get("current_round"))
    reference_round = _optional_int(meta.get("reference_round"))
    if None in {better_round, worse_round, better_score, worse_score, margin, current_round, reference_round}:
        return None
    if better_round == current_round:
        better_summary = methods.get("current_method_summary") or "No method summary was available."
        worse_summary = methods.get("reference_method_summary") or "No method summary was available."
        better_only = methods.get("current_only_components") or "none"
        worse_only = methods.get("reference_only_components") or "none"
        better_commit = meta.get("current_commit") or "none"
        worse_commit = meta.get("reference_commit") or "none"
    else:
        better_summary = methods.get("reference_method_summary") or "No method summary was available."
        worse_summary = methods.get("current_method_summary") or "No method summary was available."
        better_only = methods.get("reference_only_components") or "none"
        worse_only = methods.get("current_only_components") or "none"
        better_commit = meta.get("reference_commit") or "none"
        worse_commit = meta.get("current_commit") or "none"
    return {
        "bucket": "positive",
        "sort_key": (int(current_round), int(reference_round), path.name),
        "title": f"draft_r{better_round}_over_r{worse_round}",
        "metadata": [
            ("comparison_type", "draft_vs_best_prior_draft"),
            ("source_diff", _relative_or_absolute(task_dir, path)),
            ("better_round", better_round),
            ("better_commit", better_commit),
            ("better_score", better_score),
            ("worse_round", worse_round),
            ("worse_commit", worse_commit),
            ("worse_score", worse_score),
            ("metric_direction", result.get("metric_direction") or "unknown"),
            ("better_aligned_margin", margin),
        ],
        "experience": (
            f"The better-scoring draft used: {better_summary} The lower-scoring draft used: {worse_summary} "
            f"Components unique to the better draft were [{better_only}]; components unique to the worse draft were [{worse_only}]. "
            "This is observed comparative evidence, not a causal claim."
        ),
    }


def rebuild_high_level_memory(task_dir: Path, *, task_name: str | None = None) -> str:
    """Atomically rebuild the English task-level experience view from stable diff artifacts."""
    diffs_dir = task_dir / "memory_bank" / "diffs"
    experiences: list[dict[str, Any]] = []
    if diffs_dir.exists():
        for path in sorted(diffs_dir.glob("*.md")):
            sections = _parse_markdown_sections(path)
            meta = sections.get("meta") if isinstance(sections.get("meta"), dict) else {}
            schema = str(meta.get("schema_version") or "")
            if schema == "method_diff_v2":
                experience = _parent_diff_experience(task_dir, path, sections)
                debug_experience = _debug_diff_experience(task_dir, path, sections)
            elif schema == "draft_method_diff_v1":
                experience = _draft_diff_experience(task_dir, path, sections)
                debug_experience = None
            else:
                experience = None
                debug_experience = None
            if experience:
                experiences.append(experience)
            if debug_experience:
                experiences.append(debug_experience)
    experiences.sort(key=lambda item: item["sort_key"])
    lines = [
        "# High-Level Memory",
        "",
        "- schema_version: high_level_memory_v2",
        f"- task: {task_name or task_dir.name}",
        "- source: derived from memory_bank/diffs; cards and diffs remain authoritative evidence",
        "- interpretation: score comparisons are observed associations; debug recoveries are observed failure-to-success transitions; neither establishes causality",
        "",
    ]
    for heading, bucket in (
        ("Positive Experiences", "positive"),
        ("Negative Experiences", "negative"),
        ("Debug Experiences", "debug"),
    ):
        lines.append(f"## {heading}")
        selected = [item for item in experiences if item["bucket"] == bucket]
        if not selected:
            lines.extend(["", "- None yet.", ""])
            continue
        lines.append("")
        for index, item in enumerate(selected, start=1):
            lines.append(f"{index}. **{item['title']}**")
            for key, value in item["metadata"]:
                lines.append(f"   - {key}: {value}")
            lines.append(f"   - experience: {item['experience']}")
            lines.append("")
    high_level_path = task_dir / "memory_bank" / HIGH_LEVEL_MEMORY_FILENAME
    high_level_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = high_level_path.with_name(f".{high_level_path.name}.tmp")
    temp_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    temp_path.replace(high_level_path)
    return _relative_or_absolute(task_dir, high_level_path)


def write_round_memory_artifacts(
    *,
    task_dir: Path,
    metadata: dict[str, Any],
    result: dict[str, Any],
    higher_is_better: bool,
) -> dict[str, Any]:
    """Write task-local memory card and, when possible, parent-to-current diff."""
    memory_dir = task_dir / "memory_bank"
    cards_dir = memory_dir / "cards"
    diffs_dir = memory_dir / "diffs"
    cards_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir.mkdir(parents=True, exist_ok=True)

    round_num = int(result.get("round") if result.get("round") is not None else -1)
    branch_decision = result.get("branch_decision") if isinstance(result.get("branch_decision"), dict) else {}
    branch = _normalize_branch_name(str(result.get("branch") or branch_decision.get("branch") or ""))
    branch_state = str(branch_decision.get("branch_state") or branch_decision.get("search_state") or "")
    branch_reason = str(branch_decision.get("branch_reason") or branch_decision.get("reason") or "")
    validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
    status = str(result.get("status") or validation.get("status") or "unknown")
    score = _round_score(result)
    commit = str(result.get("commit_hash") or result.get("commit") or "").strip()
    parent = _primary_parent(branch, branch_decision)
    parent_score = _parent_score(parent)
    delta = _metric_aligned_delta(score, parent_score, higher_is_better)
    round_summary = result.get("round_summary") if isinstance(result.get("round_summary"), dict) else {}
    solution_contract = result.get("solution_contract") if isinstance(result.get("solution_contract"), dict) else {}
    failure_taxonomy = validation.get("failure_taxonomy") if isinstance(validation.get("failure_taxonomy"), dict) else {}
    early_eda = result.get("early_eda") if isinstance(result.get("early_eda"), dict) else {}
    artifacts = _artifact_paths(task_dir, result)

    suffix = commit[:8] if commit else _safe_slug(status)
    card_path = cards_dir / f"round_{round_num:03d}_{suffix}.md"
    card_rel = _relative_or_absolute(task_dir, card_path)
    diff_rel = ""

    delta_label = _delta_label(delta)
    method_family = round_summary.get("method_family") or result.get("effective_method_family")
    cost_risk = _cost_risk_signal(
        result=result,
        validation=validation,
        solution_contract=solution_contract,
        failure_taxonomy=failure_taxonomy,
        score=score,
        parent_score=parent_score,
        delta=delta,
    )
    completed_soft_lines = _build_soft_lines(
        task_dir=task_dir,
        round_num=round_num,
        round_summary=round_summary,
        result=result,
        validation=validation,
        failure_taxonomy=failure_taxonomy,
        cost_risk=cost_risk,
        delta_label=delta_label,
        status="completed_local",
    )
    hard_lines = [
        f"# Round {round_num:03d} Memory Card",
        "",
        "## Meta",
        "- schema_version: memory_card_v2",
        f"- task: {metadata.get('task_name', task_dir.name)}",
        f"- round: {round_num}",
        f"- branch: {branch}",
        f"- branch_state: {branch_state}",
        f"- commit: {commit or 'none'}",
        f"- status: {status}",
        f"- score: {score if score is not None else 'none'}",
        f"- metric_direction: {'higher' if higher_is_better else 'lower'}",
        f"- sandbox_run_time: {validation.get('run_time')}",
        f"- risk_tags: {', '.join(cost_risk.get('risk_tags') or []) or 'none'}",
        f"- artifacts: solution={artifacts['solution']}; feedback={artifacts['feedback']}; context={artifacts['context']}; post_code_memory_summary={artifacts['post_code_memory_summary']}; result={artifacts['result']}",
        "",
    ]
    card_path.write_text("\n".join(hard_lines + _pending_soft_lines(delta_label)), encoding="utf-8")

    if parent:
        current_code_path = _resolve_task_path(task_dir, artifacts.get("solution"))
        current_code = _read_text(current_code_path)
        if current_code:
            diff_path = diffs_dir / f"round_{round_num:03d}_vs_{'anchor' if branch == 'improve' else 'parent'}_{parent.get('round', 'unknown')}.md"
            diff_rel = _relative_or_absolute(task_dir, diff_path)
            action_summary = _compact_inline(
                round_summary.get("diff_action")
                or round_summary.get("parent_modification_summary")
                or "none",
                limit=900,
            )
            reason_summary = _compact_inline(
                round_summary.get("diff_reason")
                or "No Codex-written diff reason was recorded.",
                limit=900,
            )
            result_note = _compact_inline(
                round_summary.get("result_reflection")
                or validation.get("feedback")
                or "No validation result reflection was available.",
                limit=700,
            )
            diff_lines = [
                f"# Round {round_num:03d} Method Diff",
                "",
                "## Meta",
                "- schema_version: method_diff_v2",
                f"- task: {metadata.get('task_name', task_dir.name)}",
                f"- branch: {branch}",
                f"- parent_round: {parent.get('round', 'unknown')}",
                f"- parent_commit: {parent.get('commit') or 'none'}",
                f"- current_round: {round_num}",
                f"- current_commit: {commit or 'none'}",
                f"- parent_card: {parent.get('card_path') or parent.get('memory_card_path') or 'none'}",
                f"- current_card: {card_rel}",
                "",
                "## Action",
                f"- {action_summary}",
                "",
                "## Reason",
                f"- {reason_summary}",
                "",
                "## Result",
                f"- parent_score: {parent_score if parent_score is not None else 'unknown'}",
                f"- current_score: {score if score is not None else 'unknown'}",
                f"- metric_direction: {'higher' if higher_is_better else 'lower'}",
                f"- metric_aligned_delta: {delta if delta is not None else 'unknown'}",
                f"- score_change_label: {delta_label}",
                f"- status_change: {parent.get('status', 'unknown')} -> {status}",
                f"- sandbox_run_time: {validation.get('run_time')}",
                f"- material_tolerance: {cost_risk.get('material_tolerance')}",
                f"- result_basis: mechanical score/status comparison after sandbox; score_change_label is the positive/negative optimization signal.",
                f"- result_note: {result_note}",
                "",
            ]
            diff_path.write_text("\n".join(diff_lines), encoding="utf-8")

    comparison_type = "parent_patch" if diff_rel and parent else ""
    comparison_round = _optional_int(parent.get("round")) if parent else None
    comparison_score = parent_score if parent else None
    comparison_delta = delta if parent else None
    if branch == "draft" and score is not None:
        prior_rows = _load_jsonl(memory_dir / "card_index.jsonl")
        draft_reference = _best_prior_draft_row(
            prior_rows,
            current_round=round_num,
            higher_is_better=higher_is_better,
        )
        if draft_reference is not None:
            comparison_type = "draft_vs_best_prior_draft"
            comparison_round = int(draft_reference["round"])
            comparison_score = float(draft_reference["score"])
            comparison_delta = _metric_aligned_delta(score, comparison_score, higher_is_better)
            diff_rel = _relative_or_absolute(
                task_dir,
                _draft_diff_path(task_dir, round_num, comparison_round),
            )

    index_record = {
        "schema_version": "memory_card_index_v1",
        "task": metadata.get("task_name", task_dir.name),
        "round": round_num,
        "branch": branch,
        "branch_state": branch_state,
        "branch_reason": branch_reason,
        "status": status,
        "score": score,
        "metric_direction": "higher" if higher_is_better else "lower",
        "metric_aligned_delta_vs_parent": delta,
        "delta_label": delta_label,
        "cost_bucket": cost_risk.get("cost_bucket"),
        "reward_bucket": cost_risk.get("reward_bucket"),
        "risk_tags": cost_risk.get("risk_tags") or [],
        "sandbox_run_time": cost_risk.get("sandbox_run_time"),
        "commit": commit or None,
        "method_family": method_family,
        "method_keywords": _stable_unique([
            method_family,
            *(
                round_summary.get("core_components")
                if isinstance(round_summary.get("core_components"), list)
                else []
            ),
        ], limit=10),
        "card_path": card_rel,
        "diff_path": diff_rel,
        "parent_binding": parent or {"role": "none"},
        "artifacts": artifacts,
        "soft_summary_status": "pending_local_async",
        "updated_at": datetime.now().isoformat(),
    }
    if comparison_type:
        index_record.update({
            "diff_kind": comparison_type,
            "comparison_round": comparison_round,
            "comparison_score": comparison_score,
            "metric_aligned_delta_vs_comparison": comparison_delta,
        })
    _upsert_card_index(task_dir, index_record)
    current_portrait = {
        "method_family": method_family or "unknown",
        "method_summary": _full_inline(round_summary.get("method_summary") or "No method summary was available."),
        "core_components": (
            list(round_summary.get("core_components") or [])
            if isinstance(round_summary.get("core_components"), list) else []
        ),
    }
    _ensure_draft_comparison_diffs(
        task_dir=task_dir,
        task_name=str(metadata.get("task_name") or task_dir.name),
        higher_is_better=higher_is_better,
        portrait_overrides={round_num: current_portrait},
    )
    high_level_memory_rel = rebuild_high_level_memory(
        task_dir,
        task_name=str(metadata.get("task_name") or task_dir.name),
    )
    result["memory_card_path"] = card_rel
    if diff_rel:
        result["memory_diff_path"] = diff_rel
    result["high_level_memory_path"] = high_level_memory_rel
    _schedule_soft_summary_update(
        task_dir=task_dir,
        card_path=card_path,
        card_rel=card_rel,
        round_num=round_num,
        soft_lines=completed_soft_lines,
        method_family=str(method_family or "unknown"),
    )
    return {
        "status": "memory_card_written",
        "memory_card_path": card_rel,
        "memory_diff_path": diff_rel,
        "high_level_memory_path": high_level_memory_rel,
        "soft_summary_status": "pending_local_async",
    }
