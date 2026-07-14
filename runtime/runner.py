from __future__ import annotations

import ast

from .common import *
from .constants import *
from .search_graph import render_search_graph_artifacts

def _classify_skill_source_path(source_path: Path, task_name: str) -> tuple[str, str]:
    """Return a prompt-facing source label and title for a routed skill path."""
    path_text = str(source_path).lower()
    name = source_path.name.lower()
    expected_task_skill = f"skill_{task_name.lower()}.md"
    if name == expected_task_skill or (name.startswith("skill_") and "mle-reimagined" in path_text):
        return "task_skill_source", "Task Skill Source"
    if "failure" in name or "error" in name or "mle_skill_error" in path_text:
        return "failure_prevention_skill_source", "Failure Prevention Skill Source"
    return "routed_skill_source", "Routed Skill Source"


def persist_runtime_skill_sources(task_dir: Path, skill_route: "SkillRoute") -> "SkillRoute":
    """Persist prompt-safe routed skill sources for optional context expansion."""
    if not skill_route.sources:
        return skill_route
    context_dir = task_dir / "context_sources"
    context_dir.mkdir(parents=True, exist_ok=True)
    persisted_sources: list[str] = []
    used_names: dict[str, int] = {}
    for idx, source in enumerate(skill_route.sources, start=1):
        source_path = Path(str(source))
        try:
            raw = source_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            persisted_sources.append(str(source))
            continue
        source_label, source_title = _classify_skill_source_path(source_path, task_dir.name)
        used_names[source_label] = used_names.get(source_label, 0) + 1
        cleaned = sanitize_legacy_prediction_file_language(raw).strip()
        header = "\n".join([
            f"# {source_title}",
            "",
            f"Original source: {source_path}",
            "",
            "Legacy cross-round prediction-file instructions, if present in the original, have been rewritten here as current-run diagnostics. The coding prompt and runtime static gate allow only `submission.csv` as the solution output file.",
            "",
        ])
        target = context_dir / f"{source_label}_{used_names[source_label]}.md"
        target.write_text(header + cleaned + "\n", encoding="utf-8")
        persisted_sources.append(str(target))
    return SkillRoute(
        branch=skill_route.branch,
        reason=skill_route.reason,
        sources=persisted_sources,
        content=skill_route.content,
    )


def _compact_feedback_excerpt(*values: Any, limit: int = 1200) -> str:
    text = "\n\n".join(str(value or "").strip() for value in values if str(value or "").strip())
    if not text:
        return ""
    return shrink_text_middle(text, limit)


def _compact_decision_for_summary(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict):
        return {}
    score_feedback = decision.get("score_feedback") if isinstance(decision.get("score_feedback"), dict) else {}
    return {
        "schema_version": decision.get("schema_version"),
        "round": decision.get("round"),
        "branch": decision.get("branch"),
        "branch_state": decision.get("branch_state"),
        "branch_reason": decision.get("branch_reason") or decision.get("reason"),
        "runtime_profile": decision.get("runtime_profile"),
        "eda_mode": decision.get("eda_mode"),
        "deep_eda_advice": decision.get("deep_eda_advice"),
        "parent_binding": decision.get("parent_binding"),
        "draft_prior_memory": decision.get("draft_prior_memory"),
        "score_feedback": {
            "status": score_feedback.get("status"),
            "latest_delta_vs_previous_best": score_feedback.get("latest_delta_vs_previous_best"),
            "latest_delta_vs_current_best": score_feedback.get("latest_delta_vs_current_best"),
            "material_tolerance": score_feedback.get("material_tolerance"),
            "issues": (score_feedback.get("issues") or [])[:4] if isinstance(score_feedback.get("issues"), list) else [],
            "required_response": (score_feedback.get("required_response") or [])[:4]
                if isinstance(score_feedback.get("required_response"), list) else [],
        },
        "budget": decision.get("budget"),
        "external_timeout_plan": decision.get("external_timeout_plan"),
        "validation_timeout_seconds": decision.get("validation_timeout_seconds"),
    }


def compact_round_for_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Write compact round metadata to rounds_summary.json; full artifacts live by path."""
    validation = row.get("validation") if isinstance(row.get("validation"), dict) else {}
    solution_contract = row.get("solution_contract") if isinstance(row.get("solution_contract"), dict) else {}
    round_summary = row.get("round_summary") if isinstance(row.get("round_summary"), dict) else {}
    early_eda = row.get("early_eda") if isinstance(row.get("early_eda"), dict) else {}
    submit = row.get("submit") if isinstance(row.get("submit"), dict) else {}
    graph_node = row.get("graph_node") if isinstance(row.get("graph_node"), dict) else {}
    quality = validation.get("quality") if isinstance(validation.get("quality"), dict) else {}
    failure_taxonomy = validation.get("failure_taxonomy") if isinstance(validation.get("failure_taxonomy"), dict) else {}
    branch_decision = row.get("branch_decision") if isinstance(row.get("branch_decision"), dict) else {}
    compact = {
        "schema_version": "round_summary_compact_v1",
        "round": row.get("round"),
        "task_name": row.get("task_name"),
        "branch": row.get("branch"),
        "effective_branch": row.get("effective_branch"),
        "commit_hash": row.get("commit_hash") or row.get("commit"),
        "status": row.get("status") or validation.get("status"),
        "score": validation.get("score") if validation else row.get("score"),
        "raw_score": validation.get("raw_score"),
        "reward": validation.get("reward"),
        "round_wall_time": row.get("round_wall_time"),
        "input_tokens": row.get("input_tokens"),
        "output_tokens": row.get("output_tokens"),
        "code_chars": len(str(row.get("code") or "")) if row.get("code") is not None else None,
        "code_path": row.get("code_path"),
        "validation_feedback_path": row.get("validation_feedback_path"),
        "failure_artifact_dir": row.get("failure_artifact_dir"),
        "memory_card_path": row.get("memory_card_path"),
        "memory_diff_path": row.get("memory_diff_path"),
        "graph_node": {
            "node_id": graph_node.get("node_id"),
            "round": graph_node.get("round"),
            "commit": graph_node.get("commit"),
            "memory_card_path": graph_node.get("memory_card_path"),
            "memory_diff_path": graph_node.get("memory_diff_path"),
        } if graph_node else {},
        "branch_decision": _compact_decision_for_summary(branch_decision),
        "effective_lineage": row.get("effective_lineage"),
        "effective_method_family": row.get("effective_method_family"),
        "early_eda": {
            "enabled": early_eda.get("enabled"),
            "mode": early_eda.get("mode"),
            "status": early_eda.get("status"),
            "work_dir": early_eda.get("work_dir"),
            "archive_hit": (early_eda.get("archive") or {}).get("hit") if isinstance(early_eda.get("archive"), dict) else None,
        },
        "solution_contract": {
            "status": solution_contract.get("status"),
            "missing": solution_contract.get("missing") or [],
            "blockers": solution_contract.get("blockers") or [],
            "score_first_envelope": solution_contract.get("score_first_envelope") or {},
        },
        "validation": {
            "phase": validation.get("phase"),
            "timeout": validation.get("timeout"),
            "status_code": validation.get("status_code"),
            "status": validation.get("status"),
            "score": validation.get("score"),
            "raw_score": validation.get("raw_score"),
            "reward": validation.get("reward"),
            "quality": {
                "kind": quality.get("kind"),
                "submit_eligible": quality.get("submit_eligible"),
                "reason": quality.get("reason"),
            },
            "failure_taxonomy": {
                "primary": failure_taxonomy.get("primary"),
                "all": (failure_taxonomy.get("all") or [])[:8] if isinstance(failure_taxonomy.get("all"), list) else [],
                "evidence": failure_taxonomy.get("evidence"),
                "source": failure_taxonomy.get("source"),
                "debug_instruction": failure_taxonomy.get("debug_instruction"),
            },
            "job_id": validation.get("job_id"),
            "queue_time": validation.get("queue_time"),
            "run_time": validation.get("run_time"),
            "experiment_signature": validation.get("experiment_signature"),
            "feedback_excerpt": _compact_feedback_excerpt(validation.get("feedback"), validation.get("clear_run_log")),
        },
        "round_summary": {
            "method_family": round_summary.get("method_family"),
            "core_components": round_summary.get("core_components") or [],
            "method_summary": round_summary.get("method_summary"),
            "method_profile": shrink_text_middle(str(round_summary.get("method_profile") or ""), 900),
            "result_reflection": round_summary.get("result_reflection"),
            "novelty_vs_best": round_summary.get("novelty_vs_best"),
        },
    }
    if submit:
        compact["submit"] = {
            "status_code": submit.get("status_code"),
            "status": submit.get("status"),
            "score": submit.get("score"),
            "reward": submit.get("reward"),
            "job_id": submit.get("job_id"),
            "queue_time": submit.get("queue_time"),
            "run_time": submit.get("run_time"),
            "feedback_excerpt": _compact_feedback_excerpt(submit.get("feedback"), submit.get("clear_run_log")),
        }
    if row.get("error"):
        compact["error_excerpt"] = shrink_text_middle(str(row.get("error")), 800)
    return compact


def compact_rounds_for_summary(all_rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compact_round_for_summary(row) for row in all_rounds if isinstance(row, dict)]


def write_rounds_summary_with_search_graph(
    *,
    summary_file: Path,
    summary_data: dict[str, Any],
    task_dir: Path,
    higher_is_better: bool,
) -> None:
    """Persist compact summary, then best-effort refresh human-only graphic.png."""
    summary_file.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")
    try:
        render_search_graph_artifacts(
            task_dir,
            higher_is_better=higher_is_better,
        )
    except Exception as exc:
        logger.warning("[%s] Human-only search graph graphic refresh failed: %s", task_dir.name, exc)


async def evaluate_single_task_single_round(
    sandbox_client: httpx.AsyncClient,
    task: dict[str, Any],
    round_num: int,
    output_dir: Path,
    model: str,
    reasoning_level: str,
    max_tokens: int,
    temperature: float,
    best_score_so_far: float | None = None,
    higher_is_better: bool = True,
    task_skills_dir: Path = DEFAULT_TASK_SKILLS_DIR,
    eda_skill_dir: Path = DEFAULT_EDA_SKILL_DIR,
    error_skill_file: Path = DEFAULT_ERROR_SKILL_FILE,
    local_eda_data_root: Path = DEFAULT_LOCAL_EDA_DATA_ROOT,
    eda_timeout_seconds: int = 900,
    early_eda_branches: tuple[str, ...] = DEFAULT_EARLY_EDA_BRANCHES,
) -> dict[str, Any]:
    """
    Evaluate a single task for one round using search-oriented storage.
    """
    round_start_time = time.time()

    if "metadata" not in task or "prompt" not in task:
        raise ValueError(f"Task must have 'metadata' and 'prompt' fields, got: {list(task.keys())}")

    metadata = task["metadata"]
    task_name = metadata["task_name"]

    prompt_messages = task["prompt"]
    if hasattr(prompt_messages, "tolist"):
        prompt_messages = prompt_messages.tolist()

    resource_type = metadata.get("cpu_gpu", "cpu")
    resource_type = "cpu" if str(resource_type).lower() == "cpu" else "gpu"
    val_data_dir = metadata.get("data_dir", "")

    logger.info("[%s] Round %s - Starting", task_name, round_num + 1)

    work_dir = output_dir
    solution_file = work_dir / "solution.py"
    current_branch = get_current_branch(output_dir)
    branch_decision_file = output_dir / "index" / "current_branch_decision.json"
    branch_decision = (
        json.loads(branch_decision_file.read_text(encoding="utf-8"))
        if branch_decision_file.exists()
        else {"branch": current_branch}
    )
    branch_decision = apply_latest_failed_parent_fallback(output_dir, branch_decision)
    search_operator = search_operator_from_dict(branch_decision.get("search_operator", {}))
    raw_remaining_budget = (branch_decision.get("budget") or {}).get("remaining_budget")
    prompt_remaining_budget = 43200.0 if raw_remaining_budget is None else max(0.0, float(raw_remaining_budget))
    prompt_search_state = str(branch_decision.get("search_state") or "")
    branch_decision = dict(branch_decision)
    if prompt_remaining_budget <= V3_MIN_ROUND_TIMEOUT_SECONDS:
        return {
            "round": round_num,
            "task_name": task_name,
            "branch": current_branch,
            "branch_decision": branch_decision,
            "status": "sandbox_budget_exhausted",
            "error": "remaining sandbox runtime is below the minimum validation envelope",
            "round_wall_time": time.time() - round_start_time,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    external_timeout_plan = (
        dict(branch_decision.get("external_timeout_plan"))
        if isinstance(branch_decision.get("external_timeout_plan"), dict)
        else {}
    )
    frozen_validation_timeout = (
        external_timeout_plan.get("validation_timeout_seconds")
        if external_timeout_plan.get("schema_version") == "external_timeout_plan_v1"
        else None
    )
    validation_envelope = compute_validation_timeout(
        prompt_remaining_budget,
        search_operator,
        search_state=prompt_search_state,
        branch_state=branch_decision.get("branch_state"),
        runtime_profile=branch_decision.get("runtime_profile"),
    )
    validation_timeout = int(
        min(frozen_validation_timeout, validation_envelope)
        if isinstance(frozen_validation_timeout, (int, float)) and frozen_validation_timeout > 0
        else validation_envelope
    )
    external_timeout_plan.update({
        "schema_version": "external_timeout_plan_v1",
        "validation_timeout_seconds": validation_timeout,
        "remaining_sandbox_runtime_seconds": prompt_remaining_budget,
        "runtime_profile": str(branch_decision.get("runtime_profile") or "standard"),
        "allocation_basis": external_timeout_plan.get("allocation_basis") or "framework_operator_cap",
        "policy": external_timeout_plan.get("policy") or V4_EXTERNAL_TIMEOUT_POLICY,
    })
    branch_decision["validation_timeout_seconds"] = validation_timeout
    branch_decision["external_timeout_plan"] = external_timeout_plan
    try:
        branch_decision_file.write_text(json.dumps(branch_decision, indent=2), encoding="utf-8")
    except Exception:
        logger.debug("[%s] Could not persist external timeout plan", task_name, exc_info=True)
    eda_mode = eda_mode_for_round(branch_decision, current_branch, early_eda_branches)
    should_run_early_eda = eda_mode is not None
    early_eda: dict[str, Any] = {
        "enabled": should_run_early_eda,
        "branch": current_branch,
        "mode": eda_mode or "none",
        "trigger_reason": branch_decision.get("reason"),
    }
    eda_summary_text = ""
    usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0}

    if should_run_early_eda:
        eda_root = "deep_eda" if eda_mode == "deep_bottleneck" else "early_eda"
        eda_work_dir = output_dir / eda_root / f"round_{round_num}"
        eda_work_dir.mkdir(parents=True, exist_ok=True)
        navigation_context = build_refinement_context(output_dir, round_num, higher_is_better=higher_is_better)
        logger.info(
            "[%s] Round %s - Running %s local EDA for branch=%s intent=%s",
            task_name,
            round_num + 1,
            eda_mode,
            current_branch,
            branch_decision.get("search_intent"),
        )
        try:
            archive_record: dict[str, Any] | None = None
            if eda_mode != "deep_bottleneck" and early_eda_archive_available(task_name):
                try:
                    eda_context, eda_summary_text, eda_usage, eda_run_result, archive_record = load_early_eda_archive(
                        task_name=task_name,
                        work_dir=eda_work_dir,
                    )
                    eda_raw_text = "[EARLY EDA ARCHIVE HIT]"
                    eda_summary_raw_text = "[EARLY EDA ARCHIVE HIT]"
                    logger.info(
                        "[%s] Round %s - Reused archived early EDA from %s",
                        task_name,
                        round_num + 1,
                        archive_record.get("source_dir"),
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] Round %s - Early EDA archive load failed; regenerating personalized EDA: %s",
                        task_name,
                        round_num + 1,
                        exc,
                    )
                    archive_record = {
                        "enabled": True,
                        "hit": False,
                        "status": "archive_load_failed",
                        "error": repr(exc),
                    }
            if not archive_record or not archive_record.get("hit"):
                eda_context, eda_raw_text, eda_usage, eda_run_result = await generate_round_eda(
                    work_dir=eda_work_dir,
                    output_dir=output_dir,
                    round_num=round_num,
                    prompt_messages=prompt_messages,
                    metadata=metadata,
                    refinement_context=navigation_context,
                    model=model,
                    reasoning_level=reasoning_level,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    eda_skill_dir=eda_skill_dir,
                    local_eda_data_root=local_eda_data_root,
                    eda_timeout_seconds=eda_timeout_seconds,
                    eda_mode=eda_mode or "early",
                    branch_decision=branch_decision,
                    higher_is_better=higher_is_better,
                )
                usage["input_tokens"] += eda_usage.get("input_tokens", 0)
                usage["output_tokens"] += eda_usage.get("output_tokens", 0)
                eda_summary_text, eda_summary_raw_text, eda_summary_usage = await generate_eda_summary(
                    work_dir=eda_work_dir,
                    output_dir=output_dir,
                    round_num=round_num,
                    prompt_messages=prompt_messages,
                    metadata=metadata,
                    refinement_context=navigation_context,
                    eda_context=eda_context,
                    model=model,
                    reasoning_level=reasoning_level,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    eda_mode=eda_mode or "early",
                )
                usage["input_tokens"] += eda_summary_usage.get("input_tokens", 0)
                usage["output_tokens"] += eda_summary_usage.get("output_tokens", 0)
                if eda_mode != "deep_bottleneck":
                    archive_record = archive_early_eda_outputs(task_name=task_name, work_dir=eda_work_dir)
            eda_status = "completed" if int(eda_run_result.get("return_code") or 0) == 0 else "failed_nonfatal"
            early_eda.update({
                "status": eda_status,
                "work_dir": str(eda_work_dir),
                "raw_text": eda_raw_text,
                "run_result": eda_run_result,
                "summary": eda_summary_text,
                "summary_raw_text": eda_summary_raw_text,
                "archive": archive_record,
            })
        except CodexCliError as e:
            logger.warning("[%s] Round %s - Early EDA LLM infrastructure failure: %s", task_name, round_num + 1, e)
            usage["input_tokens"] += e.usage.get("input_tokens", 0)
            usage["output_tokens"] += e.usage.get("output_tokens", 0)
            return {
                "round": round_num,
                "task_name": task_name,
                "branch": current_branch,
                "early_eda": {
                    "status": e.failure_type,
                    "enabled": should_run_early_eda,
                    "branch": current_branch,
                    "mode": eda_mode or "none",
                },
                "status": e.failure_type,
                "llm_failure": {
                    "phase": "early_eda",
                    "failure_type": e.failure_type,
                    "return_code": e.return_code,
                    "stderr_tail": e.stderr[-1000:],
                },
                "round_wall_time": time.time() - round_start_time,
                **usage,
            }
        except Exception as e:
            logger.warning("[%s] Round %s - Early EDA failed, continuing with integrated coding: %s", task_name, round_num + 1, e)
            early_eda.update({
                "status": "failed_nonfatal",
                "error": str(e),
                "work_dir": str(eda_work_dir),
            })
    else:
        early_eda["status"] = "skipped"
    if solution_file.exists():
        solution_file.unlink()
    clear_active_scratch_workspace(work_dir)
    skill_route = route_skills_for_branch(
        task_name=task_name,
        branch=current_branch,
        task_skills_dir=task_skills_dir,
        eda_skill_dir=eda_skill_dir,
        error_skill_file=error_skill_file,
        branch_decision=branch_decision,
    )
    skill_route = persist_runtime_skill_sources(output_dir, skill_route)
    planning_text = ""
    planning_raw_text = ""
    coding_skill_context = skill_route.content
    refinement_context = None

    incumbent_prefill = {
        "enabled": False,
        "branch": current_branch,
        "parent_role": "none",
        "source_path": "",
        "source_exists": False,
        "reason": "draft_branch_or_no_incumbent_prefill",
    }
    if current_branch != "draft":
        incumbent_prefill = prefill_active_solution_from_incumbent(output_dir, solution_file, branch_decision)
        if (
            str(branch_decision.get("schema_version") or "").startswith("branch_decision_v3")
            and not incumbent_prefill.get("enabled")
        ):
            raise RuntimeError(
                "v3 parent binding could not materialize the implementation base: "
                f"{incumbent_prefill.get('reason') or 'unknown'}"
            )

    max_no_solution_retries = V33_MAX_NO_SOLUTION_RETRIES
    context_eda_data_dir = resolve_local_eda_data_dir(task_name, local_eda_data_root)
    response_text = ""
    call_metadata = dict(metadata)
    call_metadata.pop("search_operator", None)
    call_metadata.update({
        "branch": current_branch,
        "branch_state": branch_decision.get("branch_state"),
        "runtime_profile": branch_decision.get("runtime_profile"),
        "parent_binding": branch_decision.get("parent_binding"),
        "portfolio_action": branch_decision.get("portfolio_action"),
        "portfolio_slot": branch_decision.get("portfolio_slot"),
        "incumbent_prefill": incumbent_prefill,
        "context_eda_data_dir": str(context_eda_data_dir),
        "deep_eda_advice": branch_decision.get("deep_eda_advice"),
        "skill_sources": skill_route.sources,
        "skill_route_reason": skill_route.reason,
    })

    for retry_idx in range(max_no_solution_retries + 1):
        retry_suffix = f"_retry_{retry_idx}" if retry_idx > 0 else ""
        trace_file = output_dir / "traces" / f"round_{round_num}{retry_suffix}_trace.json"

        current_refinement = refinement_context
        if retry_idx > 0:
            retry_hint = (
                f"\n\n[CRITICAL - RETRY {retry_idx}/{max_no_solution_retries}]\n"
                "Your previous attempt did NOT produce a solution.py file.\n"
                "You MUST create a file named `solution.py` in the current working directory.\n"
                "Write the complete solution code to solution.py.\n"
                "Do NOT output the code only as markdown in your response."
            )
            current_refinement = (current_refinement or "") + retry_hint
            if solution_file.exists():
                solution_file.unlink()
            if current_branch != "draft":
                incumbent_prefill = prefill_active_solution_from_incumbent(output_dir, solution_file, branch_decision)
                call_metadata["incumbent_prefill"] = incumbent_prefill
        attempt_prefill_hash = None
        if incumbent_prefill.get("enabled") and solution_file.exists():
            try:
                attempt_prefill_hash = hashlib.sha256(solution_file.read_bytes()).hexdigest()
            except Exception:
                attempt_prefill_hash = None

        try:
            response_text, attempt_usage = await call_codex_cli(
                work_dir=work_dir,
                prompt_messages=prompt_messages,
                metadata=call_metadata,
                system_prompt=SYSTEM_PROMPT,
                model=model,
                reasoning_level=reasoning_level,
                max_tokens=max_tokens,
                temperature=temperature,
                trace_file=trace_file,
                refinement_context=current_refinement,
                skill_context=coding_skill_context,
                phase_name="coding",
            )
            usage["input_tokens"] += attempt_usage.get("input_tokens", 0)
            usage["output_tokens"] += attempt_usage.get("output_tokens", 0)
        except CodexCliError as e:
            logger.warning("[%s] Round %s attempt %s - Coding LLM infrastructure failure: %s", task_name, round_num + 1, retry_idx + 1, e)
            usage["input_tokens"] += e.usage.get("input_tokens", 0)
            usage["output_tokens"] += e.usage.get("output_tokens", 0)
            if e.failure_type == "llm_cli_timeout" and solution_file.exists():
                salvaged_code = solution_file.read_text(encoding="utf-8", errors="replace")
                if len(salvaged_code.strip()) > 100:
                    try:
                        ast.parse(salvaged_code)
                    except SyntaxError as parse_error:
                        logger.warning(
                            "[%s] Round %s attempt %s - timed out with unparsable solution.py: %s",
                            task_name,
                            round_num + 1,
                            retry_idx + 1,
                            parse_error,
                        )
                    else:
                        logger.warning(
                            "[%s] Round %s attempt %s - Codex timed out, but solution.py was written and parsed; continuing to validation",
                            task_name,
                            round_num + 1,
                            retry_idx + 1,
                        )
                        response_text = "[CODING TIMEOUT: salvaged written solution.py]"
                        usage["salvaged_solution_after_timeout"] = True
                        break
            return {
                "round": round_num,
                "task_name": task_name,
                "branch": get_current_branch(output_dir),
                "branch_decision": branch_decision,
                "search_operator": search_operator_to_dict(search_operator),
                "raw_text": response_text,
                "early_eda": early_eda,
                "planning": planning_text,
                "planning_raw_text": planning_raw_text,
                "skill_route": {
                    "branch": skill_route.branch,
                    "reason": skill_route.reason,
                    "sources": skill_route.sources,
                },
                "status": e.failure_type,
                "llm_failure": {
                    "phase": "coding",
                    "failure_type": e.failure_type,
                    "return_code": e.return_code,
                    "stderr_tail": e.stderr[-1000:],
                },
                "round_wall_time": time.time() - round_start_time,
                **usage,
            }
        except Exception as e:
            logger.error("[%s] Round %s attempt %s - CLI call failed: %s", task_name, round_num + 1, retry_idx + 1, e)
            if retry_idx == max_no_solution_retries:
                return {
                    "round": round_num,
                    "task_name": task_name,
                    "branch": get_current_branch(output_dir),
                    "branch_decision": branch_decision,
                    "search_operator": search_operator_to_dict(search_operator),
                    "error": str(e),
                    "status": "agent_error",
                    "round_wall_time": time.time() - round_start_time,
                    **usage,
                }
            continue

        if solution_file.exists():
            existing_code = solution_file.read_text(encoding="utf-8", errors="replace")
            if len(existing_code.strip()) > 100:
                existing_hash = hashlib.sha256(existing_code.encode("utf-8", errors="replace")).hexdigest()
                if attempt_prefill_hash and existing_hash == attempt_prefill_hash:
                    logger.warning(
                        "[%s] Round %s attempt %s - prefilled solution.py was not modified",
                        task_name,
                        round_num + 1,
                        retry_idx + 1,
                    )
                    code = extract_code(response_text)
                    if code and len(code.strip()) > 100:
                        extracted_hash = hashlib.sha256(code.encode("utf-8", errors="replace")).hexdigest()
                        if extracted_hash != attempt_prefill_hash:
                            solution_file.write_text(code, encoding="utf-8")
                            logger.info(
                                "[%s] Round %s - Replaced unchanged prefill with %s extracted chars",
                                task_name,
                                round_num + 1,
                                len(code),
                            )
                            break
                    if retry_idx < max_no_solution_retries:
                        logger.warning(
                            "[%s] Round %s - unchanged prefilled solution on attempt %s, retrying (%s/%s)",
                            task_name,
                            round_num + 1,
                            retry_idx + 1,
                            retry_idx + 1,
                            max_no_solution_retries,
                        )
                        continue
                    solution_file.unlink(missing_ok=True)
                else:
                    break
            solution_file.unlink(missing_ok=True)

        logger.info(
            "[%s] Round %s attempt %s - solution.py not found, extracting from response",
            task_name,
            round_num + 1,
            retry_idx + 1,
        )
        code = extract_code(response_text)
        if code and len(code.strip()) > 100:
            solution_file.write_text(code, encoding="utf-8")
            logger.info("[%s] Round %s - Extracted %s chars from response", task_name, round_num + 1, len(code))
            break

        if retry_idx < max_no_solution_retries:
            logger.warning(
                "[%s] Round %s - No solution on attempt %s, retrying (%s/%s)",
                task_name,
                round_num + 1,
                retry_idx + 1,
                retry_idx + 1,
                max_no_solution_retries,
            )
            continue

        logger.error("[%s] Round %s - No code after %s attempts", task_name, round_num + 1, max_no_solution_retries + 1)
        return {
            "round": round_num,
            "task_name": task_name,
            "branch": get_current_branch(output_dir),
            "branch_decision": branch_decision,
            "search_operator": search_operator_to_dict(search_operator),
            "raw_text": response_text,
            "early_eda": early_eda,
            "planning": planning_text,
            "planning_raw_text": planning_raw_text,
            "skill_route": {
                "branch": skill_route.branch,
                "reason": skill_route.reason,
                "sources": skill_route.sources,
            },
            "error": f"solution.py not created after {max_no_solution_retries + 1} attempts",
            "status": "no_solution",
            "round_wall_time": time.time() - round_start_time,
            **usage,
        }

    logger.info(
        "[%s] Round %s - Using framework external validation timeout=%ss",
        task_name,
        round_num + 1,
        branch_decision["validation_timeout_seconds"],
    )

    code = solution_file.read_text(encoding="utf-8")
    solution_contract = inspect_solution_contract(
        code,
        search_operator=search_operator,
        search_state=branch_decision.get("search_state"),
        strict_score_first_required=bool((branch_decision.get("runtime_control") or {}).get("strict_score_first_required")),
    )
    static_gate_repair_attempts_used = 0
    while (
        solution_contract["status"] == "block"
        and static_gate_repair_attempts_used < V4_MAX_STATIC_GATE_REPAIR_ATTEMPTS
    ):
        repair_attempt = static_gate_repair_attempts_used + 1
        blockers_before = list(solution_contract.get("blockers") or [])
        logger.warning(
            "[%s] Round %s - static gate repair attempt %s/%s for blockers: %s",
            task_name,
            round_num + 1,
            repair_attempt,
            V4_MAX_STATIC_GATE_REPAIR_ATTEMPTS,
            blockers_before,
        )
        trace_suffix = "" if repair_attempt == 1 else f"_retry_{repair_attempt - 1}"
        repair_refinement_context = refinement_context
        if repair_attempt > 1:
            repair_refinement_context = "\n\n".join(filter(None, [
                refinement_context,
                (
                    "[STATIC GATE REPAIR RETRY]\n"
                    "The previous same-round repair did not clear every hard blocker. "
                    "Re-read the current root solution.py and the newly computed contract below; "
                    "fix only the blockers that remain."
                ),
            ]))
        static_gate_repair_attempts_used = repair_attempt
        try:
            repaired_code, gate_response, gate_usage = await repair_static_gate_failure(
                work_dir=work_dir,
                prompt_messages=prompt_messages,
                metadata=call_metadata,
                model=model,
                reasoning_level=reasoning_level,
                max_tokens=max_tokens,
                temperature=temperature,
                trace_file=(
                    output_dir
                    / "traces"
                    / f"round_{round_num}_static_gate_repair{trace_suffix}_trace.json"
                ),
                refinement_context=repair_refinement_context,
                skill_context=coding_skill_context,
                code=code,
                solution_contract=solution_contract,
            )
            usage["input_tokens"] += gate_usage.get("input_tokens", 0)
            usage["output_tokens"] += gate_usage.get("output_tokens", 0)
            code = repaired_code
            solution_file.write_text(code, encoding="utf-8")
            response_text += (
                f"\n\n[STATIC GATE REPAIR RESPONSE {repair_attempt}/"
                f"{V4_MAX_STATIC_GATE_REPAIR_ATTEMPTS}]\n{gate_response}"
            )
            solution_contract = inspect_solution_contract(
                code,
                search_operator=search_operator,
                search_state=branch_decision.get("search_state"),
                strict_score_first_required=bool((branch_decision.get("runtime_control") or {}).get("strict_score_first_required")),
            )
        except CodexCliError as e:
            logger.warning("[%s] Round %s - Static gate repair LLM infrastructure failure: %s", task_name, round_num + 1, e)
            usage["input_tokens"] += e.usage.get("input_tokens", 0)
            usage["output_tokens"] += e.usage.get("output_tokens", 0)
            solution_contract.setdefault("gate_policy", {}).update({
                "repair_attempt_limit": V4_MAX_STATIC_GATE_REPAIR_ATTEMPTS,
                "repair_attempts_used": static_gate_repair_attempts_used,
            })
            return {
                "round": round_num,
                "task_name": task_name,
                "branch": get_current_branch(output_dir),
                "branch_decision": branch_decision,
                "search_operator": search_operator_to_dict(search_operator),
                "raw_text": response_text,
                "early_eda": early_eda,
                "planning": planning_text,
                "planning_raw_text": planning_raw_text,
                "skill_route": {
                    "branch": skill_route.branch,
                    "reason": skill_route.reason,
                    "sources": skill_route.sources,
                },
                "code": code,
                "code_features": inspect_code_memory_features(code),
                "solution_contract": solution_contract,
                "status": e.failure_type,
                "llm_failure": {
                    "phase": "static_gate_repair",
                    "failure_type": e.failure_type,
                    "return_code": e.return_code,
                    "stderr_tail": e.stderr[-1000:],
                },
                "round_wall_time": time.time() - round_start_time,
                **usage,
            }
        except Exception as e:
            logger.warning(
                "[%s] Round %s - static gate repair attempt %s/%s failed: %s",
                task_name,
                round_num + 1,
                repair_attempt,
                V4_MAX_STATIC_GATE_REPAIR_ATTEMPTS,
                e,
            )

    if static_gate_repair_attempts_used:
        solution_contract.setdefault("gate_policy", {}).update({
            "repair_attempt_limit": V4_MAX_STATIC_GATE_REPAIR_ATTEMPTS,
            "repair_attempts_used": static_gate_repair_attempts_used,
        })

    if solution_contract["status"] == "block":
        failure_taxonomy = {
            "primary": "static_gate_blocked",
            "all": ["static_gate_blocked", *list(solution_contract.get("blockers") or [])],
            "evidence": "static_gate_contract",
            "source": "static_gate",
            "debug_instruction": "Repair the generated solution.py so the static gate passes before sandbox validation.",
        }
        round_summary = build_local_round_summary(
            search_operator=search_operator,
            validation_status="static_gate_blocked",
            validation_score=None,
            failure_taxonomy=failure_taxonomy,
            solution_contract=solution_contract,
            branch_decision=branch_decision,
            task_dir=output_dir,
            validation_feedback="",
        )
        round_summary = normalize_round_summary_method_family(round_summary, search_operator, output_dir)
        effective_lineage = build_effective_lineage(
            round_num=round_num,
            commit_hash=None,
            branch=get_current_branch(output_dir),
            branch_decision=branch_decision,
            search_operator=search_operator,
            round_summary=round_summary,
        )
        failure_dir = output_dir / "failed_rounds" / f"round_{round_num:03d}_static_gate_blocked"
        failure_dir.mkdir(parents=True, exist_ok=True)
        failure_feedback = (
            "Static gate blocked validation before sandbox execution.\n\n"
            f"Blockers: {solution_contract.get('blockers')}\n\n"
            "[STATIC GATE CONTRACT]\n"
            + json.dumps(solution_contract, indent=2, ensure_ascii=False)
        )
        (failure_dir / "solution.py").write_text(code, encoding="utf-8")
        (failure_dir / "validation_feedback.txt").write_text(failure_feedback, encoding="utf-8")
        (failure_dir / "round_summary.json").write_text(
            json.dumps(round_summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        for aux_name in ("context_readiness.md", POST_CODE_MEMORY_SUMMARY_FILENAME):
            aux_path = output_dir / aux_name
            if aux_path.exists() and not aux_path.is_dir():
                shutil.copyfile(aux_path, failure_dir / aux_name)
        result = {
            "round": round_num,
            "task_name": task_name,
            "branch": get_current_branch(output_dir),
            "branch_decision": branch_decision,
            "search_operator": search_operator_to_dict(search_operator),
            "raw_text": response_text,
            "early_eda": early_eda,
            "planning": planning_text,
            "planning_raw_text": planning_raw_text,
            "skill_route": {
                "branch": skill_route.branch,
                "reason": skill_route.reason,
                "sources": skill_route.sources,
            },
            "code": code,
            "code_features": inspect_code_memory_features(code),
            "solution_contract": solution_contract,
            "round_summary": round_summary,
            "effective_lineage": effective_lineage,
            "effective_operator": effective_lineage.get("effective_operator"),
            "effective_method_family": effective_lineage.get("effective_method_family"),
            "effective_search_intent": effective_lineage.get("effective_search_intent"),
            "effective_branch": effective_lineage.get("effective_branch"),
            "code_path": str((failure_dir / "solution.py").relative_to(output_dir)),
            "validation_feedback_path": str((failure_dir / "validation_feedback.txt").resolve()),
            "failure_artifact_dir": str(failure_dir.resolve()),
            "failure_primary": "static_gate_blocked",
            "error": f"static gate blocked validation: {solution_contract['blockers']}",
            "status": "static_gate_blocked",
            "round_wall_time": time.time() - round_start_time,
            **usage,
        }
        try:
            result["memory_card_update"] = write_round_memory_artifacts(
                task_dir=output_dir,
                metadata=metadata,
                result=result,
                higher_is_better=higher_is_better,
            )
        except Exception as e:
            logger.warning("[%s] Round %s - Static gate memory card write failed: %s", task_name, round_num + 1, e)
        (failure_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result
    if solution_contract["status"] != "pass":
        logger.warning(
            "[%s] Round %s - solution.py contract warnings: %s",
            task_name,
            round_num + 1,
            solution_contract["missing"],
        )

    code_fingerprint = solution_fingerprint(code)
    code_features = inspect_code_memory_features(code)
    duplicate_solution = find_duplicate_solution(output_dir, code)
    if duplicate_solution:
        feedback = (
            "Skipped sandbox validation: generated solution.py is identical to prior "
            f"commit {duplicate_solution.get('commit')} ({duplicate_solution.get('code_path')}). "
            "This round produced no new experimental information; choose a distinct operator or make a material code change."
        )
        duplicate_dir = output_dir / "duplicates" / f"round_{round_num}"
        duplicate_dir.mkdir(parents=True, exist_ok=True)
        (duplicate_dir / "solution.py").write_text(code, encoding="utf-8")
        (duplicate_dir / "validation_feedback.txt").write_text(feedback, encoding="utf-8")
        for aux_name in ("context_readiness.md", POST_CODE_MEMORY_SUMMARY_FILENAME):
            aux_path = output_dir / aux_name
            if aux_path.exists() and not aux_path.is_dir():
                shutil.copyfile(aux_path, duplicate_dir / aux_name)
        (duplicate_dir / "duplicate_info.json").write_text(
            json.dumps(duplicate_solution, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        duplicate_validation = {
            "phase": "validation",
            "timeout": 0,
            "status_code": None,
            "status": DUPLICATE_SOLUTION_STATUS,
            "score": None,
            "raw_score": None,
            "reward": None,
            "quality": {
                "kind": DUPLICATE_SOLUTION_STATUS,
                "submit_eligible": False,
                "reason": "identical_solution_fingerprint",
            },
            "failure_taxonomy": {
                "primary": DUPLICATE_SOLUTION_STATUS,
                "all": [DUPLICATE_SOLUTION_STATUS],
                "evidence": "identical_solution_fingerprint",
                "source": "duplicate_solution_gate",
                "debug_instruction": "Do not debug this as a runtime failure; route the next round to a distinct operator or material patch.",
            },
            "job_id": None,
            "queue_time": 0.0,
            "run_time": 0.0,
            "raw_run_log": "",
            "clear_run_log": "",
            "feedback": feedback,
        }
        duplicate_summary = build_local_round_summary(
            search_operator=search_operator,
            validation_status=DUPLICATE_SOLUTION_STATUS,
            validation_score=None,
            failure_taxonomy=duplicate_validation["failure_taxonomy"],
            solution_contract=solution_contract,
            branch_decision=branch_decision,
            task_dir=output_dir,
            validation_feedback=feedback,
        )
        duplicate_summary = normalize_round_summary_method_family(duplicate_summary, search_operator, output_dir)
        duplicate_lineage = build_effective_lineage(
            round_num=round_num,
            commit_hash=None,
            branch=get_current_branch(output_dir),
            branch_decision=branch_decision,
            search_operator=search_operator,
            round_summary=duplicate_summary,
        )
        if solution_file.exists():
            solution_file.unlink()
        duplicate_result = {
            "round": round_num,
            "task_name": task_name,
            "branch": get_current_branch(output_dir),
            "branch_decision": branch_decision,
            "search_operator": search_operator_to_dict(search_operator),
            "raw_text": response_text,
            "early_eda": early_eda,
            "planning": planning_text,
            "planning_raw_text": planning_raw_text,
            "skill_route": {
                "branch": skill_route.branch,
                "reason": skill_route.reason,
                "sources": skill_route.sources,
            },
            "code": code,
            "code_path": str((duplicate_dir / "solution.py").relative_to(output_dir)),
            "validation_feedback_path": str((duplicate_dir / "validation_feedback.txt").resolve()),
            "failure_artifact_dir": str(duplicate_dir.resolve()),
            "code_fingerprint": code_fingerprint,
            "code_features": code_features,
            "duplicate_solution": duplicate_solution,
            "solution_contract": solution_contract,
            "validation": duplicate_validation,
            "round_summary": duplicate_summary,
            "effective_lineage": duplicate_lineage,
            "effective_operator": duplicate_lineage.get("effective_operator"),
            "effective_method_family": duplicate_lineage.get("effective_method_family"),
            "effective_search_intent": duplicate_lineage.get("effective_search_intent"),
            "effective_branch": duplicate_lineage.get("effective_branch"),
            "summary_usage": {"input_tokens": 0, "output_tokens": 0, "source": "duplicate_solution_gate"},
            "status": DUPLICATE_SOLUTION_STATUS,
            "round_wall_time": time.time() - round_start_time,
            **usage,
        }
        try:
            duplicate_result["memory_card_update"] = write_round_memory_artifacts(
                task_dir=output_dir,
                metadata=metadata,
                result=duplicate_result,
                higher_is_better=higher_is_better,
            )
        except Exception as e:
            logger.warning("[%s] Round %s - Duplicate memory card write failed: %s", task_name, round_num + 1, e)
        (duplicate_dir / "result.json").write_text(json.dumps(duplicate_result, indent=2, ensure_ascii=False), encoding="utf-8")
        return duplicate_result

    search_state = str(branch_decision.get("search_state") or "")
    validation_timeout = int(branch_decision["validation_timeout_seconds"])
    logger.info(
        "[%s] Round %s - Running validation resource_type=%s timeout=%ss state=%s operator=%s",
        task_name,
        round_num + 1,
        resource_type,
        validation_timeout,
        search_state or "unknown",
        search_operator.name,
    )
    val_ctx = EvalContext(phase="validation", data_dir=val_data_dir)
    val_status_code, val_payload = await get_sandbox_result(
        client=sandbox_client,
        code_str=code,
        data_dir=val_ctx.data_dir,
        resource_type=resource_type,
        job_timeout=validation_timeout,
        wait_timeout=validation_timeout + 600,
        poll_interval=5,
    )

    val_job_id = val_payload.get("job_id")
    val_result_payload = val_payload.get("result") or {}
    val_status = str(val_result_payload.get("result") or "unknown")
    val_score_value = val_result_payload.get("score")
    raw_val_score = float(val_score_value) if (val_status_code == 200 and val_score_value is not None) else None

    val_queue_time = None
    val_run_time = None
    created_at = val_payload.get("created_at")
    started_at = val_payload.get("started_at")
    completed_at = val_payload.get("completed_at")
    if started_at and completed_at:
        started_ts = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        completed_ts = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        val_run_time = (completed_ts - started_ts).total_seconds()
        if created_at:
            created_ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            val_queue_time = (started_ts - created_ts).total_seconds()

    val_run_log = val_result_payload.get("run_log")
    val_clear_log = get_clear_log(val_run_log)
    val_feedback = format_sandbox_feedback(val_status_code, val_payload)
    validation_diagnostic_feedback = "\n\n".join(part for part in [val_feedback, val_clear_log or ""] if part)
    quality_feedback = "\n\n".join(part for part in [validation_diagnostic_feedback, val_run_log or ""] if part)
    quality = detect_validation_quality_issue(
        code,
        val_status,
        raw_val_score,
        quality_feedback,
        search_operator,
        strict_score_first_required=bool((branch_decision.get("runtime_control") or {}).get("strict_score_first_required")),
    )
    val_score = raw_val_score
    if raw_val_score is not None and not bool(quality.get("submit_eligible", True)):
        logger.warning(
            "[%s] Round %s - scored validation downgraded: %s (raw_score=%s)",
            task_name,
            round_num + 1,
            quality.get("kind"),
            raw_val_score,
        )
        val_status = str(quality.get("kind") or "quality_gate_failed")
        val_score = None
    val_reward = score2reward(val_score, metadata, mode="power_sigmoid") if val_score is not None else 0.0
    failure_taxonomy = classify_validation_failure(val_status, quality_feedback) if val_score is None else {
        "primary": "none",
        "all": [],
        "evidence": "validation_score",
        "source": "validation_result",
        "debug_instruction": "Validation produced a score; debug taxonomy is not active.",
    }
    quality_kind = str(quality.get("kind") or "")
    quality_override_failures = {
        "constant_prediction_success",
        "uninformative_fallback",
        "fallback_dominated_success",
        "route_failed_with_fallback_score",
        "success_with_fallback_warning",
        "quality_gate_failed",
    }
    if (
        val_score is None
        and not bool(quality.get("submit_eligible", True))
        and quality_kind in quality_override_failures
    ):
        failure_taxonomy["primary"] = quality_kind
        all_failures = list(failure_taxonomy.get("all") or [])
        if quality_kind not in all_failures:
            all_failures.insert(0, quality_kind)
        failure_taxonomy["all"] = all_failures
        failure_taxonomy["evidence"] = str(quality.get("reason") or quality_kind)
        failure_taxonomy["source"] = "validation_quality_gate"
        failure_taxonomy["debug_instruction"] = (
            "Do not preserve an uninformative emergency fallback as a successful model. "
            "Fix the data, label, target, submission-unit, or training parser so the round trains a meaningful model."
        )
    experiment_signature = validation_experiment_signature(val_feedback, val_score, search_operator)

    round_wall_time = time.time() - round_start_time
    current_branch = get_current_branch(output_dir)
    # Keep the per-round routing snapshot frozen. current_branch_decision.json
    # can be overwritten by later scheduling or external inspection while this
    # sandbox job is still running; result lineage must describe the operator
    # that actually generated and validated this solution.py.
    result_branch_decision = dict(branch_decision)
    result = {
        "round": round_num,
        "task_name": task_name,
        "branch": current_branch,
        "branch_decision": result_branch_decision,
        "search_operator": search_operator_to_dict(search_operator),
        "early_eda": early_eda,
        "planning": planning_text,
        "planning_raw_text": planning_raw_text,
        "skill_route": {
            "branch": skill_route.branch,
            "reason": skill_route.reason,
            "sources": skill_route.sources,
        },
        "raw_text": response_text,
        "code": code,
        "code_fingerprint": code_fingerprint,
        "code_features": code_features,
        "solution_contract": solution_contract,
        **usage,
        "round_wall_time": round_wall_time,
        "validation": {
            "phase": "validation",
            "timeout": validation_timeout,
            "status_code": val_status_code,
            "status": val_status,
            "score": val_score,
            "raw_score": raw_val_score,
            "reward": val_reward,
            "quality": quality,
            "failure_taxonomy": failure_taxonomy,
            "job_id": val_job_id,
            "queue_time": val_queue_time,
            "run_time": val_run_time,
            "raw_run_log": val_run_log,
            "clear_run_log": val_clear_log,
            "feedback": val_feedback,
            "experiment_signature": experiment_signature,
        },
    }

    summary_trace_file = output_dir / "traces" / f"round_{round_num}_summary_trace.json"
    if V33_SUPPORT_CALLS_DEFAULT:
        try:
            round_summary, summary_usage = await call_codex_round_summary(
                work_dir=output_dir / "traces",
                metadata=metadata,
                round_num=round_num,
                solution_code=code,
                validation_feedback=val_feedback,
                validation_status=val_status,
                validation_score=val_score,
                model=model,
                reasoning_level=reasoning_level,
                trace_file=summary_trace_file,
            )
            usage["input_tokens"] += summary_usage.get("input_tokens", 0)
            usage["output_tokens"] += summary_usage.get("output_tokens", 0)
            result["summary_usage"] = summary_usage
        except Exception as e:
            logger.warning("[%s] Round %s - Summary call failed: %s", task_name, round_num + 1, e)
            round_summary = build_local_round_summary(
                search_operator=search_operator,
                validation_status=val_status,
                validation_score=val_score,
                failure_taxonomy=failure_taxonomy,
                solution_contract=solution_contract,
                branch_decision=result_branch_decision,
                task_dir=output_dir,
                validation_feedback=validation_diagnostic_feedback,
            )
    else:
        round_summary = build_local_round_summary(
            search_operator=search_operator,
            validation_status=val_status,
            validation_score=val_score,
            failure_taxonomy=failure_taxonomy,
            solution_contract=solution_contract,
            branch_decision=result_branch_decision,
            task_dir=output_dir,
            validation_feedback=validation_diagnostic_feedback,
        )
        result["summary_usage"] = {"input_tokens": 0, "output_tokens": 0, "source": "local_structured"}

    round_summary = normalize_round_summary_method_family(round_summary, search_operator, output_dir)
    result["round_summary"] = round_summary
    result["input_tokens"] = usage["input_tokens"]
    result["output_tokens"] = usage["output_tokens"]

    commit_hash = create_commit_hash(round_num, datetime.now().isoformat())
    result["commit_hash"] = commit_hash
    effective_lineage = build_effective_lineage(
        round_num=round_num,
        commit_hash=commit_hash,
        branch=current_branch,
        branch_decision=result_branch_decision,
        search_operator=search_operator,
        round_summary=round_summary,
    )
    result["effective_lineage"] = effective_lineage
    result["effective_operator"] = effective_lineage.get("effective_operator")
    result["effective_method_family"] = effective_lineage.get("effective_method_family")
    result["effective_search_intent"] = effective_lineage.get("effective_search_intent")
    result["effective_branch"] = effective_lineage.get("effective_branch")
    save_commit(output_dir, commit_hash, planning_text, code, val_feedback, result, round_summary)
    try:
        result["memory_card_update"] = write_round_memory_artifacts(
            task_dir=output_dir,
            metadata=metadata,
            result=result,
            higher_is_better=higher_is_better,
        )
        commit_dir = output_dir / "commits" / commit_hash
        if commit_dir.exists():
            (commit_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("[%s] Round %s - Memory card write failed: %s", task_name, round_num + 1, e)

    if solution_file.exists():
        solution_file.unlink()
    context_readiness_file = output_dir / "context_readiness.md"
    if context_readiness_file.exists():
        context_readiness_file.unlink()
    post_code_memory_summary_file = output_dir / POST_CODE_MEMORY_SUMMARY_FILENAME
    if post_code_memory_summary_file.exists():
        post_code_memory_summary_file.unlink()

    if val_score is not None:
        commit_msg = f"Round {round_num + 1}: {val_status} score={val_score:.4f}"
    else:
        commit_msg = f"Round {round_num + 1}: {val_status}"

    commit_status = "success" if val_score is not None else val_status
    update_commit_log(
        output_dir,
        commit_hash,
        current_branch,
        commit_msg,
        val_score,
        round_wall_time,
        commit_status,
        round_summary,
        search_operator=search_operator,
    )
    update_branch_ref(
        task_dir=output_dir,
        branch=current_branch,
        commit_hash=commit_hash,
        score=val_score,
        status=commit_status,
        wall_time=round_wall_time,
        round_num=round_num,
        higher_is_better=higher_is_better,
    )

    if val_score is not None:
        is_best = best_score_so_far is None or (
            (higher_is_better and val_score > best_score_so_far) or
            (not higher_is_better and val_score < best_score_so_far)
        )
        if is_best:
            create_tag(
                output_dir,
                "best_local_cv",
                commit_hash,
                f"Best validation score so far: {val_score:.4f}",
                val_score,
                current_branch,
            )
            logger.info("[%s] Round %s - New best, tagged as best_local_cv", task_name, round_num + 1)

        branch_tag = f"best_{current_branch}"
        branch_summary = load_branch_summary(output_dir).get(current_branch, {})
        if branch_summary.get("head") == commit_hash and branch_summary.get("best_score") == val_score:
            create_tag(
                output_dir,
                branch_tag,
                commit_hash,
                f"Best score on branch {current_branch}: {val_score:.4f}",
                val_score,
                current_branch,
            )

    if val_score is not None:
        logger.info("[%s] Round %s - val_score=%.6f, commit=%s", task_name, round_num + 1, val_score, commit_hash)
    else:
        logger.info("[%s] Round %s - Validation failed, commit=%s", task_name, round_num + 1, commit_hash)

    try:
        update_best_validation_vault(output_dir, result, higher_is_better=higher_is_better)
        graph_node = record_graph_node(output_dir, result, higher_is_better=higher_is_better)
        result["graph_node"] = graph_node
        commit_dir = output_dir / "commits" / commit_hash
        if commit_dir.exists():
            (commit_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("[%s] Round %s - Graph node update failed: %s", task_name, round_num + 1, e)

    try:
        memory_result = write_local_memory_after_round(
            task_dir=output_dir,
            metadata=metadata,
            round_num=round_num,
            commit_hash=commit_hash,
            branch=current_branch,
            validation_status=val_status,
            validation_score=val_score,
            round_summary=round_summary,
            higher_is_better=higher_is_better,
            result=result,
        )
        result["memory_update"] = memory_result
        memory_usage = memory_result.get("usage", {}) if isinstance(memory_result, dict) else {}
        result["input_tokens"] += memory_usage.get("input_tokens", 0)
        result["output_tokens"] += memory_usage.get("output_tokens", 0)
        commit_dir = output_dir / "commits" / commit_hash
        if commit_dir.exists():
            (commit_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("[%s] Round %s - Memory update failed: %s", task_name, round_num + 1, e)

    logger.info("[%s] Round %s wall time: %.2fs", task_name, round_num + 1, round_wall_time)
    return result


def choose_validation_best_submit_round(
    task_dir: Path,
    all_rounds: list[dict[str, Any]],
    higher_is_better: bool,
) -> dict[str, Any] | None:
    """Select the final submit candidate strictly by raw validation score."""
    valid_rows = [row for row in all_rounds if is_submission_eligible_round(row)]
    if not valid_rows:
        return None
    best = max(valid_rows, key=lambda row: round_sort_key(row, higher_is_better))
    update_best_validation_vault(task_dir, best, higher_is_better=higher_is_better)
    return best


async def submit_best_round(
    sandbox_client: httpx.AsyncClient,
    best_round: dict[str, Any],
    task: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Run submit phase for the best validation round."""
    metadata = task["metadata"]
    task_name = metadata["task_name"]
    resource_type = metadata.get("cpu_gpu", "cpu")
    resource_type = "cpu" if str(resource_type).lower() == "cpu" else "gpu"
    val_data_dir = metadata.get("data_dir", "")

    round_num = best_round["round"]
    code = best_round["code"]
    val_score = best_round["validation"]["score"]
    commit_hash = best_round.get("commit_hash", "unknown")
    submit_branch = str(best_round.get("branch") or get_current_branch(output_dir))

    logger.info(
        "[%s] Submitting best round %s (val_score=%.6f, commit=%s, timeout=%ss)",
        task_name,
        round_num + 1,
        val_score,
        commit_hash,
        V4_SUBMIT_TIMEOUT_SECONDS,
    )

    submit_data_dir = resolve_submit_data_dir(val_data_dir)
    submit_ctx = EvalContext(phase="submit", data_dir=submit_data_dir)
    submit_status_code, submit_payload = await get_sandbox_result(
        client=sandbox_client,
        code_str=code,
        data_dir=submit_ctx.data_dir,
        resource_type=resource_type,
        job_timeout=V4_SUBMIT_TIMEOUT_SECONDS,
        wait_timeout=V4_SUBMIT_TIMEOUT_SECONDS,
        poll_interval=5,
    )

    submit_job_id = submit_payload.get("job_id")
    submit_result_payload = submit_payload.get("result") or {}
    submit_status = str(submit_result_payload.get("result") or "unknown")
    submit_score_value = submit_result_payload.get("score")
    submit_score = float(submit_score_value) if (submit_status_code == 200 and submit_score_value is not None) else None
    submit_reward = score2reward(submit_score, metadata, mode="power_sigmoid") if submit_score is not None else 0.0

    submit_queue_time = None
    submit_run_time = None
    if submit_status_code == 200:
        created_at = submit_payload.get("created_at")
        started_at = submit_payload.get("started_at")
        completed_at = submit_payload.get("completed_at")
        if started_at and completed_at:
            started_ts = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            completed_ts = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            submit_run_time = (completed_ts - started_ts).total_seconds()
            if created_at:
                created_ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                submit_queue_time = (started_ts - created_ts).total_seconds()

    submit_run_log = submit_result_payload.get("run_log")
    submit_clear_log = get_clear_log(submit_run_log)
    submit_feedback = format_sandbox_feedback(submit_status_code, submit_payload)

    commit_dir = output_dir / "commits" / commit_hash
    if commit_dir.exists():
        (commit_dir / "submit_feedback.txt").write_text(submit_feedback, encoding="utf-8")

    best_round["submit"] = {
        "phase": "submit",
        "status_code": submit_status_code,
        "status": submit_status,
        "score": submit_score,
        "reward": submit_reward,
        "job_id": submit_job_id,
        "queue_time": submit_queue_time,
        "run_time": submit_run_time,
        "raw_run_log": submit_run_log,
        "clear_run_log": submit_clear_log,
        "feedback": submit_feedback,
    }

    if commit_dir.exists():
        (commit_dir / "result.json").write_text(json.dumps(best_round, indent=2), encoding="utf-8")

    if submit_score is not None:
        create_tag(
            output_dir,
            "submitted_score",
            commit_hash,
            f"Submitted score: {submit_score:.4f}",
            submit_score,
            submit_branch,
        )

    logger.info(
        "[%s] Submit complete (submit_score=%s)",
        task_name,
        submit_score,
    )
    return best_round


async def evaluate_single_task_multi_rounds(
    sandbox_client: httpx.AsyncClient,
    task: dict[str, Any],
    output_dir: Path,
    model: str,
    reasoning_level: str,
    max_tokens: int,
    temperature: float,
    num_rounds: int,
    time_budget: float = 43200.0,
    budget_mode: str = "sandbox",
    sandbox_run_budget: float | None = None,
    branch_strategy: str = "portfolio_first",
    warmup_branches: tuple[str, ...] = DEFAULT_WARMUP_BRANCHES,
    task_skills_dir: Path = DEFAULT_TASK_SKILLS_DIR,
    eda_skill_dir: Path = DEFAULT_EDA_SKILL_DIR,
    error_skill_file: Path = DEFAULT_ERROR_SKILL_FILE,
    local_eda_data_root: Path = DEFAULT_LOCAL_EDA_DATA_ROOT,
    eda_timeout_seconds: int = 900,
    early_eda_branches: tuple[str, ...] = DEFAULT_EARLY_EDA_BRANCHES,
) -> list[dict[str, Any]]:
    """Evaluate a single task across multiple rounds."""
    task_name = task["metadata"]["task_name"] if "metadata" in task else task["task_name"]
    sandbox_budget = resolve_sandbox_run_budget(time_budget, sandbox_run_budget)
    logger.info(
        "[%s] Starting multi-round evaluation (%s rounds, time_budget=%ss, budget_mode=%s, sandbox_run_budget=%ss)",
        task_name,
        num_rounds,
        time_budget,
        budget_mode,
        sandbox_budget,
    )

    init_git_structure(output_dir)
    if not (output_dir / "HEAD").exists():
        set_current_branch(output_dir, "draft")
    metadata = task["metadata"]
    higher_is_better = metadata.get("higher_is_better", True)

    all_rounds: list[dict[str, Any]] = []
    total_time = 0.0
    total_sandbox_run_time = 0.0
    task_start_wall = time.time()
    best_score_so_far = None
    summary_file = output_dir / "rounds_summary.json"

    for round_num in range(num_rounds):
        spent_wall_time = time.time() - task_start_wall
        budget_state = compute_budget_state(
            budget_mode=budget_mode,
            time_budget=time_budget,
            sandbox_run_budget=sandbox_budget,
            spent_wall_time=spent_wall_time,
            spent_sandbox_run_time=total_sandbox_run_time,
        )
        remaining_budget = float(budget_state["remaining_budget"])
        elapsed_fraction = float(budget_state["elapsed_fraction"])
        if remaining_budget <= V3_MIN_ROUND_TIMEOUT_SECONDS:
            logger.info(
                "[%s] %s budget exhausted (spent_wall=%.2fs, spent_sandbox=%.2fs, remaining=%.2fs), stopping at round %s",
                task_name,
                budget_mode,
                spent_wall_time,
                total_sandbox_run_time,
                remaining_budget,
                round_num,
            )
            break

        branch_decision = choose_branch_for_round(
            task_dir=output_dir,
            round_num=round_num,
            all_rounds=all_rounds,
            higher_is_better=higher_is_better,
            branch_strategy=branch_strategy,
            warmup_branches=warmup_branches,
            task_name=task_name,
            task_skills_dir=task_skills_dir,
            elapsed_fraction=elapsed_fraction,
            remaining_budget=remaining_budget,
            budget_state=budget_state,
        )
        set_current_branch(output_dir, branch_decision["branch"])
        logger.info(
            "[%s] Round %s branch=%s state=%s runtime_profile=%s reason=%s",
            task_name,
            round_num + 1,
            branch_decision["branch"],
            branch_decision.get("branch_state"),
            branch_decision.get("runtime_profile"),
            branch_decision.get("branch_reason") or branch_decision.get("reason"),
        )

        round_result = await evaluate_single_task_single_round(
            sandbox_client=sandbox_client,
            task=task,
            round_num=round_num,
            output_dir=output_dir,
            model=model,
            reasoning_level=reasoning_level,
            max_tokens=max_tokens,
            temperature=temperature,
            best_score_so_far=best_score_so_far,
            higher_is_better=higher_is_better,
            task_skills_dir=task_skills_dir,
            eda_skill_dir=eda_skill_dir,
            error_skill_file=error_skill_file,
            local_eda_data_root=local_eda_data_root,
            eda_timeout_seconds=eda_timeout_seconds,
            early_eda_branches=early_eda_branches,
        )
        if "branch" not in round_result:
            round_result["branch"] = branch_decision["branch"]
            round_result["branch_decision"] = branch_decision
        if "search_operator" not in round_result:
            round_result["search_operator"] = branch_decision.get("search_operator")
        all_rounds.append(round_result)

        if "commit_hash" not in round_result:
            try:
                if not round_result.get("memory_card_path"):
                    round_result["memory_card_update"] = write_round_memory_artifacts(
                        task_dir=output_dir,
                        metadata=metadata,
                        result=round_result,
                        higher_is_better=higher_is_better,
                    )
            except Exception as e:
                logger.warning("[%s] Round %s - No-commit memory card write failed: %s", task_name, round_num + 1, e)
            record_branch_attempt_without_commit(
                task_dir=output_dir,
                branch=branch_decision["branch"],
                status=str(round_result.get("status", "no_commit")),
                wall_time=float(round_result.get("round_wall_time", 0.0) or 0.0),
                round_num=round_num,
            )
            _append_jsonl(graph_dir(output_dir) / "events.jsonl", {
                "event": "round_without_commit",
                "round": round_num,
                "task_name": task_name,
                "branch": branch_decision["branch"],
                "operator": branch_decision.get("search_operator"),
                "status": round_result.get("status"),
                "error": round_result.get("error"),
                "wall_time": round_result.get("round_wall_time"),
                "timestamp": datetime.now().isoformat(),
            })
            try:
                memory_dir = output_dir / "memory_bank"
                memory_dir.mkdir(exist_ok=True)
                no_commit_record = {
                    "round": round_num,
                    "commit": None,
                    "branch": branch_decision["branch"],
                    "effective_branch": branch_decision["branch"],
                    "branch_state": branch_decision.get("branch_state"),
                    "branch_reason": branch_decision.get("branch_reason") or branch_decision.get("reason"),
                    "runtime_profile": branch_decision.get("runtime_profile"),
                    "parent_binding": branch_decision.get("parent_binding"),
                    "status": round_result.get("status", "no_commit"),
                    "score": None,
                    "operator": branch_decision.get("search_operator"),
                    "execution_operator": branch_decision.get("search_operator"),
                    "search_intent": branch_decision.get("search_intent"),
                    "effective_search_intent": branch_decision.get("search_intent"),
                    "search_state": branch_decision.get("search_state"),
                    "reason": branch_decision.get("reason"),
                    "method_family": (branch_decision.get("search_operator") or {}).get("family"),
                    "summary": "Round ended without a committed solution.py or sandbox validation.",
                    "reflection": round_result.get("error") or round_result.get("status"),
                    "failure_primary": round_result.get("status", "no_commit"),
                    "validation_diagnostics": {},
                    "memory_card_path": round_result.get("memory_card_path"),
                    "memory_diff_path": round_result.get("memory_diff_path"),
                    "wall_time": round_result.get("round_wall_time"),
                    "input_tokens": round_result.get("input_tokens"),
                    "output_tokens": round_result.get("output_tokens"),
                    "timestamp": datetime.now().isoformat(),
                }
                _append_jsonl(memory_dir / "rounds.jsonl", no_commit_record)
                _append_jsonl(memory_dir / "failure_ledger.jsonl", {
                    "round": round_num,
                    "commit": None,
                    "branch": branch_decision["branch"],
                    "status": round_result.get("status", "no_commit"),
                    "failure_primary": round_result.get("status", "no_commit"),
                    "failure_all": [round_result.get("status", "no_commit")],
                    "feedback_excerpt": round_result.get("error") or "",
                    "operator": branch_decision.get("search_operator"),
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                logger.debug("[%s] Round %s - failed to append no-commit memory record", task_name, round_num + 1, exc_info=True)

        val_score = round_result.get("validation", {}).get("score")
        if val_score is not None:
            if best_score_so_far is None:
                best_score_so_far = val_score
            elif higher_is_better and val_score > best_score_so_far:
                best_score_so_far = val_score
            elif not higher_is_better and val_score < best_score_so_far:
                best_score_so_far = val_score

        round_sandbox_time = float(round_result.get("validation", {}).get("run_time") or 0.0)
        total_sandbox_run_time += round_sandbox_time
        total_time = total_sandbox_run_time
        spent_wall_time = time.time() - task_start_wall
        budget_state = compute_budget_state(
            budget_mode=budget_mode,
            time_budget=time_budget,
            sandbox_run_budget=sandbox_budget,
            spent_wall_time=spent_wall_time,
            spent_sandbox_run_time=total_sandbox_run_time,
        )
        logger.info(
            "[%s] Round %s complete, round_wall=%.2fs, sandbox_run=%.2fs, spent_wall=%.2fs, spent_sandbox=%.2fs, active_remaining=%.2fs",
            task_name,
            round_num + 1,
            float(round_result.get("round_wall_time", 0.0) or 0.0),
            round_sandbox_time,
            spent_wall_time,
            total_sandbox_run_time,
            float(budget_state["remaining_budget"]),
        )

        summary_data = {
            "schema_version": "rounds_summary_compact_v1",
            "rounds_are_compact": True,
            "artifact_policy": "Full code, raw LLM text, raw sandbox logs, and long validation feedback are stored in commit/trace artifacts and referenced by path.",
            "rounds": compact_rounds_for_summary(all_rounds),
            "round_outcomes": summarize_round_outcomes(all_rounds),
            "total_time": total_time,
            "total_sandbox_run_time": total_sandbox_run_time,
            "spent_wall_time": spent_wall_time,
            "time_budget": time_budget,
            "budget_mode": budget_mode,
            "sandbox_run_budget": sandbox_budget,
            "budget_state": budget_state,
            "branch_strategy": branch_strategy,
            "branch_summary": load_branch_summary(output_dir),
            "graph_nodes": len(load_graph_nodes(output_dir)),
            "best_validation_vault": json.loads(best_vault_path(output_dir).read_text(encoding="utf-8"))
                if best_vault_path(output_dir).exists() else None,
        }
        write_rounds_summary_with_search_graph(
            summary_file=summary_file,
            summary_data=summary_data,
            task_dir=output_dir,
            higher_is_better=higher_is_better,
        )

        if should_stop_after_final_audit(all_rounds, budget_state):
            summary_data["stop_reason"] = "final_audit_completed"
            write_rounds_summary_with_search_graph(
                summary_file=summary_file,
                summary_data=summary_data,
                task_dir=output_dir,
                higher_is_better=higher_is_better,
            )
            logger.info(
                "[%s] Stopping after successful final audit; preserving validation-best submit path",
                task_name,
            )
            break

        if row_is_llm_infra_failure(round_result):
            if row_is_llm_transient_infra_failure(round_result):
                consecutive_transient = consecutive_llm_transient_infra_failures(all_rounds)
                active_remaining = float(budget_state.get("remaining_budget") or 0.0)
                if (
                    consecutive_transient < LLM_TRANSIENT_INFRA_STOP_THRESHOLD
                    and active_remaining >= V3_MIN_ROUND_TIMEOUT_SECONDS
                ):
                    logger.warning(
                        "[%s] Transient LLM infrastructure failure status=%s (%s/%s); continuing search",
                        task_name,
                        round_result.get("status"),
                        consecutive_transient,
                        LLM_TRANSIENT_INFRA_STOP_THRESHOLD,
                    )
                    continue
                summary_data["stop_reason"] = "repeated_llm_transient_infra"
                summary_data["consecutive_llm_transient_infra_failures"] = consecutive_transient
                write_rounds_summary_with_search_graph(
                    summary_file=summary_file,
                    summary_data=summary_data,
                    task_dir=output_dir,
                    higher_is_better=higher_is_better,
                )
                logger.warning(
                    "[%s] Stopping task after repeated transient LLM infrastructure failures status=%s count=%s",
                    task_name,
                    round_result.get("status"),
                    consecutive_transient,
                )
                break
            summary_data["stop_reason"] = "llm_infra_failure"
            write_rounds_summary_with_search_graph(
                summary_file=summary_file,
                summary_data=summary_data,
                task_dir=output_dir,
                higher_is_better=higher_is_better,
            )
            logger.warning(
                "[%s] Stopping task after LLM infrastructure failure status=%s; preserving validation-best submit path",
                task_name,
                round_result.get("status"),
            )
            break

    spent_wall_time = time.time() - task_start_wall
    budget_state = compute_budget_state(
        budget_mode=budget_mode,
        time_budget=time_budget,
        sandbox_run_budget=sandbox_budget,
        spent_wall_time=spent_wall_time,
        spent_sandbox_run_time=total_sandbox_run_time,
    )
    logger.info(
        "[%s] Completed %s rounds (sandbox_run_time=%.2fs, spent_wall=%.2fs)",
        task_name,
        len(all_rounds),
        total_sandbox_run_time,
        spent_wall_time,
    )

    best_round = choose_validation_best_submit_round(output_dir, all_rounds, higher_is_better=higher_is_better)
    if best_round:
        best_commit_hash = best_round.get("commit_hash")
        logger.info(
            "[%s] Validation-best submit round: %s (val_score=%.6f, commit=%s)",
            task_name,
            best_round["round"] + 1,
            best_round["validation"]["score"],
            best_commit_hash,
        )
        await submit_best_round(
            sandbox_client=sandbox_client,
            best_round=best_round,
            task=task,
            output_dir=output_dir,
        )
        summary_data = {
            "schema_version": "rounds_summary_compact_v1",
            "rounds_are_compact": True,
            "artifact_policy": "Full code, raw LLM text, raw sandbox logs, and long validation feedback are stored in commit/trace artifacts and referenced by path.",
            "rounds": compact_rounds_for_summary(all_rounds),
            "round_outcomes": summarize_round_outcomes(all_rounds),
            "total_time": total_time,
            "total_sandbox_run_time": total_sandbox_run_time,
            "spent_wall_time": spent_wall_time,
            "time_budget": time_budget,
            "budget_mode": budget_mode,
            "sandbox_run_budget": sandbox_budget,
            "budget_state": budget_state,
            "branch_strategy": branch_strategy,
            "branch_summary": load_branch_summary(output_dir),
            "graph_nodes": len(load_graph_nodes(output_dir)),
            "best_validation_vault": json.loads(best_vault_path(output_dir).read_text(encoding="utf-8"))
                if best_vault_path(output_dir).exists() else None,
            "best_round": best_round["round"],
            "best_commit": best_commit_hash,
            "selection_policy": SUBMIT_SELECTION_POLICY,
        }
        write_rounds_summary_with_search_graph(
            summary_file=summary_file,
            summary_data=summary_data,
            task_dir=output_dir,
            higher_is_better=higher_is_better,
        )
    else:
        logger.warning("[%s] No valid validation-best candidate, skipping submit", task_name)

    return all_rounds


async def evaluate_tasks_concurrent(
    sandbox_client: httpx.AsyncClient,
    tasks: list[dict[str, Any]],
    output_path: Path,
    model: str,
    reasoning_level: str,
    max_tokens: int,
    temperature: float,
    num_rounds: int,
    concurrency: int,
    time_budget: float = 43200.0,
    budget_mode: str = "sandbox",
    sandbox_run_budget: float | None = None,
    branch_strategy: str = "portfolio_first",
    warmup_branches: tuple[str, ...] = DEFAULT_WARMUP_BRANCHES,
    task_skills_dir: Path = DEFAULT_TASK_SKILLS_DIR,
    eda_skill_dir: Path = DEFAULT_EDA_SKILL_DIR,
    error_skill_file: Path = DEFAULT_ERROR_SKILL_FILE,
    local_eda_data_root: Path = DEFAULT_LOCAL_EDA_DATA_ROOT,
    eda_timeout_seconds: int = 900,
    early_eda_branches: tuple[str, ...] = DEFAULT_EARLY_EDA_BRANCHES,
) -> list[dict[str, Any]]:
    """Evaluate multiple tasks concurrently."""
    semaphore = asyncio.Semaphore(concurrency)

    async def evaluate_with_semaphore(task: dict[str, Any]) -> list[dict[str, Any]]:
        async with semaphore:
            task_name = task["metadata"]["task_name"] if "metadata" in task else task["task_name"]
            task_output_dir = output_path / task_name
            task_output_dir.mkdir(parents=True, exist_ok=True)
            return await evaluate_single_task_multi_rounds(
                sandbox_client=sandbox_client,
                task=task,
                output_dir=task_output_dir,
                model=model,
                reasoning_level=reasoning_level,
                max_tokens=max_tokens,
                temperature=temperature,
                num_rounds=num_rounds,
                time_budget=time_budget,
                budget_mode=budget_mode,
                sandbox_run_budget=sandbox_run_budget,
                branch_strategy=branch_strategy,
                warmup_branches=warmup_branches,
                task_skills_dir=task_skills_dir,
                eda_skill_dir=eda_skill_dir,
                error_skill_file=error_skill_file,
                local_eda_data_root=local_eda_data_root,
                eda_timeout_seconds=eda_timeout_seconds,
                early_eda_branches=early_eda_branches,
            )

    task_results = await asyncio.gather(
        *[evaluate_with_semaphore(task) for task in tasks],
        return_exceptions=True,
    )

    all_results = []
    for idx, result in enumerate(task_results):
        if isinstance(result, Exception):
            task_name = tasks[idx]["metadata"]["task_name"] if "metadata" in tasks[idx] else tasks[idx]["task_name"]
            logger.error("Task %s failed: %s", task_name, result)
            all_results.append({
                "task_name": task_name,
                "error": str(result),
                "status": "task_error",
            })
        else:
            all_results.extend(result)

    return all_results


async def main(
    data_file: str,
    output_dir: str,
    model: str = "o4-mini",
    reasoning_level: str = "high",
    max_tokens: int = 100000,
    temperature: float = 0.6,
    num_rounds: int = 3,
    concurrency: int = 1,
    time_budget: float = 43200.0,
    budget_mode: str = "sandbox",
    sandbox_run_budget: float | None = None,
    branch_strategy: str = "portfolio_first",
    warmup_branches: str = ",".join(DEFAULT_WARMUP_BRANCHES),
    task_skills_dir: str = str(DEFAULT_TASK_SKILLS_DIR),
    eda_skill_dir: str = str(DEFAULT_EDA_SKILL_DIR),
    error_skill_file: str = str(DEFAULT_ERROR_SKILL_FILE),
    local_eda_data_root: str = str(DEFAULT_LOCAL_EDA_DATA_ROOT),
    eda_timeout_seconds: int = 900,
    early_eda_branches: str = ",".join(DEFAULT_EARLY_EDA_BRANCHES),
    sandbox_base_url: str = SANDBOX_BASE_URL,
) -> None:
    """Main evaluation function."""
    data_path = Path(data_file)
    if data_path.suffix == ".json":
        tasks = json.loads(data_path.read_text(encoding="utf-8"))
    elif data_path.suffix == ".parquet":
        tasks = pd.read_parquet(data_path).to_dict(orient="records")
    else:
        raise ValueError(f"Unsupported file format: {data_path.suffix}")

    logger.info("Loaded %s tasks from %s", len(tasks), data_file)
    raw_warmup = [branch.strip() for branch in warmup_branches.split(",") if branch.strip()]
    warmup_tuple = normalize_branch_sequence(raw_warmup)
    invalid_warmup = [branch for branch in warmup_tuple if branch not in BRANCH_SPEC_BY_NAME]
    if invalid_warmup:
        raise ValueError(f"Unknown warmup branch(es): {invalid_warmup}. Valid branches: {sorted(BRANCH_SPEC_BY_NAME)}")
    early_eda_tuple = normalize_branch_sequence([branch.strip() for branch in early_eda_branches.split(",") if branch.strip()])
    invalid_early_eda = [branch for branch in early_eda_tuple if branch not in BRANCH_SPEC_BY_NAME]
    if invalid_early_eda:
        raise ValueError(f"Unknown early EDA branch(es): {invalid_early_eda}. Valid branches: {sorted(BRANCH_SPEC_BY_NAME)}")
    if branch_strategy not in {"portfolio_first", "operator_graph", "adaptive", "branch_cycle"}:
        raise ValueError("branch_strategy must be one of: portfolio_first, operator_graph, adaptive, branch_cycle")
    if budget_mode not in BUDGET_MODES:
        raise ValueError(f"budget_mode must be one of: {sorted(BUDGET_MODES)}")
    resolved_sandbox_run_budget = resolve_sandbox_run_budget(time_budget, sandbox_run_budget)

    logger.info(
        "Configuration: model=%s, reasoning_level=%s, rounds=%s, concurrency=%s, time_budget=%ss, budget_mode=%s, sandbox_run_budget=%ss",
        model,
        reasoning_level,
        num_rounds,
        concurrency,
        time_budget,
        budget_mode,
        resolved_sandbox_run_budget,
    )

    output_path = Path(output_dir).expanduser().resolve()
    contamination = detect_output_dir_contamination(output_path)
    if contamination:
        details = "\n- ".join(contamination)
        raise RuntimeError(
            "Refusing to run with contaminated output_dir. Use a fresh --output-dir or clean the listed path-layout problems.\n"
            f"- {details}"
        )
    output_path.mkdir(parents=True, exist_ok=True)
    resolved_task_skills_dir = Path(task_skills_dir)
    resolved_eda_skill_dir = Path(eda_skill_dir)
    resolved_error_skill_file = Path(error_skill_file)
    resolved_local_eda_data_root = Path(local_eda_data_root)

    config = {
        "data_file": data_file,
        "model": model,
        "reasoning_level": reasoning_level,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "num_rounds": num_rounds,
        "concurrency": concurrency,
        "time_budget": time_budget,
        "budget_mode": budget_mode,
        "sandbox_run_budget": resolved_sandbox_run_budget,
        "branch_strategy": branch_strategy,
        "warmup_branches": list(warmup_tuple),
        "task_skills_dir": str(resolved_task_skills_dir),
        "eda_skill_dir": str(resolved_eda_skill_dir),
        "error_skill_file": str(resolved_error_skill_file),
        "local_eda_data_root": str(resolved_local_eda_data_root),
        "eda_timeout_seconds": eda_timeout_seconds,
        "eda_policy": "early_bootstrap_plus_codex_context_acquisition_deep_eda",
        "bootstrap_early_eda": {
            "enabled": True,
            "trigger": "round_0_portfolio_seed",
            "decoupled_from_draft_branch": True,
            "archive_root": str(DEFAULT_EARLY_EDA_ARCHIVE_ROOT),
            "archive_policy": "reuse_task_archive_else_generate_and_store",
        },
        "legacy_extra_early_eda_branches": list(early_eda_tuple),
        "draft_implies_eda": False,
        "sandbox_base_url": sandbox_base_url,
        "submit_data_root": str(SUBMIT_DATA_ROOT),
        "v4": {
            "graph_dir": V3_GRAPH_DIR,
            "top_k_portfolio": V3_TOP_K_PORTFOLIO,
            "min_round_timeout_seconds": V3_MIN_ROUND_TIMEOUT_SECONDS,
            "external_timeout_policy": V4_EXTERNAL_TIMEOUT_POLICY,
            "external_timeout_cap_seconds": dict(V4_EXTERNAL_TIMEOUT_CAP_SECONDS),
            "final_audit_fraction": V3_FINAL_AUDIT_FRACTION,
            "exploration_fraction": V3_EXPLORATION_FRACTION,
            "enable_after_best_early_stop": V3_ENABLE_AFTER_BEST_EARLY_STOP,
            "submit_selection_policy": SUBMIT_SELECTION_POLICY,
            "submit_timeout_seconds": V4_SUBMIT_TIMEOUT_SECONDS,
            "llm_policy": V33_LLM_POLICY,
            "codex_phase_timeout_seconds": CODEX_PHASE_TIMEOUT_SECONDS,
            "standalone_planning_enabled": False,
            "integrated_planning_file": "context_readiness.md",
            "max_prompt_tokens": V35_MAX_PROMPT_TOKENS,
            "pinned_eda_schema_limit": V35_PINNED_EDA_SCHEMA_LIMIT,
            "filtered_user_task_limit_tokens": V35_FILTERED_USER_TASK_LIMIT_TOKENS,
            "selected_skill_card_limit_tokens": V35_SELECTED_SKILL_CARD_LIMIT_TOKENS,
            "support_calls_enabled": V33_SUPPORT_CALLS_DEFAULT,
            "deep_eda_after_best": V33_DEEP_EDA_AFTER_BEST,
            "deep_eda_min_valid_successes": V33_DEEP_EDA_MIN_VALID_SUCCESSES,
            "deep_eda_cooldown_rounds": V33_DEEP_EDA_COOLDOWN_ROUNDS,
            "max_deep_eda_runs": V33_MAX_DEEP_EDA_RUNS,
            "deep_eda_execution": "codex_context_acquisition_only",
            "memory_bank_recent_rounds": V34_MEMORY_BANK_RECENT_ROUNDS,
            "memory_bank_max_failures": V34_MEMORY_BANK_MAX_FAILURES,
            "memory_bank_max_eda_insights": V34_MEMORY_BANK_MAX_EDA_INSIGHTS,
            "budget_modes": sorted(BUDGET_MODES),
            "timeout_trap_recent_limit": V31_TIMEOUT_TRAP_RECENT_LIMIT,
            "timeout_trap_recent_threshold": V31_TIMEOUT_TRAP_RECENT_THRESHOLD,
            "strategy_replace_after_best": V31_STRATEGY_REPLACE_AFTER_BEST,
            "local_plateau_after_best": V31_LOCAL_PLATEAU_AFTER_BEST,
            "weak_start_success_limit": V36_WEAK_START_SUCCESS_LIMIT,
            "min_diverse_portfolio_families": V37_MIN_DIVERSE_PORTFOLIO_FAMILIES,
            "frontload_structural_success_target": V37_FRONTLOAD_DIVERSE_SUCCESS_LIMIT,
            "required_successful_draft_origin_seeds": V38_REQUIRED_DRAFT_ORIGIN_SEEDS,
            "frontload_max_attempts": V37_FRONTLOAD_MAX_ATTEMPTS,
            "frontload_max_attempts_role": "diagnostic_only_seed_collection_is_success_count_based",
            "frontload_code_action": "draft_independent_seed",
            "fresh_draft_after_scored_no_improvement": V38_PLATEAU_SCORED_ROUNDS_BEFORE_NEW_DRAFT,
            "fresh_draft_cooldown_rounds": V37_FRESH_DRAFT_COOLDOWN_ROUNDS,
            "max_fresh_draft_runs": V38_MAX_FRESH_DRAFT_RUNS,
            "fresh_draft_requires_concrete_anchor": False,
            "fresh_draft_model_prior_fallback": True,
            "max_debug_repairs_per_seed": V38_MAX_DEBUG_REPAIRS_PER_SEED,
            "debug_success_inherits_parent_effective_identity": True,
            "non_debug_no_score_statuses": sorted(NON_DEBUG_NO_SCORE_STATUSES),
            "strong_candidate_count": V36_STRONG_CANDIDATE_COUNT,
            "portfolio_first": True,
        },
        "branch_specs": {
            spec.name: {
                "title": spec.title,
                "goal": spec.goal,
                "instructions": spec.instructions,
            }
            for spec in BRANCH_SPECS
        },
        "timestamp": datetime.now().isoformat(),
        "backend": BACKEND_ID,
    }
    (output_path / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    sandbox_client = httpx.AsyncClient(
        base_url=sandbox_base_url,
        timeout=httpx.Timeout(300.0, connect=60.0),
        trust_env=False,
    )

    try:
        all_results = await evaluate_tasks_concurrent(
            sandbox_client=sandbox_client,
            tasks=tasks,
            output_path=output_path,
            model=model,
            reasoning_level=reasoning_level,
            max_tokens=max_tokens,
            temperature=temperature,
            num_rounds=num_rounds,
            concurrency=concurrency,
            time_budget=time_budget,
            budget_mode=budget_mode,
            sandbox_run_budget=resolved_sandbox_run_budget,
            branch_strategy=branch_strategy,
            warmup_branches=warmup_tuple,
            task_skills_dir=resolved_task_skills_dir,
            eda_skill_dir=resolved_eda_skill_dir,
            error_skill_file=resolved_error_skill_file,
            local_eda_data_root=resolved_local_eda_data_root,
            eda_timeout_seconds=eda_timeout_seconds,
            early_eda_branches=early_eda_tuple,
        )
        (output_path / "summary.json").write_text(json.dumps(all_results, indent=2), encoding="utf-8")
        logger.info("Evaluation complete. Results saved to %s", output_path)
    finally:
        await sandbox_client.aclose()


def cli_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "BSPM Codex v4 portfolio-first runtime search with sandbox budget, compact task-skill evidence, "
            "source-map EDA paths, structured memory/portfolio bank, static validation gates, and validation-best submit selection"
        )
    )
    parser.add_argument("--data-file", type=str, required=True, help="Path to task data file (JSON or Parquet)")
    parser.add_argument("--output-dir", type=str, required=True, help="Output directory for results")
    parser.add_argument("--model", type=str, default="o4-mini", help="OpenAI model to use")
    parser.add_argument("--reasoning-level", type=str, default="high", help="Codex reasoning level")
    parser.add_argument("--max-tokens", type=int, default=100000, help="Maximum tokens for generation")
    parser.add_argument("--temperature", type=float, default=0.6, help="Temperature for generation")
    parser.add_argument("--num-rounds", type=int, default=256, help="Number of refinement rounds per task")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of tasks to process concurrently")
    parser.add_argument("--time-budget", type=float, default=43200.0, help="Total time budget per task in seconds")
    parser.add_argument(
        "--budget-mode",
        type=str,
        default="sandbox",
        choices=sorted(BUDGET_MODES),
        help="Scheduler budget accounting. v4 default and normal mode is sandbox net validation runtime.",
    )
    parser.add_argument(
        "--sandbox-run-budget",
        type=float,
        default=None,
        help="Total sandbox started-to-completed validation runtime budget per task in seconds; defaults to --time-budget",
    )
    parser.add_argument(
        "--branch-strategy",
        type=str,
        default="portfolio_first",
        choices=["portfolio_first", "operator_graph", "adaptive", "branch_cycle"],
        help="Compatibility label; v4 always uses portfolio-first scheduling",
    )
    parser.add_argument(
        "--warmup-branches",
        type=str,
        default=",".join(DEFAULT_WARMUP_BRANCHES),
        help="Compatibility-only field; v4 portfolio policy ignores warmup branch cycling",
    )
    parser.add_argument(
        "--task-skills-dir",
        type=str,
        default=str(DEFAULT_TASK_SKILLS_DIR),
        help="Directory containing task-specific SKILL_<task>.md files",
    )
    parser.add_argument(
        "--eda-skill-dir",
        type=str,
        default=str(DEFAULT_EDA_SKILL_DIR),
        help="Directory containing the EDA guardrail skill package",
    )
    parser.add_argument(
        "--error-skill-file",
        type=str,
        default=str(DEFAULT_ERROR_SKILL_FILE),
        help="Markdown file containing the error-prevention skill",
    )
    parser.add_argument(
        "--local-eda-data-root",
        type=str,
        default=str(DEFAULT_LOCAL_EDA_DATA_ROOT),
        help="Root containing local public validation data for conditional early EDA",
    )
    parser.add_argument(
        "--eda-timeout-seconds",
        type=int,
        default=900,
        help="Timeout for each local EDA script run",
    )
    parser.add_argument(
        "--early-eda-branches",
        type=str,
        default=",".join(DEFAULT_EARLY_EDA_BRANCHES),
        help=(
            "Legacy extra branch-level early EDA triggers. Empty by default: v4 runs EDA by explicit "
            "information action, namely bootstrap portfolio seed or an explicit bottleneck round, not because branch=draft."
        ),
    )
    parser.add_argument(
        "--sandbox-base-url",
        type=str,
        default=SANDBOX_BASE_URL,
        help="Sandbox service base URL",
    )

    args = parser.parse_args()

    asyncio.run(main(
        data_file=args.data_file,
        output_dir=args.output_dir,
        model=args.model,
        reasoning_level=args.reasoning_level,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        num_rounds=args.num_rounds,
        concurrency=args.concurrency,
        time_budget=args.time_budget,
        budget_mode=args.budget_mode,
        sandbox_run_budget=args.sandbox_run_budget,
        branch_strategy=args.branch_strategy,
        warmup_branches=args.warmup_branches,
        task_skills_dir=args.task_skills_dir,
        eda_skill_dir=args.eda_skill_dir,
        error_skill_file=args.error_skill_file,
        local_eda_data_root=args.local_eda_data_root,
        eda_timeout_seconds=args.eda_timeout_seconds,
        early_eda_branches=args.early_eda_branches,
        sandbox_base_url=args.sandbox_base_url,
    ))


if __name__ == "__main__":
    cli_main()
