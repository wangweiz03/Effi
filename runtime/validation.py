from __future__ import annotations

import ast

from .common import *
from .constants import *

def _truncate_text(text: str | None, limit: int) -> str:
    """Keep prompts bounded while preserving both beginning and end."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    head = max(limit // 2, 0)
    tail = max(limit - head, 0)
    return text[:head] + "\n...[truncated]...\n" + text[-tail:]


def _parse_round_summary(raw_text: str) -> dict[str, str]:
    """Parse the two summary fields from Codex output."""
    text = raw_text.strip()
    candidates = [text]

    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates.extend(fenced)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        method_summary = str(payload.get("method_summary", "")).strip()
        method_profile = str(payload.get("method_profile", "")).strip()
        result_reflection = str(payload.get("result_reflection", "")).strip()
        method_family = str(payload.get("method_family", "")).strip()
        novelty_vs_best = str(payload.get("novelty_vs_best", "")).strip()
        core_components_raw = payload.get("core_components", [])
        if isinstance(core_components_raw, list):
            core_components = [str(item).strip()[:80] for item in core_components_raw if str(item).strip()][:8]
        elif core_components_raw:
            core_components = [str(core_components_raw).strip()[:80]]
        else:
            core_components = []
        if method_summary or result_reflection:
            return {
                "method_summary": method_summary,
                "method_profile": method_profile[:900],
                "result_reflection": result_reflection[:240],
                "method_family": method_family[:80],
                "core_components": core_components,
                "novelty_vs_best": novelty_vs_best[:240],
            }

    raise ValueError("Codex summary response did not contain valid JSON fields")


def infer_posthoc_method_family(task_dir: Path | None) -> str:
    """Infer method family from Codex's context_readiness before falling back to compat fields."""
    if task_dir is None:
        return ""
    path = task_dir / "context_readiness.md"
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    patterns = (
        r"(?im)^\s*[-*]?\s*method_family\s*:\s*`?([A-Za-z0-9_. -]+)`?",
        r"(?im)^\s*[-*]?\s*方法族\s*[:：]\s*`?([A-Za-z0-9_. -]+)`?",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = re.sub(r"[^A-Za-z0-9_.-]+", "_", match.group(1).strip()).strip("_").lower()
        if value:
            try:
                return canonical_method_family(value)
            except Exception:
                return value[:80]
    return ""


def _parse_post_code_method_summary_block(block: str, *, source: str) -> dict[str, Any]:
    """Parse a post-code method portrait block."""
    match = re.search(
        r"(?ims)^#{1,6}\s*Post-Code (?:Memory|Method) Summary\s*$\s*(.*?)(?=^#{1,6}\s+|\Z)",
        block,
    )
    if match:
        block = match.group(1).strip()
    else:
        block = block.strip()
    field_aliases = {
        "card_method_summary": "method_summary",
        "method_summary": "method_summary",
        "summary": "method_summary",
        "card_method_profile": "method_profile",
        "method_profile": "method_profile",
        "profile": "method_profile",
        "card_core_components": "core_components",
        "core_components": "core_components",
        "components": "core_components",
        "card_reuse_risk": "card_reuse_risk",
        "reuse_risk": "card_reuse_risk",
        "diff_action": "diff_action",
        "action": "diff_action",
        "diff_reason": "diff_reason",
        "reason": "diff_reason",
        "parent_modification_summary": "parent_modification_summary",
        "modification_summary": "parent_modification_summary",
        "memory_reuse_signal": "memory_reuse_signal",
        "reuse_signal": "memory_reuse_signal",
    }
    fields: dict[str, str] = {}
    current_key = ""
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        field_match = re.match(r"^\s*[-*]?\s*([A-Za-z_][A-Za-z0-9_ -]{1,60})\s*[:：]\s*(.*)$", line)
        if field_match:
            raw_key = re.sub(r"[^a-z0-9]+", "_", field_match.group(1).strip().lower()).strip("_")
            key = field_aliases.get(raw_key)
            if key:
                current_key = key
                value = field_match.group(2).strip()
                if value:
                    fields[key] = (fields.get(key, "") + " " + value).strip()
                else:
                    fields.setdefault(key, "")
                continue
        if current_key:
            continuation = re.sub(r"^\s*[-*]\s*", "", line.strip())
            fields[current_key] = (fields[current_key] + " " + continuation).strip()
    if not fields:
        return {}
    core_components_raw = fields.get("core_components") or ""
    core_components = [
        item.strip()[:80]
        for item in re.split(r"[,;]", core_components_raw)
        if item.strip()
    ][:10]
    return {
        "method_summary": fields.get("method_summary", ""),
        "method_profile": shrink_text_middle(fields.get("method_profile", ""), 1400),
        "core_components": core_components,
        "parent_modification_summary": shrink_text_middle(
            fields.get("parent_modification_summary") or fields.get("diff_action") or "",
            900,
        ),
        "memory_reuse_signal": shrink_text_middle(
            fields.get("memory_reuse_signal") or fields.get("card_reuse_risk") or "",
            700,
        ),
        "card_reuse_risk": shrink_text_middle(fields.get("card_reuse_risk") or fields.get("memory_reuse_signal") or "", 700),
        "diff_action": shrink_text_middle(fields.get("diff_action") or fields.get("parent_modification_summary") or "", 900),
        "diff_reason": shrink_text_middle(fields.get("diff_reason") or "", 900),
        "source": source,
    }


def extract_post_code_method_summary(task_dir: Path | None) -> dict[str, Any]:
    """Parse the coding agent's post-code method portrait from its dedicated file.

    Older artifacts placed this block at the end of context_readiness.md; keep
    that fallback for compatibility, but new prompts write a separate file so
    context_readiness.md remains a pre-code audit artifact.
    """
    if task_dir is None:
        return {}
    candidates = [
        (task_dir / POST_CODE_MEMORY_SUMMARY_FILENAME, "post_code_memory_summary_file"),
        (task_dir / "context_readiness.md", "context_readiness_legacy_post_code_memory_summary"),
    ]
    for path, source in candidates:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        parsed = _parse_post_code_method_summary_block(text, source=source)
        if parsed:
            return parsed
    return {}


def _find_initial_eda_findings_md(task_dir: Path) -> Path | None:
    preferred = task_dir / "early_eda" / "round_0" / "eda_findings.md"
    if preferred.exists():
        return preferred
    candidates = sorted((task_dir / "early_eda").glob("round_*/eda_findings.md"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def append_deep_eda_insights_to_initial_findings(task_dir: Path, insights: list[dict[str, Any]]) -> int:
    """Append context-acquisition deep EDA facts to the task-local initial EDA markdown.

    The durable machine-readable store remains `memory_bank/eda_insights.jsonl`.
    This markdown append keeps the human EDA state file current for agents that
    inspect the full EDA findings path. Markers make repeated validation/replay
    calls idempotent.
    """
    if not insights:
        return 0
    path = _find_initial_eda_findings_md(task_dir)
    if path is None:
        return 0
    try:
        existing = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    appended: list[str] = []
    if "## Context Deep EDA Updates" not in existing:
        appended.extend(["", "## Context Deep EDA Updates", ""])
    for idx, insight in enumerate(insights):
        if not isinstance(insight, dict):
            continue
        marker = f"<!-- bspm-context-deep-eda round={insight.get('round')} commit={insight.get('commit') or 'none'} idx={idx} -->"
        if marker in existing or marker in "\n".join(appended):
            continue
        files_checked = insight.get("files_checked")
        if isinstance(files_checked, list):
            files_text = ", ".join(str(item) for item in files_checked[:8])
        else:
            files_text = str(files_checked or "").strip()
        commands = insight.get("commands_or_reads")
        if isinstance(commands, list):
            commands_text = ", ".join(str(item) for item in commands[:8])
        else:
            commands_text = str(commands or "").strip()
        appended.extend([
            marker,
            f"### Round {insight.get('round')} Context Deep EDA",
            f"- source: deep_eda",
            f"- commit: {insight.get('commit') or 'none'}",
            f"- trigger: {insight.get('trigger') or 'unspecified'}",
            f"- files_checked: {files_text or 'none recorded'}",
            f"- commands_or_reads: {commands_text or 'none recorded'}",
            f"- finding: {insight.get('finding') or 'none recorded'}",
            f"- confidence: {insight.get('confidence') or 'unknown'}",
            f"- coding_implication: {insight.get('coding_implication') or 'none recorded'}",
            f"- validation_status: {insight.get('validation_status') or 'unknown'}",
            f"- validation_score: {insight.get('validation_score') if insight.get('validation_score') is not None else 'none'}",
            "",
        ])
    if not appended or all(not line.strip() for line in appended):
        return 0
    try:
        suffix = "\n" if existing.endswith("\n") else "\n\n"
        path.write_text(existing.rstrip() + suffix + "\n".join(appended).rstrip() + "\n", encoding="utf-8")
    except Exception:
        return 0
    return sum(1 for line in appended if line.startswith("<!-- bspm-context-deep-eda"))


def extract_context_deep_eda_insights(
    *,
    task_dir: Path,
    round_num: int,
    commit_hash: str | None,
    validation_status: str | None,
    validation_score: float | None,
) -> list[dict[str, Any]]:
    """Parse structured deep-EDA facts written by the coding agent before solution.py."""
    path = task_dir / "context_readiness.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    insights: list[dict[str, Any]] = []
    for block in blocks:
        try:
            payload = json.loads(block)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        source = str(payload.get("source") or "").strip().lower()
        has_deep_fields = any(payload.get(key) for key in ("trigger", "files_checked", "finding", "coding_implication"))
        if source not in {"deep_eda", "context_deep_eda"} and not has_deep_fields:
            continue
        finding = shrink_text_middle(str(payload.get("finding") or payload.get("summary") or "").strip(), 1200)
        coding_implication = shrink_text_middle(str(payload.get("coding_implication") or "").strip(), 800)
        if not finding and not coding_implication:
            continue
        files_checked_raw = payload.get("files_checked")
        if isinstance(files_checked_raw, list):
            files_checked = [str(item).strip()[:240] for item in files_checked_raw if str(item).strip()][:20]
        elif files_checked_raw:
            files_checked = [str(files_checked_raw).strip()[:240]]
        else:
            files_checked = []
        commands_raw = payload.get("commands_or_reads")
        if isinstance(commands_raw, list):
            commands_or_reads = [str(item).strip()[:240] for item in commands_raw if str(item).strip()][:20]
        elif commands_raw:
            commands_or_reads = [str(commands_raw).strip()[:240]]
        else:
            commands_or_reads = []
        insights.append({
            "schema_version": "eda_insight_v2",
            "source": "deep_eda",
            "round": round_num,
            "commit": commit_hash,
            "trigger": shrink_text_middle(str(payload.get("trigger") or "").strip(), 500),
            "files_checked": files_checked,
            "commands_or_reads": commands_or_reads,
            "finding": finding,
            "confidence": str(payload.get("confidence") or "unknown").strip()[:40],
            "coding_implication": coding_implication,
            "validation_status": validation_status,
            "validation_score": validation_score,
            "context_readiness_path": "context_readiness.md",
            "created_at": datetime.now().isoformat(),
        })
    return insights[:4]


def classify_validation_failure(status: str, feedback: str) -> dict[str, Any]:
    """Classify common runtime failures so debug rounds stay concrete."""
    text = f"{status}\n{feedback}".lower()
    timeout_evidence = timeout_failure_evidence(status, feedback)
    if timeout_evidence:
        return {
            "primary": "timeout",
            "all": ["timeout"],
            "evidence": timeout_evidence,
            "source": "structured_timeout_classifier",
            "debug_instruction": (
                "Repair the timeout with a trained score-first route and a smaller statically bounded workload; "
                "preserve the method family only when its reduced candidate/fold/epoch plan can finish externally."
            ),
        }
    if (
        "y contains previously unseen labels" in text
        or "previously unseen labels" in text
        or ("labelencoder" in text and "unseen" in text and "labels" in text)
    ):
        return {
            "primary": "fold_label_coverage",
            "all": ["fold_label_coverage", "model_training", "runtime_exception"],
            "evidence": "unseen_fold_labels",
            "source": "validation_failure_classifier",
            "debug_instruction": (
                "Repair the fold/meta-model label coverage issue: ensure each classifier fold sees every class it "
                "must predict, use a label-stable objective, or skip/remap invalid per-fold meta candidates without "
                "changing the submission schema."
            ),
        }
    if (
        "invalid literal for int" in text
        or "could not convert" in text
        or ("traceback" in text and ("unicode" in text or "decode" in text))
    ):
        return {
            "primary": "data_parsing",
            "all": ["data_parsing", "runtime_exception"],
            "evidence": "parsing_exception",
            "source": "validation_failure_classifier",
            "debug_instruction": (
                "Repair the concrete parsing/runtime exception with the smallest necessary code change; preserve "
                "the current method unless the traceback proves it cannot run."
            ),
        }
    checks = [
        ("oom", ("out of memory", "oom", "cuda error: out of memory", "memoryerror", "killed")),
        ("dependency", ("modulenotfounderror", "importerror", "no module named", "not installed", "distributionnotfound")),
        ("schema", ("keyerror", "column", "columns", "not in index", "feature names", "shape mismatch")),
        ("submission", ("submission file", "wrong number of rows", "missing column", "sample submission missing")),
        ("metric", ("metric", "scoring", "auc", "rmse", "log_loss", "quadratic weighted kappa")),
        ("data_parsing", ("parsererror", "unicode", "decode", "bad lines", "file not found", "filenotfounderror", "is a directory")),
    ]
    matched = [name for name, needles in checks if any(needle in text for needle in needles)]
    output_format_patterns = (
        r"\binvalid\s+(?:output|submission|format|dtype|json|csv|header)\b",
        r"\b(?:output|submission)\s+format\s+(?:error|invalid|mismatch)\b",
        r"\b(?:nan|inf(?:inity)?)\s+(?:found|detected|in\s+(?:output|prediction|submission))\b",
        r"\b(?:output|prediction|submission)\s+contains?\s+(?:nan|inf(?:inity)?)\b",
        r"\bdtype\s+(?:error|mismatch|invalid)\b",
        r"\bjsondecodeerror\b",
        r"\bcsv\s+(?:parse|format|header)\s+(?:error|invalid|mismatch)\b",
        r"\b(?:missing|unexpected|duplicate)\s+(?:csv\s+)?header\b",
    )
    if any(re.search(pattern, text) for pattern in output_format_patterns):
        matched.append("output_format")
    if not matched and ("traceback" in text or "error" in text or "exception" in text):
        matched = ["runtime_exception"]
    return {
        "primary": matched[0] if matched else "unknown",
        "all": matched,
        "evidence": "feedback_taxonomy" if matched else "none",
        "source": "validation_failure_classifier",
        "debug_instruction": (
            "Repair the classified failure with the smallest necessary code change; preserve the current method unless "
            "the taxonomy and feedback prove it cannot run."
        ),
    }


def _operator_focus_tokens(operator: Any | None) -> set[str]:
    if operator is None:
        return set()
    if isinstance(operator, dict):
        fields = [operator.get("name"), operator.get("family")]
    else:
        fields = [getattr(operator, "name", ""), getattr(operator, "family", "")]
    text = " ".join(str(item or "") for item in fields).lower()
    stop = {
        "portfolio",
        "strengthen",
        "frontload",
        "fresh",
        "draft",
        "seed",
        "best",
        "model",
        "prior",
        "score",
        "first",
        "logloss",
        "loss",
        "auc",
        "qwk",
        "rmse",
        "mae",
        "route",
        "task",
        "skill",
        "operator",
        "candidate",
        "classification",
        "challenge",
    }
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", text)
        if len(token) >= 3 and token not in stop
    }
    # Keep common high-signal short modality tokens.
    for token in ("cnn", "svm", "svc", "mlp", "knn", "gbdt", "xgb"):
        if token in text:
            tokens.add(token)
    return tokens


def _is_score_first_timeout_recovery_operator(operator: Any | None) -> bool:
    """Detect timeout-recovery operators even when the scheduler state is generic."""
    if operator is None:
        return False
    if isinstance(operator, dict):
        fields = [
            operator.get("name"),
            operator.get("intent"),
            operator.get("family"),
            operator.get("source"),
            operator.get("description"),
        ]
    else:
        fields = [
            getattr(operator, "name", ""),
            getattr(operator, "intent", ""),
            getattr(operator, "family", ""),
            getattr(operator, "source", ""),
            getattr(operator, "description", ""),
        ]
    text = " ".join(str(item or "") for item in fields).lower()
    return (
        "score_first_timeout_recovery" in text
        or "score-first timeout recovery" in text
        or "repeated timeouts produced no score" in text
        or (
            "timeout" in text
            and "score" in text
            and "first" in text
            and "recovery" in text
        )
    )


def _failed_candidate_names(feedback: str) -> list[str]:
    lower = (feedback or "").lower()
    names: list[str] = []
    patterns = [
        r'"(?P<name>[^"\n]{3,120})"\s*:\s*"(?:[^"]{0,80})?(?:error|exception|traceback|valueerror|runtimeerror|failed)',
        r"\b(?:candidate[-_ ]?error|failed[-_ ]?candidate|candidate[-_ ]?failed)\b[^\\n]{0,160}?\b(?:name|candidate)\s*[=:]\s*(?P<name>[a-z0-9_.+-]{3,120})",
        r"\b(?P<name>[a-z0-9_.+-]{3,120})\s+failed\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, lower, flags=re.DOTALL):
            name = match.group("name").strip(" '\"\t\r\n,;:")
            if not name:
                continue
            if any(bad in name for bad in ("submission.csv", "sample_submission", "train.csv", "test.csv")):
                continue
            names.append(name)
    unique: list[str] = []
    for name in names:
        if name not in unique:
            unique.append(name)
    return unique[:12]


def _selected_fallback_route(feedback: str) -> dict[str, Any]:
    lower = (feedback or "").lower()
    selected = ""
    fallback_path = ""
    selected_match = re.search(r'"selected_candidate"\s*:\s*"(?P<name>[^"]+)"', lower)
    if not selected_match:
        selected_match = re.search(r"\bselected_candidate\s*[=:]\s*(?P<name>[a-z0-9_.+-]+)", lower)
    if selected_match:
        selected = selected_match.group("name")
    fallback_match = re.search(r'"fallback_path"\s*:\s*"(?P<name>[^"]+)"', lower)
    if not fallback_match:
        fallback_match = re.search(r"\bfallback_path\s*[=:]\s*(?P<name>[a-z0-9_.+-]+)", lower)
    if fallback_match:
        fallback_path = fallback_match.group("name")
    fallback_route_tokens = (
        "fallback",
        "weighted_blend",
        "weighted_oof_blend",
        "mean_blend",
        "best_single",
        "prior",
        "template",
        "old",
        "incumbent",
    )
    fallback_selected = any(token in selected for token in fallback_route_tokens) or any(token in fallback_path for token in fallback_route_tokens)
    return {
        "selected_candidate": selected,
        "fallback_path": fallback_path,
        "fallback_selected": fallback_selected,
    }


def detect_validation_quality_issue(
    code: str,
    status: str,
    raw_score: float | None,
    feedback: str,
    search_operator: Any | None = None,
    strict_score_first_required: bool = False,
) -> dict[str, Any]:
    """Detect scored submissions that are valid-format but not useful learned attempts."""
    lower_code = (code or "").lower()
    lower_feedback = (feedback or "").lower()
    feedback_status_text = f"{status}\n{lower_feedback}"

    parse_failure_markers = (
        "fatal error",
        "failed to parse",
        "unable to infer",
        "unable to resolve",
        "no labeled",
        "no labels",
        "no training",
        "no train",
        "target column",
        "could not infer",
    )
    fallback_markers = (
        "fallback submission",
        "wrote fallback",
        "fallback predictions",
        "make_fallback_predictions",
        "[validation-fallback]",
        "[selected-candidate-fallback]",
        "validation-fallback",
        "selected-candidate-fallback",
        "constant prediction",
        "emergency fallback",
        "conservative fallback",
        "sample submission template",
        "prior_fallback",
        "fallback_trained_prior",
        "all candidates failed",
        "exception_fallback_candidate",
    )
    constant_prediction_patterns = (
        r"np\.full\s*\([\s\S]{0,240},\s*(?:0(?:\.0+)?|0\.5|1(?:\.0+)?)",
        r"submission\s*\[[^\]]+\]\s*=\s*(?:0(?:\.0+)?|0\.5|1(?:\.0+)?)",
        r"submission\.[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:0(?:\.0+)?|0\.5|1(?:\.0+)?)",
    )
    has_parse_failure = any(marker in feedback_status_text for marker in parse_failure_markers)
    has_fallback_marker_feedback = any(marker in feedback_status_text for marker in fallback_markers)
    has_fallback_marker_code = any(marker in lower_code for marker in fallback_markers)
    has_constant_prediction = any(re.search(pattern, lower_code, flags=re.DOTALL) for pattern in constant_prediction_patterns)
    fallback_selected = (
        "selected_final\tprior_fallback" in feedback_status_text
        or "selected_candidate=prior_fallback" in feedback_status_text
        or "fallback_trained_prior" in feedback_status_text
    )
    real_candidate_failures = len(re.findall(r"\bfailed:(?!none)", lower_feedback))
    real_candidate_success_lines = len(re.findall(r"\b(?:ok|success)\b", lower_feedback))

    has_training_evidence = any(token in lower_code for token in (
        ".fit(",
        " fit(",
        "train(",
        "lgb.train",
        "catboost",
        "xgboost",
        "torch",
        "stratifiedkfold",
        "kfold",
        "cross_val",
    ))
    writes_submission = "submission.csv" in lower_code or "submission.csv" in lower_feedback
    exact_auc_random_score = raw_score is not None and abs(float(raw_score) - 0.5) <= 1e-12
    failed_candidate_names = _failed_candidate_names(feedback)
    fallback_route = _selected_fallback_route(feedback)
    fallback_exception_match = re.search(
        r"\[(?:validation|selected-candidate)-fallback\]\s+reason=(?P<reason>[^\n\r]+)",
        lower_feedback,
    )
    exception_fallback_match = re.search(
        r"\[exception\]\s*(?P<reason>[^\n\r]+)[\s\S]{0,2000}?"
        r"(?:exception_fallback_candidate|fallback_candidate|fallback_path)\s*[=:]\s*(?P<fallback>[a-z0-9_.+-]+)",
        lower_feedback,
    )
    operator_tokens = _operator_focus_tokens(search_operator)
    failed_text = " ".join(failed_candidate_names)
    selected_route_failed = bool(
        operator_tokens
        and failed_candidate_names
        and any(token in failed_text for token in operator_tokens)
    )

    if raw_score is not None and writes_submission and fallback_exception_match:
        return {
            "kind": "route_failed_with_fallback_score",
            "submit_eligible": False,
            "reason": "validation or selected route raised an exception and the scored submission came from a fallback path",
            "raw_score": raw_score,
            "fallback_exception": fallback_exception_match.group("reason").strip(),
            "failed_candidate_names": failed_candidate_names,
            "selected_candidate": fallback_route.get("selected_candidate"),
            "fallback_path": fallback_route.get("fallback_path"),
        }

    if (
        raw_score is not None
        and writes_submission
        and strict_score_first_required
        and exception_fallback_match
    ):
        return {
            "kind": "route_failed_with_fallback_score",
            "submit_eligible": False,
            "reason": "strict primary route raised an exception and the scored submission came from an exception fallback path",
            "raw_score": raw_score,
            "fallback_exception": exception_fallback_match.group("reason").strip(),
            "failed_candidate_names": failed_candidate_names,
            "selected_candidate": fallback_route.get("selected_candidate"),
            "fallback_path": exception_fallback_match.group("fallback").strip(),
        }

    if raw_score is not None and writes_submission and selected_route_failed and fallback_route.get("fallback_selected"):
        return {
            "kind": "route_failed_with_fallback_score",
            "submit_eligible": False,
            "reason": "selected route failed but final submission fell back to an older/simple blend or fallback path",
            "raw_score": raw_score,
            "failed_candidate_names": failed_candidate_names,
            "operator_focus_tokens": sorted(operator_tokens),
            "selected_candidate": fallback_route.get("selected_candidate"),
            "fallback_path": fallback_route.get("fallback_path"),
        }

    if raw_score is not None and writes_submission and exact_auc_random_score and has_constant_prediction and (
        has_fallback_marker_feedback or has_fallback_marker_code or has_parse_failure
    ):
        return {
            "kind": "constant_prediction_success",
            "submit_eligible": False,
            "reason": "exact 0.5 score with constant/fallback prediction evidence",
            "raw_score": raw_score,
        }

    if raw_score is not None and writes_submission and has_constant_prediction and not has_training_evidence and (
        has_fallback_marker_feedback or has_fallback_marker_code or has_parse_failure
    ):
        return {
            "kind": "uninformative_fallback",
            "submit_eligible": False,
            "reason": "scored submission appears to be an untrained constant/fallback output",
            "raw_score": raw_score,
        }

    if raw_score is not None and writes_submission and fallback_selected and real_candidate_failures > 0:
        return {
            "kind": "fallback_dominated_success",
            "submit_eligible": False,
            "reason": "scored submission selected a prior/fallback route after real candidates failed",
            "raw_score": raw_score,
            "real_candidate_failures": real_candidate_failures,
        }

    if raw_score is not None and writes_submission and has_parse_failure and (
        has_fallback_marker_feedback or has_fallback_marker_code or has_constant_prediction
    ):
        return {
            "kind": "success_with_fallback_warning",
            "submit_eligible": True,
            "reason": "scored submission kept; fallback/parse evidence is warning-only without hard untrained-constant proof",
            "raw_score": raw_score,
        }

    return {
        "kind": "normal_success" if raw_score is not None else "no_score",
        "submit_eligible": raw_score is not None,
        "reason": "no uninformative fallback evidence detected",
        "raw_score": raw_score,
    }


SIDE_OUTPUT_PATH_RE = re.compile(
    r"(?:^|[/_.-])(?:oof|pred|preds|prediction|predictions|model|models|fold_dump|folds_dump|blend)(?:[/_.-]|$)"
)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _string_value(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
        return "".join(parts)
    if isinstance(node, ast.Call) and _call_name(node.func).endswith("Path") and node.args:
        return _string_value(node.args[0])
    return ""


def _name_value(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id.lower()
    if isinstance(node, ast.Attribute):
        return node.attr.lower()
    return ""


def _submission_path(path_text: str, node_name: str = "") -> bool:
    text = f"{path_text} {node_name}".lower()
    return "submission" in text and not SIDE_OUTPUT_PATH_RE.search(text)


def _side_output_target(path_node: ast.AST | None) -> bool:
    path_text = _string_value(path_node).lower()
    node_name = _name_value(path_node)
    if _submission_path(path_text, node_name):
        return False
    legacy_file_bucket = "arti" + "fact"
    if path_text:
        if re.search(rf"(?:^|[/_.-]){legacy_file_bucket}s?(?:[/_.-]|$)", path_text):
            return True
        return bool(SIDE_OUTPUT_PATH_RE.search(path_text))
    return bool(re.search(r"\b(?:oof|preds?|predictions?|models?)_(?:path|file|csv|pkl|npy|parquet)\b", node_name))


def _detect_side_output_file_evidence(code: str) -> list[dict[str, str]]:
    """Detect actual cross-round file writes without flagging input path variables like test_path."""
    evidence: list[dict[str, str]] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return evidence

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call = _call_name(node.func).lower()
        first_arg = node.args[0] if node.args else None

        if call in {"joblib.dump", "pickle.dump", "cloudpickle.dump", "dill.dump"}:
            evidence.append({"pattern": call, "snippet": "serializer dump call"})
        elif call in {"np.save", "numpy.save", "np.savez", "numpy.savez", "np.savez_compressed", "numpy.savez_compressed"}:
            evidence.append({"pattern": call, "snippet": "numpy array save call"})
        elif call in {"to_pickle", "to_parquet", "to_feather", "to_hdf"} or call.endswith((".to_pickle", ".to_parquet", ".to_feather", ".to_hdf")):
            evidence.append({"pattern": call, "snippet": "non-csv dataframe file write"})
        elif (call == "to_csv" or call.endswith(".to_csv")) and node.args and _side_output_target(first_arg):
            evidence.append({"pattern": call, "snippet": _string_value(first_arg) or _name_value(first_arg)})
        elif call == "open" and len(node.args) >= 2:
            mode = _string_value(node.args[1]).lower()
            if any(flag in mode for flag in ("w", "a", "+")) and _side_output_target(first_arg):
                evidence.append({"pattern": call, "snippet": _string_value(first_arg) or _name_value(first_arg)})
        elif call.endswith((".write_text", ".write_bytes")) and _side_output_target(getattr(node.func, "value", None)):
            evidence.append({"pattern": call, "snippet": _string_value(getattr(node.func, "value", None)) or _name_value(getattr(node.func, "value", None))})

    return evidence[:5]


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_name(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return ""


def _literal_true(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _literal_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _keyword_true(call: ast.Call, name: str) -> bool:
    return any(keyword.arg == name and _literal_true(keyword.value) for keyword in call.keywords)


def _keyword_none(call: ast.Call, name: str) -> bool:
    return any(keyword.arg == name and _literal_none(keyword.value) for keyword in call.keywords)


def _keyword_local_files_only(call: ast.Call) -> bool:
    return any(keyword.arg == "local_files_only" and _literal_true(keyword.value) for keyword in call.keywords)


def _has_offline_pretrained_guard(code: str) -> bool:
    lower = code.lower()
    has_offline_mode = any(token in lower for token in (
        "hf_hub_offline",
        "transformers_offline",
        "local_files_only",
        "offline",
        "cache_only",
        "local cache",
        "local_cache",
    ))
    has_quick_fallback = (
        "try:" in lower
        and "except" in lower
        and any(token in lower for token in (
            "pretrained=false",
            "pretrained = false",
            "weights=none",
            "weights = none",
            "fallback",
            "no-download",
            "no download",
        ))
    )
    return bool(has_offline_mode and has_quick_fallback)


def _detect_external_download_evidence(code: str) -> list[dict[str, Any]]:
    """Detect model/data download calls that can hang or fail inside sandbox validation."""
    evidence: list[dict[str, Any]] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return evidence

    download_call_names = {
        "hf_hub_download",
        "snapshot_download",
        "torch.hub.load",
        "load_state_dict_from_url",
        "urlretrieve",
        "requests.get",
        "wget.download",
    }

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func).lower()
        line = getattr(node, "lineno", None)
        if _keyword_true(node, "pretrained") and not _has_offline_pretrained_guard(code):
            evidence.append({"line": line, "call": name, "reason": "pretrained_true"})

        # A non-None torchvision `weights=` argument can be valid when the code
        # checks a local cache and falls back to `weights=None`. Direct download
        # APIs and `pretrained=True` remain hard blockers below.

        if _keyword_true(node, "download"):
            evidence.append({"line": line, "call": name, "reason": "download_true"})

        if name.endswith(".from_pretrained") or name == "from_pretrained":
            if not _keyword_local_files_only(node):
                evidence.append({"line": line, "call": name, "reason": "from_pretrained_not_local_only"})

        if any(name == item or name.endswith(f".{item}") for item in download_call_names):
            evidence.append({"line": line, "call": name, "reason": "external_download_call"})

    return evidence[:12]


def _operator_static_field(operator: Any | None, name: str) -> str:
    if operator is None:
        return ""
    if isinstance(operator, dict):
        return str(operator.get(name) or "")
    return str(getattr(operator, name, "") or "")


def _numeric_assignments(code: str, name: str) -> list[int]:
    values: list[int] = []
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_])[\"']?(?:[A-Za-z_]+_)?{name}[\"']?\s*(?:=|:)\s*(?P<value>\d+)",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(code):
        try:
            values.append(int(match.group("value")))
        except Exception:
            continue
    return values


def _has_staged_score_first_sparse_path(code: str) -> dict[str, Any]:
    """Heuristically recognize code that scores one sparse candidate before optional widening.

    The score-first gate should block all-or-nothing broad searches, not strong
    sparse text plans that first finish a bounded trained candidate and only then
    attempt optional siblings or blends. This is deliberately structural and
    task-agnostic: it looks for candidate completion, OOF/local scoring, a later
    optional tier, and a submission write after the completed candidate.
    """
    lower = (code or "").lower()
    completion_markers = (
        "completed_candidates.append",
        "candidate_results.append",
        "results.append",
        "print_candidate_summary",
        "print_candidate_table",
        "selected_candidate = completed_candidates[0]",
        "best_candidate",
    )
    score_markers = (
        "roc_auc_score",
        "log_loss",
        "mean_auc",
        "oof",
        "cross_val",
        "validation_score",
        "cv_score",
    )
    optional_markers = (
        "nbsvm",
        "nb_svm",
        "blend",
        "stack",
        "calibrator",
        "auxiliary",
        "optional",
        "support candidate",
        "second candidate",
    )
    first_completion = min(
        (lower.find(marker) for marker in completion_markers if marker in lower),
        default=-1,
    )
    if first_completion < 0:
        return {"present": False, "reason": "no_candidate_completion_marker"}

    prefix = lower[:first_completion]
    suffix = lower[first_completion:]
    has_scoring_before_completion = any(marker in prefix for marker in score_markers)
    has_optional_after_completion = any(marker in suffix for marker in optional_markers)
    writes_submission_after = "submission.csv" in suffix or ".to_csv(" in suffix
    present = (
        has_scoring_before_completion
        and has_optional_after_completion
        and writes_submission_after
    )
    return {
        "present": present,
        "first_completion_index": first_completion,
        "has_scoring_before_completion": has_scoring_before_completion,
        "has_optional_after_completion": has_optional_after_completion,
        "writes_submission_after": writes_submission_after,
        "reason": "staged_score_first_sparse_path" if present else "incomplete_staged_sparse_path",
    }


def _has_staged_descriptor_score_first_path(code: str) -> dict[str, Any]:
    """Recognize a cheap image/audio descriptor candidate before optional deep media.

    Timeout-recovery code often keeps the expensive CNN/audio route as a later
    optional tier while moving thumbnail/descriptors plus a shallow model to the
    front. Function definitions make whole-file token order misleading, so this
    check inspects the executable `main()` tail when present.
    """
    lower = (code or "").lower()
    main_index = lower.rfind("def main")
    exec_region = lower[main_index:] if main_index >= 0 else lower

    descriptor_markers = (
        "run_descriptor_portfolio(",
        "run_descriptor_candidate",
        "descriptor_extratrees_scorefirst",
        "descriptor score-first",
        "score-first descriptor",
        "descriptor_order",
        "descriptor_image_size",
        "descriptor_classifier",
        "descriptor_regressor",
        "extract_feature_matrix",
        "extract_features_from_image",
        "extract_descriptor_features",
        "train_thumbnail_candidate",
        "thumbnail_candidate",
        "thumb_ridge",
        "feature-progress",
    )
    deep_markers = (
        "run_cnn_candidate",
        "train_cnn_candidate",
        "effv2_dualhead",
        "for candidate in cnn_candidates",
        "run_audio_cnn_candidate",
        "for candidate in deep_candidates",
    )
    completion_markers = (
        "completed_results, best_result, fallback_name",
        "best_result, fallback_name",
        "all_results.append(descriptor",
        "candidates.append(thumb_candidate",
        "current_best = thumb_candidate",
        "score-first thumbnail",
        "best_candidate = choose_best_candidate",
        "best_candidate is not none",
        "tracker.update",
        "tracker.finalize",
    )
    submission_markers = (
        "write_submission",
        "finalize_and_exit",
        "submission.csv",
    )
    descriptor_pos = min(
        (exec_region.find(marker) for marker in descriptor_markers if marker in exec_region),
        default=-1,
    )
    deep_pos = min(
        (exec_region.find(marker) for marker in deep_markers if marker in exec_region),
        default=-1,
    )
    has_descriptor_model = any(token in lower for token in (
        "extratrees",
        "randomforest",
        "histgradientboosting",
        "ridge",
        "elasticnet",
        "logisticregression",
        "svc",
    ))
    has_descriptor_features = any(token in lower for token in (
        "descriptor",
        "thumbnail",
        "brightness",
        "blur",
        "color",
        "hash",
        "dhash",
        "image features",
    ))
    has_completion = any(marker in exec_region for marker in completion_markers)
    has_submission = any(marker in exec_region for marker in submission_markers)
    present = (
        descriptor_pos >= 0
        and (deep_pos < 0 or descriptor_pos < deep_pos)
        and has_descriptor_model
        and has_descriptor_features
        and has_completion
        and has_submission
    )
    return {
        "present": present,
        "descriptor_pos": descriptor_pos,
        "deep_pos": deep_pos,
        "has_descriptor_model": has_descriptor_model,
        "has_descriptor_features": has_descriptor_features,
        "has_completion": has_completion,
        "has_submission": has_submission,
        "reason": "staged_descriptor_score_first_path" if present else "no_descriptor_score_first_path",
    }


def _full_media_feature_pass_before_score_report(code: str) -> dict[str, Any]:
    """Detect full train/test media feature extraction before any scored candidate.

    Thumbnail/descriptor paths are good score-first routes only if they are
    bounded enough to finish before the first submission. A low image size does
    not help when the script still decodes every media file before training the
    first candidate.
    """
    lower = (code or "").lower()
    main_index = lower.rfind("def main")
    exec_region = lower[main_index:] if main_index >= 0 else lower
    score_markers = (
        "train_candidate(",
        ".fit(",
        "completed_results.append",
        "best_result",
        "current_best",
        "tracker.update",
        "write_submission",
        "submission.to_csv",
    )
    first_score_pos = min(
        (exec_region.find(marker) for marker in score_markers if marker in exec_region),
        default=-1,
    )
    full_pass_patterns = (
        ("extract_features_train_ids", r"\bextract\w*features\([^)\n]*train_ids"),
        ("extract_features_test_ids", r"\bextract\w*features\([^)\n]*test_ids"),
        ("extract_core_train_ids", r"\bextract_core_features\([^)\n]*train_ids"),
        ("extract_core_test_ids", r"\bextract_core_features\([^)\n]*test_ids"),
        ("feature_matrix_train_ids", r"\b(?:build|make|compute|extract)\w*feature\w*\([^)\n]*train_ids"),
        ("feature_matrix_test_ids", r"\b(?:build|make|compute|extract)\w*feature\w*\([^)\n]*test_ids"),
    )
    matches: list[dict[str, Any]] = []
    for name, pattern in full_pass_patterns:
        match = re.search(pattern, exec_region)
        if match:
            matches.append({"kind": name, "pos": match.start(), "snippet": exec_region[match.start():match.end()]})
    before_score = [
        item for item in matches
        if first_score_pos < 0 or int(item["pos"]) < first_score_pos
    ]
    if not before_score:
        return {"present": False, "reason": "no_full_media_feature_pass_before_score", "matches": matches[:4]}
    first = min(before_score, key=lambda item: int(item["pos"]))
    pos = int(first["pos"])
    local_window = exec_region[max(0, pos - 450):pos + 450]
    bounded_tokens = (
        "sample_train_ids",
        "sampled_train_ids",
        "train_sample_ids",
        "subset_train_ids",
        "small_train_ids",
        "max_train_images",
        "max_train_files",
        "max_train_rows",
        "train_limit",
        "train_ids[:",
        "test_ids[:",
        ".sample(",
        ".head(",
        "stratifiedshufflesplit",
    )
    bounded = any(token in local_window for token in bounded_tokens)
    return {
        "present": not bounded,
        "reason": (
            "full_media_feature_pass_before_first_score"
            if not bounded else "bounded_media_feature_pass_before_first_score"
        ),
        "first_score_pos": first_score_pos,
        "first_match": first,
        "matches": before_score[:4],
        "bounded": bounded,
    }


def _score_first_envelope_report(
    code: str,
    operator: Any | None,
    search_state: str | None,
    *,
    strict_score_first_required: bool = False,
) -> dict[str, Any]:
    """Detect high-cost first paths that can spend the whole round before any score.

    If the first executable route starts with full-cost vectorization,
    image/audio preprocessing, or multi-candidate heavy training, the sandbox
    can spend the whole external timeout before producing a score. This check
    is intentionally modality-based rather than task-name based.
    """
    lower = (code or "").lower()
    op_cost = _operator_static_field(operator, "cost").lower()
    op_text = " ".join(
        _operator_static_field(operator, field)
        for field in ("name", "intent", "family", "description", "source")
    ).lower()
    state = str(search_state or "").lower()
    early_state = state in {
        "",
        "portfolio_seed",
        "frontload",
        "frontload_draft",
        "fresh_draft",
        "debug_repair",
        "timeout_trap",
        "score_first_timeout_recovery",
    } or bool(strict_score_first_required)

    high_cost_hint = (
        op_cost == "high"
        or any(token in op_text for token in (
            "cnn",
            "efficientnet",
            "resnet",
            "convnext",
            "vit",
            "image",
            "audio",
            "spectrogram",
            "transformer",
            "tfidf",
            "sparse",
            "gbdt",
            "lightgbm",
            "xgboost",
            "catboost",
        ))
        or any(token in lower for token in (
            "tfidfvectorizer",
            "countvectorizer",
            "torch.utils.data",
            "dataloader",
            "timm.create_model",
            "torchvision",
            "tensorflow",
            "keras",
            "cv2.imread",
            "librosa.load",
            "lgb.train",
            "xgb.train",
            "catboost",
        ))
    )
    if not high_cost_hint:
        return {"status": "pass", "evidence": [], "reason": "not_high_cost_runtime_round"}

    evidence: list[dict[str, Any]] = []
    mitigations: list[dict[str, Any]] = []
    max_features = _numeric_assignments(code, "max_features")
    total_max_features = sum(value for value in max_features if value > 0)
    candidate_spec_count = len(re.findall(r"\b(?:CandidateSpec|CandidateConfig)\s*\(", code))
    has_cv = any(token in lower for token in (
        "stratifiedkfold",
        "kfold",
        "groupkfold",
        "cross_val",
        "n_splits",
        "folds_run",
    ))
    if "tfidfvectorizer" in lower or "countvectorizer" in lower:
        sparse_stage = _has_staged_score_first_sparse_path(code)
        if sparse_stage.get("present") and total_max_features >= 450000 and has_cv:
            mitigations.append({
                "kind": "sparse_text_large_features_but_staged_score_first",
                "total_max_features": total_max_features,
                "max_features": max_features[:8],
                "candidate_specs": candidate_spec_count,
                "stage": sparse_stage,
            })
        elif total_max_features >= 450000 and has_cv:
            evidence.append({
                "kind": "sparse_text_oversized_first_cv",
                "total_max_features": total_max_features,
                "max_features": max_features[:8],
                "candidate_specs": candidate_spec_count,
            })
        elif candidate_spec_count >= 3 and total_max_features >= 300000:
            evidence.append({
                "kind": "sparse_text_broad_candidate_table_before_score",
                "total_max_features": total_max_features,
                "candidate_specs": candidate_spec_count,
            })

    image_sizes = _numeric_assignments(code, "image_size")
    epochs = _numeric_assignments(code, "epochs")
    has_deep_media_code = any(token in lower for token in (
        "torch.utils.data",
        "dataloader",
        "timm.create_model",
        "torchvision",
        "tensorflow",
        "keras",
        "cv2.imread",
        "pil.image",
        "librosa.load",
        "torchaudio",
    ))
    full_data_prescan = any(token in lower for token in (
        "discover_duplicate_groups",
        "duplicate_hash_scan",
        "compute_dhash",
        "perceptual hash",
        "full-data",
        "full data",
        "embedding extraction",
        "extract_embeddings",
    ))
    unbounded_recursive_data_scan = any(token in lower for token in (
        "os.walk(data_dir",
        "os.walk(str(data_dir",
        "os.walk(data_root",
    ))
    native_directory_scan = (
        "def scan_data_dir" in lower
        and any(token in lower for token in (
            "os.scandir(",
            "os.walk(",
        ))
    )
    bounded_scan_markers = any(token in lower for token in (
        "max_scan",
        "max_files",
        "scan_limit",
        "top-level",
        "shallow",
        "glob_depth",
    ))
    if has_deep_media_code:
        descriptor_stage = _has_staged_descriptor_score_first_path(code)
        media_full_pass = _full_media_feature_pass_before_score_report(code)
        if unbounded_recursive_data_scan and early_state and not bounded_scan_markers:
            evidence.append({
                "kind": "deep_media_unbounded_recursive_data_scan_before_score",
                "markers": [
                    token for token in (
                        "os.walk(data_dir",
                        "os.walk(data_root",
                    )
                    if token in lower
                ],
            })
        if native_directory_scan and early_state:
            evidence.append({
                "kind": "deep_media_native_directory_scan_before_score",
                "markers": [
                    token for token in ("os.scandir(", "os.walk(") if token in lower
                ],
                "guidance": "prefer CSV-first schema discovery and known train/test media directories before native recursive scans",
            })
        if full_data_prescan and early_state:
            markers = [
                token for token in (
                    "discover_duplicate_groups",
                    "duplicate_hash_scan",
                    "compute_dhash",
                    "extract_embeddings",
                )
                if token in lower
            ]
            if descriptor_stage.get("present"):
                mitigations.append({
                    "kind": "deep_media_prescan_is_descriptor_score_first",
                    "markers": markers,
                    "stage": descriptor_stage,
                })
            else:
                evidence.append({
                    "kind": "deep_media_full_data_prescan_before_score",
                    "markers": markers,
                })
        strict_score_first_context = (
            bool(strict_score_first_required)
            or "score_first_timeout_recovery" in op_text
            or state in {"timeout_trap", "score_first_timeout_recovery"}
        )
        if (
            early_state
            and media_full_pass.get("present")
            and strict_score_first_context
        ):
            evidence.append({
                "kind": "deep_media_full_dataset_descriptor_before_score",
                "reason": "full train/test media feature extraction happens before the first trained candidate/submission in a strict score-first context",
                "stage": descriptor_stage,
                "full_pass": media_full_pass,
            })
        if image_sizes and epochs and max(image_sizes) >= 384 and max(epochs) >= 4 and early_state:
            if descriptor_stage.get("present"):
                mitigations.append({
                    "kind": "deep_media_heavy_candidate_after_descriptor_score_first",
                    "max_image_size": max(image_sizes),
                    "max_epochs": max(epochs),
                    "candidate_specs": candidate_spec_count,
                    "stage": descriptor_stage,
                })
            else:
                evidence.append({
                    "kind": "deep_media_heavy_first_candidate",
                    "max_image_size": max(image_sizes),
                    "max_epochs": max(epochs),
                    "candidate_specs": candidate_spec_count,
                })
        if "use_tta=True" in code and early_state and (max(epochs or [0]) >= 3 or max(image_sizes or [0]) >= 384):
            evidence.append({
                "kind": "deep_media_tta_before_first_score",
                "max_image_size": max(image_sizes or [0]),
                "max_epochs": max(epochs or [0]),
            })

    estimators = _numeric_assignments(code, "n_estimators")
    has_tree_ensemble = any(token in lower for token in ("lgbm", "lightgbm", "xgboost", "xgb.", "catboost", "randomforest", "extratrees"))
    if has_tree_ensemble and estimators and max(estimators) >= 500 and candidate_spec_count >= 2 and early_state:
        evidence.append({
            "kind": "tree_ensemble_broad_expensive_first_table",
            "max_estimators": max(estimators),
            "candidate_specs": candidate_spec_count,
        })

    return {
        "status": "block" if evidence else "pass",
        "evidence": evidence[:8],
        "mitigations": mitigations[:8],
        "reason": (
            "first scoring path appears too expensive for a no-score/high-cost runtime round"
            if evidence else "no oversized first-score path detected"
        ),
        "search_state": state,
        "strict_score_first_required": bool(strict_score_first_required),
    }


def _integer_literal(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return int(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
        and not isinstance(node.operand.value, bool)
    ):
        value = int(node.operand.value)
        return -value if isinstance(node.op, ast.USub) else value
    return None


def _identifier_tokens(name: str) -> set[str]:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name or ""))
    return {token for token in re.split(r"[^a-z0-9]+", snake.lower()) if token}


def _looks_like_fixed_data_cardinality_name(name: str) -> bool:
    tokens = _identifier_tokens(name)
    if tokens & {"max", "min", "limit", "cap", "threshold", "budget", "batch"}:
        return False
    if tokens & {"row", "rows", "nrow", "nrows"}:
        return True
    data_terms = {
        "train", "test", "submission", "dataset", "data", "record", "records",
        "file", "files", "image", "images",
    }
    count_terms = {"n", "num", "number", "count", "length", "size", "total", "expected"}
    return bool(tokens & data_terms and tokens & count_terms)


def _assigned_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for item in target.elts for name in _assigned_names(item)]
    return []


def _looks_like_data_cardinality_expression(node: ast.AST) -> bool:
    value: ast.AST | None = None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len" and node.args:
        value = node.args[0]
    elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "shape":
        if _integer_literal(node.slice) == 0:
            value = node.value.value
    if value is None:
        return False
    try:
        text = ast.unparse(value)
    except Exception:
        text = ""
    tokens = _identifier_tokens(text)
    return bool(tokens & {
        "train", "test", "submission", "sample", "data", "dataset", "df",
        "frame", "rows", "records", "files", "images", "x", "y",
    })


def _detect_hardcoded_data_cardinality_evidence(code: str) -> list[dict[str, Any]]:
    """Find exact dataset-size assumptions without flagging ordinary ML hyperparameters."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    minimum_cardinality = 10_000
    evidence: list[dict[str, Any]] = []

    def add(*, node: ast.AST, kind: str, name: str, value: int) -> None:
        evidence.append({
            "line": getattr(node, "lineno", None),
            "kind": kind,
            "name": name,
            "value": value,
        })

    for node in ast.walk(tree):
        assignment_targets: list[ast.AST] = []
        assignment_value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            assignment_targets = list(node.targets)
            assignment_value = node.value
        elif isinstance(node, ast.AnnAssign):
            assignment_targets = [node.target]
            assignment_value = node.value
        if assignment_value is not None:
            value = _integer_literal(assignment_value)
            if value is not None and abs(value) >= minimum_cardinality:
                for target in assignment_targets:
                    for name in _assigned_names(target):
                        if _looks_like_fixed_data_cardinality_name(name):
                            add(node=node, kind="fixed_cardinality_assignment", name=name, value=value)

        if isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values):
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    continue
                value = _integer_literal(value_node)
                if (
                    value is not None
                    and abs(value) >= minimum_cardinality
                    and _looks_like_fixed_data_cardinality_name(key_node.value)
                ):
                    add(
                        node=value_node,
                        kind="fixed_cardinality_mapping",
                        name=key_node.value,
                        value=value,
                    )

        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for index, operator in enumerate(node.ops):
                if not isinstance(operator, (ast.Eq, ast.NotEq)):
                    continue
                left, right = operands[index], operands[index + 1]
                for expression, literal in ((left, right), (right, left)):
                    value = _integer_literal(literal)
                    if (
                        value is not None
                        and abs(value) >= minimum_cardinality
                        and _looks_like_data_cardinality_expression(expression)
                    ):
                        add(
                            node=node,
                            kind="exact_cardinality_comparison",
                            name=ast.unparse(expression),
                            value=value,
                        )

    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in evidence:
        key = (item.get("line"), item.get("kind"), item.get("name"), item.get("value"))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:12]


def inspect_solution_contract(
    code: str,
    *,
    search_operator: Any | None = None,
    search_state: str | None = None,
    strict_score_first_required: bool = False,
) -> dict[str, Any]:
    """Static contract gate before externally timed sandbox validation."""
    lower = code.lower()
    hardcoded_path_patterns = (
        "/hpc_data/",
        "/mnt/pubdatasets2/MLE-Bench-val",
        "/mnt/pubdatasets2/automized_std_bench",
        "/mnt/local_sandbox_workdir",
    )
    hardcoded_data_cardinality_evidence = _detect_hardcoded_data_cardinality_evidence(code)
    constant_output = any(re.search(pattern, lower, flags=re.DOTALL) for pattern in (
        r"np\.full\s*\([\s\S]{0,240},\s*(?:0(?:\.0+)?|0\.5|1(?:\.0+)?)",
        r"submission\s*\[[^\]]+\]\s*=\s*(?:0(?:\.0+)?|0\.5|1(?:\.0+)?)",
        r"submission\.[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:0(?:\.0+)?|0\.5|1(?:\.0+)?)",
    ))
    has_training_call = any(token in lower for token in (
        ".fit(",
        " fit(",
        "train(",
        "lgb.train",
        "catboost",
        "xgboost",
        "torch",
        "tensorflow",
        "keras",
    ))
    untrained_constant_submission = constant_output and "submission.csv" in lower and not has_training_call
    ambiguous_sample_column_class_inference = bool(re.search(
        r"sample(?:_submission|_df|submission)?\s*\.\s*columns\s*\[\s*1\s*:\s*\]",
        lower,
    ))
    side_output_evidence = _detect_side_output_file_evidence(code)
    creates_side_output_files = bool(side_output_evidence)
    external_download_evidence = _detect_external_download_evidence(code)
    uses_external_downloads = bool(external_download_evidence)
    score_first_envelope = _score_first_envelope_report(
        code,
        search_operator,
        search_state,
        strict_score_first_required=strict_score_first_required,
    )
    has_fast_score_first_envelope = score_first_envelope.get("status") != "block"
    checks = {
        "uses_data_dir_env": "DATA_DIR" in code and "os.environ" in code,
        "writes_submission_csv": "submission.csv" in code,
        "mentions_sample_submission": "sample_submission" in code.lower(),
        "has_dependency_fallback": any(token in code for token in ("ImportError", "ModuleNotFoundError", "try:", "except ImportError")),
        "has_output_validation": any(token in code.lower() for token in ("validate", "assert", "columns", "shape")),
        "has_resource_downgrade_hint": any(token in code.lower() for token in ("fallback", "sample", "n_estimators", "epochs", "timeout", "memory")),
        "no_known_hardcoded_paths": not any(pattern in code for pattern in hardcoded_path_patterns),
        "avoids_hardcoded_data_cardinality": not hardcoded_data_cardinality_evidence,
        "avoids_untrained_constant_submission": not untrained_constant_submission,
        "avoids_ambiguous_sample_column_class_inference": not ambiguous_sample_column_class_inference,
        "avoids_side_output_files": not creates_side_output_files,
        "avoids_external_downloads": not uses_external_downloads,
        "has_fast_score_first_envelope": has_fast_score_first_envelope,
    }
    missing = [name for name, ok in checks.items() if not ok]
    hard_blocker_names = (
        "uses_data_dir_env",
        "writes_submission_csv",
        "no_known_hardcoded_paths",
        "avoids_hardcoded_data_cardinality",
        "avoids_untrained_constant_submission",
        "avoids_side_output_files",
        "avoids_external_downloads",
    )
    blockers = [
        name for name in (
            *hard_blocker_names,
        )
        if not checks[name]
    ]
    score_first_hard_required = (
        bool(strict_score_first_required)
        or "score_first_timeout_recovery" in " ".join(
            _operator_static_field(search_operator, field)
            for field in ("name", "intent", "family", "description", "source")
        ).lower()
        or str(search_state or "").lower() in {"timeout_trap", "score_first_timeout_recovery"}
    )
    soft_warnings = [name for name in missing if name not in blockers]
    return {
        "checks": checks,
        "missing": missing,
        "blockers": blockers,
        "soft_warnings": soft_warnings,
        "gate_policy": {
            "mode": "hard_format_safety_only",
            "hard_blocker_names": list(hard_blocker_names),
            "soft_warning_names": soft_warnings,
            "score_first_hard_required_by_scheduler": bool(score_first_hard_required),
            "reason": (
                "Static workload size and score-first ordering are diagnostics, not internal-deadline requirements. "
                "They should not consume a modeling round through static-gate repair "
                "unless a hard submission, path, download, side-output, constant-output, or fixed data-cardinality issue is present."
            ),
        },
        "side_output_evidence": side_output_evidence[:5],
        "external_download_evidence": external_download_evidence[:5],
        "hardcoded_data_cardinality_evidence": hardcoded_data_cardinality_evidence,
        "score_first_envelope": score_first_envelope,
        "submission_eligible": not blockers,
        "status": "pass" if not missing else ("block" if blockers else "warn"),
    }


async def repair_static_gate_failure(
    work_dir: Path,
    prompt_messages: list[dict[str, str]],
    metadata: dict[str, Any],
    model: str,
    reasoning_level: str,
    max_tokens: int,
    temperature: float,
    trace_file: Path,
    refinement_context: str | None,
    skill_context: str | None,
    code: str,
    solution_contract: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Give Codex one focused retry to repair static gate blockers before sandbox spend."""
    solution_file = work_dir / "solution.py"
    if not solution_file.exists():
        solution_file.write_text(code, encoding="utf-8")
    current_code = solution_file.read_text(encoding="utf-8", errors="replace")

    def restore_current_solution() -> None:
        try:
            on_disk = solution_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            on_disk = None
        if on_disk != current_code:
            solution_file.write_text(current_code, encoding="utf-8")

    branch = str(metadata.get("branch") or "").strip().lower()
    lineage_guard = (
        "[DRAFT REPAIR LINEAGE GUARD]\n"
        "This is a blocker-only repair of the current round, not a new seed selection step. "
        "The complete current-round solution.py in the task root is the only implementation base. "
        "Inspect and edit that file directly. Do not inspect, copy, or reconstruct from commits/, refs/, "
        "memory cards, prior-draft code, incumbent code, or other historical implementations. Preserve the "
        "current method family, feature route, validation design, and candidate structure; change only what "
        "is necessary for the listed hard safety blockers."
        if branch == "draft"
        else (
            "[CURRENT SOLUTION REPAIR GUARD]\n"
            "The complete current-round solution.py in the task root is the authoritative implementation base. "
            "Inspect and edit that file directly; do not reconstruct the solution from prompt excerpts or "
            "unrelated historical implementations. Preserve the modeling route and change only what is necessary "
            "for the listed hard safety blockers."
        )
    )
    gate_context = "\n\n".join([
        refinement_context or "",
        "[STATIC GATE FAILURE - REPAIR BEFORE VALIDATION]",
        json.dumps(solution_contract, indent=2, ensure_ascii=False),
        lineage_guard,
        "Edit the existing root solution.py to fix these blockers without broad method changes.",
        (
            "Only entries in solution_contract.blockers are repair targets. Do not change code to address "
            "solution_contract.missing or solution_contract.soft_warnings during this repair. "
            "Hard requirements: DATA_DIR-only loading, no hardcoded local paths or public row constants, "
            "sample_submission alignment when available, output validation, and no untrained constant/sample-template "
            "emergency submission when data, labels, targets, or submission units cannot be parsed. "
            "Name discovered DATA_DIR inputs as input_paths/data_files/source_files, not as reusable side-output buckets. "
            "Do not write side files for reusable predictions, models, fold dumps, or later-round blending; "
            "print diagnostics to stdout and write only submission.csv."
        ),
    ])
    try:
        response_text, usage = await call_codex_cli(
            work_dir=work_dir,
            prompt_messages=prompt_messages,
            metadata=metadata,
            system_prompt=SYSTEM_PROMPT,
            model=model,
            reasoning_level=reasoning_level,
            max_tokens=max_tokens,
            temperature=temperature,
            trace_file=trace_file,
            refinement_context=gate_context,
            skill_context=skill_context,
            phase_name="static_gate_repair",
        )
    except CodexCliError as exc:
        if exc.failure_type == "llm_cli_timeout" and solution_file.exists():
            repaired = solution_file.read_text(encoding="utf-8", errors="replace")
            if repaired != current_code and len(repaired.strip()) > 100:
                try:
                    ast.parse(repaired)
                except SyntaxError:
                    restore_current_solution()
                    raise
                usage = dict(exc.usage or {})
                usage["salvaged_solution_after_timeout"] = True
                logger.warning(
                    "Static gate repair timed out, but solution.py was written and parsed; "
                    "continuing with normal static validation."
                )
                return repaired, "[STATIC GATE REPAIR TIMEOUT: salvaged written solution.py]", usage
        restore_current_solution()
        raise
    except Exception:
        restore_current_solution()
        raise
    if solution_file.exists():
        repaired = solution_file.read_text(encoding="utf-8")
        if repaired != current_code and len(repaired.strip()) > 100:
            return repaired, response_text, usage
    extracted = extract_code(response_text)
    if extracted and extracted != current_code and len(extracted.strip()) > 100:
        solution_file.write_text(extracted, encoding="utf-8")
        return extracted, response_text, usage
    restore_current_solution()
    return current_code, response_text, usage


async def call_codex_round_summary(
    work_dir: Path,
    metadata: dict[str, Any],
    round_num: int,
    solution_code: str,
    validation_feedback: str,
    validation_status: str,
    validation_score: float | None,
    model: str,
    reasoning_level: str,
    trace_file: Path | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Ask Codex for brief method/result notes before archiving a commit."""
    work_dir.mkdir(parents=True, exist_ok=True)

    score_text = f"{validation_score:.6f}" if validation_score is not None else "N/A"
    prompt = f"""
You are summarizing one completed ML benchmark attempt for future search.
Do not create, edit, or delete files. Only print compact JSON.

Return exactly this JSON object:
{{
  "method_summary": "one short sentence describing the current round's method",
  "method_profile": "2-4 dense English sentences describing the method's model class, feature/representation strategy, validation or fallback design, runtime/resource tradeoffs, and the main risk or reuse hook",
  "result_reflection": "one short sentence reflecting on the current round's result and next implication",
  "method_family": "short stable identifier such as tfidf_logreg, efficientnet_cv, lightgbm_tabular, rule_router, residual_unet",
  "core_components": ["3-8 short component names that define the method"],
  "novelty_vs_best": "one short sentence describing what changed versus best_local_cv, or none"
}}

Keep values concise, factual, English-only, and useful for future branch scheduling. Avoid over-indexing on the score alone.

Task: {metadata.get("task_name", "unknown")}
Round: {round_num + 1}
Higher is better: {metadata.get("higher_is_better", "unknown")}
Validation status: {validation_status}
Validation score: {score_text}

[SOLUTION.PY]
{_truncate_text(solution_code, 12000)}

[VALIDATION FEEDBACK]
{_truncate_text(validation_feedback, 6000)}
""".strip()

    cmd = [
        "codex",
        "exec",
        "--full-auto",
        "--ephemeral",
        "--skip-git-repo-check",
        "--model", model,
        "-c", f"reasoning_level={json.dumps(reasoning_level)}",
    ]

    start_time = datetime.now()
    trace_data = {
        "timestamp": start_time.isoformat(),
        "model": model,
        "reasoning_level": reasoning_level,
        "work_dir": str(work_dir),
        "task_name": metadata.get("task_name", "unknown"),
        "round": round_num,
        "prompt": prompt,
        "cmd": cmd,
        "response_text": "",
        "stderr": "",
        "return_code": None,
        "usage": {},
        "duration_seconds": 0,
    }

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(work_dir),
        env=dict(os.environ),
    )
    stdout, stderr = await proc.communicate(input=prompt.encode("utf-8"))

    response_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    usage = {
        "input_tokens": len(prompt) // 4,
        "output_tokens": len(response_text) // 4,
    }

    end_time = datetime.now()
    trace_data["response_text"] = response_text
    trace_data["stderr"] = stderr_text
    trace_data["return_code"] = proc.returncode
    trace_data["usage"] = usage
    trace_data["duration_seconds"] = (end_time - start_time).total_seconds()
    trace_data["end_timestamp"] = end_time.isoformat()

    if trace_file:
        trace_file.parent.mkdir(parents=True, exist_ok=True)
        trace_file.write_text(json.dumps(trace_data, indent=2, ensure_ascii=False), encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(f"Codex summary call failed with code {proc.returncode}: {stderr_text[:500]}")

    return _parse_round_summary(response_text), usage


async def update_memory_after_round(
    task_dir: Path,
    metadata: dict[str, Any],
    round_num: int,
    commit_hash: str,
    branch: str,
    planning_text: str,
    solution_code: str,
    validation_feedback: str,
    validation_status: str,
    validation_score: float | None,
    round_summary: dict[str, str],
    model: str,
    reasoning_level: str,
) -> dict[str, Any]:
    """Retired legacy LLM memory writer.

    The active design writes token-free runtime memory into `memory_bank/`
    through `write_local_memory_after_round()` and round cards/diffs through
    `write_round_memory_artifacts()`. Keeping this no-op wrapper avoids
    accidental recreation of the retired legacy per-task Markdown tree if a
    stale caller is reintroduced.
    """
    return {
        "status": "retired_legacy_memory_writer",
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "memory_bank_dir": str(memory_bank_dir(task_dir)),
    }


def extract_validation_log_diagnostics(feedback: str, validation_score: float | None) -> dict[str, Any]:
    """Extract compact model-selection evidence from validation stdout."""
    text = str(feedback or "")
    selected = ""
    local_metric_name = ""
    selected_local_score: float | None = None
    best_local_score: float | None = None
    evidence_lines: list[str] = []
    support_lines: list[str] = []

    selected_patterns = (
        r"\[selected[-_ ]final\]\s*(?P<name>[A-Za-z0-9_.+-]+)",
        r"\[selected[-_ ]summary\][^\n]*\bfinal_candidate\s*[=:]\s*(?P<name>[A-Za-z0-9_.+-]+)",
        r"\bfinal_candidate\s*[=:]\s*(?P<name>[A-Za-z0-9_.+-]+)",
        r"\bselected(?:_final|[-_ ]final|_final_candidate|[-_ ]final[-_ ]candidate|_candidate)?\s*(?:candidate|name)?\s*[=:]\s*(?P<name>[A-Za-z0-9_.+-]+)",
        r"\[selected\]\s*candidate=(?P<name>[A-Za-z0-9_.+-]+)",
        r"selected_candidate\s+name=(?P<name>[A-Za-z0-9_.+-]+)",
    )
    for pattern in selected_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            selected = match.group("name")
            break

    score_patterns = (
        ("oof_auc", True, r"\b(?:global|final|selected)[-_]?oof[_ -]?auc\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("oof_auc", True, r"\boof[_ -]?auc\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("local_auc", True, r"\blocal[_ -]?auc\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("cv_auc", True, r"\bcv[_ -]?auc\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("mean_auc", True, r"\bmean[_ -]?auc\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("flattened_auc", True, r"\bflattened[_ -]?auc\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("qwk", True, r"\bqwk\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("oof_logloss", False, r"\boof[_ -]?log(?:_|[- ])?loss\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("logloss", False, r"\blog(?:_|[- ])?loss\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("oof_loss", False, r"\boof[_ -]?loss\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("cv_loss", False, r"\bcv[_ -]?loss\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("oof_score", True, r"\boof[_ -]?score\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
        ("cv_score", True, r"\bcv[_ -]?score\s*[=:]\s*(?P<score>-?\d+(?:\.\d+)?)"),
    )
    lower_is_better_metrics = {"oof_logloss", "logloss", "oof_loss", "cv_loss"}
    candidate_scores: list[tuple[str, float, str, bool]] = []
    candidate_names: list[str] = []

    def add_candidate_name(name: str | None) -> None:
        clean = str(name or "").strip()
        if not clean or len(clean) > 120:
            return
        if clean.lower() in {"candidate", "name", "selected", "final"}:
            return
        if clean not in candidate_names:
            candidate_names.append(clean)

    if selected:
        add_candidate_name(selected)

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip())
        if not line:
            continue
        lower = line.lower()
        support_marker = any(
            token in lower
            for token in (
                "[fold-support]",
                "[fold-summary]",
                "fold_support",
                "fold-summary",
                "fold_counts",
                "fold count",
                "fold_count",
                "fold sizes",
                "fold_size",
                "fold_rows",
                "label_support",
                "class_support",
                "positive_support",
                "positive_counts",
                "class_counts",
                "label_counts",
                "n_pos",
                "positives",
                "zero_positive",
                "empty_fold",
                "stratification",
                "stratified",
            )
        )
        if support_marker and any(
            anchor in lower
            for anchor in ("fold", "support", "positive", "label", "class", "stratif", "count", "size")
        ):
            if len(support_lines) < 6:
                support_lines.append(line[:240])
        order_match = re.search(r"candidate[-_ ]order\s*[=:]\s*(?P<value>\[[^\]]+\])", line, flags=re.IGNORECASE)
        if order_match:
            try:
                parsed_order = ast.literal_eval(order_match.group("value"))
            except Exception:
                parsed_order = []
            if isinstance(parsed_order, list):
                for item in parsed_order:
                    add_candidate_name(str(item))
        for name_pattern in (
            r"\bCANDIDATE\s+name=(?P<name>[A-Za-z0-9_.:+-]+)",
            r"\bcandidate_name=(?P<name>[A-Za-z0-9_.:+-]+)",
            r"\bcandidate=(?P<name>[A-Za-z0-9_.:+-]+)",
            r"\bselected_final_candidate=(?P<name>[A-Za-z0-9_.:+-]+)",
        ):
            name_match = re.search(name_pattern, line, flags=re.IGNORECASE)
            if name_match:
                add_candidate_name(name_match.group("name"))
        if not any(token in lower for token in ("candidate", "selected", "oof", "cv_", "qwk", "blend", "stack")):
            continue
        is_fold_only_score = (
            "fold-score" in lower
            or bool(re.search(r"\bfold\s*[=:]\s*\d+", lower))
            or bool(re.search(r"\bfold_\d+\b", lower))
        )
        comparison_match = re.match(
            r"(?P<name>[A-Za-z0-9_.+-]+)\s+(?P<family>[A-Za-z0-9_.+-]+)\s+(?P<score>-?\d+(?:\.\d+)?)\b",
            line,
        )
        if comparison_match and "fold_scores" in lower and "candidate " not in lower:
            name = comparison_match.group("name")
            family = comparison_match.group("family").lower()
            if family not in {"family", "candidate"}:
                try:
                    value = float(comparison_match.group("score"))
                except Exception:
                    value = None
                if value is not None:
                    add_candidate_name(name)
                    metric_name = "oof_logloss" if "logloss" in text.lower() else "candidate_score"
                    higher_is_better = metric_name not in lower_is_better_metrics
                    candidate_scores.append((metric_name, value, name, higher_is_better))
                    if len(evidence_lines) < 8:
                        evidence_lines.append(line[:240])
        pipe_table_match = re.search(
            r"\[candidate[-_ ]table\]\s*\*?\s*(?P<name>[A-Za-z0-9_.+-]+)\s*\|\s*(?P<score>-?\d+(?:\.\d+)?)\s*\|",
            line,
            flags=re.IGNORECASE,
        )
        if pipe_table_match:
            try:
                value = float(pipe_table_match.group("score"))
            except Exception:
                value = None
            if value is not None:
                name = pipe_table_match.group("name")
                add_candidate_name(name)
                metric_name = "oof_auc" if "auc" in lower else "candidate_score"
                higher_is_better = metric_name not in lower_is_better_metrics
                candidate_scores.append((metric_name, value, name, higher_is_better))
                if len(evidence_lines) < 8:
                    evidence_lines.append(line[:240])
        for metric_name, higher_is_better, pattern in score_patterns:
            for match in re.finditer(pattern, line, flags=re.IGNORECASE):
                try:
                    value = float(match.group("score"))
                except Exception:
                    continue
                if is_fold_only_score:
                    if len(evidence_lines) < 8:
                        evidence_lines.append(line[:240])
                    continue
                name = ""
                name_match = re.search(
                    r"(?:candidate|name)\s*[=:]\s*(?P<name>[A-Za-z0-9_.+-]+)",
                    line,
                    flags=re.IGNORECASE,
                )
                if not name_match:
                    name_match = re.match(r"(?P<name>[A-Za-z0-9_.+-]+)\s+", line)
                if name_match:
                    name = name_match.group("name")
                    add_candidate_name(name)
                candidate_scores.append((metric_name, value, name, higher_is_better))
                if len(evidence_lines) < 8:
                    evidence_lines.append(line[:240])

    if candidate_scores:
        primary_metric = ""
        if selected:
            for metric_name, _value, name, _higher_is_better in candidate_scores:
                if name and name.lower() == selected.lower():
                    primary_metric = metric_name
                    break
        if not primary_metric:
            metric_counts = Counter(metric_name for metric_name, _value, _name, _higher in candidate_scores)
            primary_metric = metric_counts.most_common(1)[0][0]
        primary_scores = [item for item in candidate_scores if item[0] == primary_metric]
        higher_is_better = primary_scores[0][3] if primary_scores else True
        key_fn = (lambda item: item[1]) if higher_is_better else (lambda item: -item[1])
        metric_name, value, _name, _higher_is_better = max(primary_scores, key=key_fn)
        best_local_score = value
        local_metric_name = metric_name
        if selected:
            selected_matches = [
                (m, v, n, h) for m, v, n, h in candidate_scores
                if n.lower() == selected.lower()
            ]
            if selected_matches:
                _m, selected_local_score, _n, _h = max(selected_matches, key=key_fn)
        if selected_local_score is None and len(candidate_scores) == 1:
            selected_local_score = candidate_scores[0][1]

    local_validation_gap = None
    large_gap = False
    if validation_score is not None and best_local_score is not None:
        try:
            if local_metric_name in lower_is_better_metrics:
                local_validation_gap = float(validation_score) - float(best_local_score)
            else:
                local_validation_gap = float(best_local_score) - float(validation_score)
            large_gap = local_validation_gap >= 0.03
        except Exception:
            local_validation_gap = None

    return {
        "selected_candidate": selected,
        "local_metric": local_metric_name,
        "selected_local_score": selected_local_score,
        "best_local_score": best_local_score,
        "validation_score": validation_score,
        "local_validation_gap": local_validation_gap,
        "large_local_validation_gap": large_gap,
        "candidate_count": len(candidate_names),
        "base_candidate_count": len([
            name for name in candidate_names
            if not re.search(r"(?i)(?:^|[_+.-])(blend|rank|prob|weighted|equal|stack|meta|calibrat|selector)(?:$|[_+.-])", name)
        ]),
        "candidate_names": candidate_names[:16],
        "evidence_lines": evidence_lines[:8],
        "support_lines": support_lines[:6],
    }


def format_validation_diagnostics_for_summary(diagnostics: dict[str, Any]) -> str:
    if not isinstance(diagnostics, dict) or not diagnostics:
        return ""
    parts: list[str] = []
    selected = diagnostics.get("selected_candidate")
    if selected:
        parts.append(f"selected={selected}")
    metric = diagnostics.get("local_metric")
    best_local = diagnostics.get("best_local_score")
    if metric and isinstance(best_local, (int, float)):
        parts.append(f"best_{metric}={float(best_local):.6f}")
    selected_local = diagnostics.get("selected_local_score")
    if metric and isinstance(selected_local, (int, float)) and selected_local != best_local:
        parts.append(f"selected_{metric}={float(selected_local):.6f}")
    base_count = diagnostics.get("base_candidate_count")
    candidate_count = diagnostics.get("candidate_count")
    if isinstance(base_count, int) and isinstance(candidate_count, int):
        parts.append(f"base_candidates={base_count}/{candidate_count}")
    support_lines = diagnostics.get("support_lines")
    if isinstance(support_lines, list) and support_lines:
        compact_support = " || ".join(str(line)[:120] for line in support_lines[:2])
        parts.append(f"support_evidence={compact_support}")
    gap = diagnostics.get("local_validation_gap")
    if isinstance(gap, (int, float)):
        parts.append(f"local_validation_gap={float(gap):+.6f}")
        if diagnostics.get("large_local_validation_gap"):
            parts.append("next: audit CV/selector/submission mapping before adding complexity")
    return "Diagnostics: " + ", ".join(parts) if parts else ""


def build_local_round_summary(
    *,
    search_operator: SearchOperator,
    validation_status: str,
    validation_score: float | None,
    failure_taxonomy: dict[str, Any],
    solution_contract: dict[str, Any],
    branch_decision: dict[str, Any],
    task_dir: Path | None = None,
    validation_feedback: str = "",
) -> dict[str, Any]:
    """Token-free method summary used unless support LLM calls are enabled."""
    score_text = f"{validation_score:.6f}" if validation_score is not None else "N/A"
    failure_primary = failure_taxonomy.get("primary") if isinstance(failure_taxonomy, dict) else None
    missing = solution_contract.get("missing") if isinstance(solution_contract, dict) else None
    method_family = infer_posthoc_method_family(task_dir) or resolve_round_method_family(search_operator, task_dir=task_dir)
    post_code_summary = extract_post_code_method_summary(task_dir)
    diagnostics = extract_validation_log_diagnostics(validation_feedback, validation_score)
    diagnostic_text = format_validation_diagnostics_for_summary(diagnostics)
    reflection_parts = [
        f"Status={validation_status}",
        f"score={score_text}",
        f"failure_primary={failure_primary or 'none'}",
        f"static_missing={missing or []}",
    ]
    if diagnostic_text:
        reflection_parts.append(diagnostic_text)
    raw_components = [
        method_family,
        str(branch_decision.get("branch_state") or branch_decision.get("search_state") or ""),
        str(branch_decision.get("branch") or ""),
        str(branch_decision.get("runtime_profile") or ""),
    ]
    components: list[str] = []
    seen_components: set[str] = set()
    for component in raw_components:
        text = component.strip()
        key = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
        if text and key and key not in seen_components:
            seen_components.add(key)
            components.append(text)
    post_components = post_code_summary.get("core_components") if isinstance(post_code_summary.get("core_components"), list) else []
    for component in post_components:
        key = re.sub(r"[^a-z0-9]+", "_", str(component).lower()).strip("_")
        if str(component).strip() and key and key not in seen_components:
            seen_components.add(key)
            components.append(str(component).strip())
    method_summary = str(post_code_summary.get("method_summary") or "").strip()
    method_profile = str(post_code_summary.get("method_profile") or "").strip()
    parent_modification_summary = str(post_code_summary.get("parent_modification_summary") or "").strip()
    memory_reuse_signal = str(post_code_summary.get("memory_reuse_signal") or "").strip()
    card_reuse_risk = str(post_code_summary.get("card_reuse_risk") or memory_reuse_signal).strip()
    diff_action = str(post_code_summary.get("diff_action") or parent_modification_summary).strip()
    diff_reason = str(post_code_summary.get("diff_reason") or "").strip()
    if not method_summary:
        method_summary = (
            f"Branch `{branch_decision.get('branch')}` state `{branch_decision.get('branch_state') or branch_decision.get('search_state')}` "
            f"produced method family `{method_family}` with validation status `{validation_status}` and score {score_text}."
            + (f" {diagnostic_text}" if diagnostic_text else "")
        )
    if not method_profile:
        method_profile = (
            f"This attempt used method family `{method_family}` under branch `{branch_decision.get('branch')}` "
            f"and state `{branch_decision.get('branch_state') or branch_decision.get('search_state')}`. "
            f"It finished with validation status `{validation_status}` and score {score_text}; primary failure/risk was "
            f"`{failure_primary or 'none'}` and static-contract missing fields were `{missing or []}`. "
            f"Use the linked solution, validation feedback, context readiness, memory card, and diff artifact to decide "
            f"whether to reuse this method, patch it, or avoid repeating its failure mode."
        )
    return {
        "method_summary": method_summary,
        "method_profile": method_profile,
        "result_reflection": "; ".join(reflection_parts) + ".",
        "method_family": method_family,
        "core_components": components,
        "parent_modification_summary": parent_modification_summary,
        "memory_reuse_signal": memory_reuse_signal,
        "card_reuse_risk": card_reuse_risk,
        "diff_action": diff_action,
        "diff_reason": diff_reason,
        "validation_diagnostics": diagnostics,
        "novelty_vs_best": (
            card_reuse_risk
            or diff_action
            or "See branch decision, context readiness, full code, validation feedback, memory card, and diff artifact."
        ),
        "source": post_code_summary.get("source") or "v4_local_structured_summary",
    }


def write_local_memory_after_round(
    *,
    task_dir: Path,
    metadata: dict[str, Any],
    round_num: int,
    commit_hash: str,
    branch: str,
    validation_status: str,
    validation_score: float | None,
    round_summary: dict[str, Any],
    higher_is_better: bool,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update the v4 structured runtime memory bank without an additional LLM call."""
    result = result or {}
    task_name = metadata.get("task_name", task_dir.name)
    registry = load_tag_registry(task_dir)
    best_tag = registry.get("best_local_cv") or {}
    vault = best_vault_path(task_dir)
    best_text = "No scored validation candidate yet."
    if best_tag:
        best_text = (
            f"Commit {best_tag.get('commit')}, score {best_tag.get('score')}, "
            f"branch {best_tag.get('branch')}."
        )
    if vault.exists() and not best_tag:
        try:
            best_payload = json.loads(vault.read_text(encoding="utf-8"))
            best_text = (
                f"Round {int(best_payload.get('round') or 0) + 1}, commit {best_payload.get('commit_hash')}, "
                f"score {best_payload.get('validation_score')}, branch {best_payload.get('branch')}."
            )
        except Exception:
            best_text = "Best vault exists but could not be parsed."
    validation = result.get("validation") or {}
    branch_decision = result.get("branch_decision") or {}
    operator = result.get("search_operator") or {}
    solution_contract = result.get("solution_contract") or {}
    early_eda = result.get("early_eda") or {}
    code_features = inspect_code_memory_features(str(result.get("code") or ""))
    failure_taxonomy = validation.get("failure_taxonomy") or {}
    effective_lineage = result.get("effective_lineage") if isinstance(result.get("effective_lineage"), dict) else {}
    execution_operator = operator
    effective_operator = result.get("effective_operator") if isinstance(result.get("effective_operator"), dict) else operator
    effective_branch = result.get("effective_branch") or effective_lineage.get("effective_branch") or branch
    effective_search_intent = (
        result.get("effective_search_intent")
        or effective_lineage.get("effective_search_intent")
        or branch_decision.get("search_intent")
    )
    effective_method_family = (
        result.get("effective_method_family")
        or effective_lineage.get("effective_method_family")
        or effective_operator.get("family")
        or round_summary.get("method_family")
    )
    summary_components = round_summary.get("core_components") if isinstance(round_summary.get("core_components"), list) else []
    method_family_components = []
    for item in [effective_method_family, *summary_components]:
        text = str(item or "").strip()
        if text and text not in method_family_components:
            method_family_components.append(text)

    round_record = {
        "round": round_num,
        "commit": commit_hash,
        "branch": branch,
        "effective_branch": effective_branch,
        "status": validation_status,
        "score": validation_score,
        "operator": effective_operator,
        "execution_operator": execution_operator,
        "search_intent": branch_decision.get("search_intent"),
        "effective_search_intent": effective_search_intent,
        "search_state": branch_decision.get("search_state"),
        "reason": branch_decision.get("reason"),
        "method_family": effective_method_family,
        "method_family_components": method_family_components,
        "execution_method_family": round_summary.get("method_family"),
        "branch_state": branch_decision.get("branch_state"),
        "branch_reason": branch_decision.get("branch_reason") or branch_decision.get("reason"),
        "runtime_profile": branch_decision.get("runtime_profile"),
        "parent_binding": branch_decision.get("parent_binding"),
        "memory_card_path": result.get("memory_card_path"),
        "memory_diff_path": result.get("memory_diff_path"),
        "effective_lineage": effective_lineage,
        "summary": round_summary.get("method_summary"),
        "reflection": round_summary.get("result_reflection"),
        "validation_diagnostics": round_summary.get("validation_diagnostics") or {},
        "failure_primary": failure_taxonomy.get("primary"),
        "quality": validation.get("quality") or {},
        "static_status": solution_contract.get("status"),
        "static_missing": solution_contract.get("missing", []),
        "run_time": validation.get("run_time"),
        "timeout": validation.get("timeout"),
        "wall_time": result.get("round_wall_time"),
        "input_tokens": result.get("input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "eda": {
            "enabled": early_eda.get("enabled"),
            "mode": early_eda.get("mode"),
            "status": early_eda.get("status"),
            "work_dir": early_eda.get("work_dir"),
        },
        "code_features": code_features,
        "timestamp": datetime.now().isoformat(),
    }
    _append_memory_jsonl(memory_bank_path(task_dir, "rounds.jsonl"), round_record)

    if validation_score is None or solution_contract.get("status") == "block":
        _append_memory_jsonl(memory_bank_path(task_dir, "failure_ledger.jsonl"), {
            "round": round_num,
            "commit": commit_hash,
            "branch": branch,
            "status": validation_status,
            "failure_primary": failure_taxonomy.get("primary"),
            "failure_all": failure_taxonomy.get("all", []),
            "static_missing": solution_contract.get("missing", []),
            "feedback_excerpt": shrink_text_middle(str(validation.get("feedback") or ""), 1600),
            "operator": effective_operator,
            "execution_operator": execution_operator,
            "effective_lineage": effective_lineage,
            "timestamp": datetime.now().isoformat(),
        })

    eda_summary = str(early_eda.get("summary") or "").strip()
    if eda_summary:
        _append_memory_jsonl(memory_bank_path(task_dir, "eda_insights.jsonl"), {
            "schema_version": "eda_insight_v2",
            "source": "initial_eda" if early_eda.get("mode") == "early" else str(early_eda.get("mode") or "eda"),
            "round": round_num,
            "commit": commit_hash,
            "mode": early_eda.get("mode"),
            "status": early_eda.get("status"),
            "work_dir": early_eda.get("work_dir"),
            "summary": shrink_text_middle(eda_summary, 2400),
            "finding": shrink_text_middle(eda_summary, 1200),
            "confidence": "medium",
            "coding_implication": "Use as persisted EDA finding/resource/submission evidence; re-check with bounded deep EDA only when implementation depends on an uncertain contract.",
            "timestamp": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
        })
    deep_eda_insights = extract_context_deep_eda_insights(
        task_dir=task_dir,
        round_num=round_num,
        commit_hash=commit_hash,
        validation_status=validation_status,
        validation_score=validation_score,
    )
    for insight in deep_eda_insights:
        _append_memory_jsonl(memory_bank_path(task_dir, "eda_insights.jsonl"), insight)
    append_deep_eda_insights_to_initial_findings(task_dir, deep_eda_insights)

    recent_rounds = _tail_memory_jsonl(memory_bank_path(task_dir, "rounds.jsonl"), V34_MEMORY_BANK_RECENT_ROUNDS)
    recent_failures = _tail_memory_jsonl(memory_bank_path(task_dir, "failure_ledger.jsonl"), V34_MEMORY_BANK_MAX_FAILURES)
    recent_eda = _tail_memory_jsonl(memory_bank_path(task_dir, "eda_insights.jsonl"), V34_MEMORY_BANK_MAX_EDA_INSIGHTS)
    memory_rounds_for_portfolio = _load_jsonl(memory_bank_path(task_dir, "rounds.jsonl"))
    portfolio_state = load_portfolio_snapshot(task_dir, memory_rounds_for_portfolio, higher_is_better)

    state = {
        "task": task_name,
        "metric_direction": "higher" if higher_is_better else "lower",
        "best_validation_candidate": best_text,
        "portfolio": {
            "candidate_count": portfolio_state.get("candidate_count", 0),
            "best_score": portfolio_state.get("best_score"),
            "family_counts": portfolio_state.get("family_counts") or {},
            "successful_draft_origin_seed_count": portfolio_state.get("successful_draft_origin_seed_count", 0),
            "successful_draft_origin_seed_total": portfolio_state.get("successful_draft_origin_seed_total", 0),
            "required_draft_origin_seeds": portfolio_state.get("required_draft_origin_seeds", V38_REQUIRED_DRAFT_ORIGIN_SEEDS),
            "successful_draft_origin_seed_families": portfolio_state.get("successful_draft_origin_seed_families") or [],
            "diversity_gap": portfolio_state.get("diversity_gap"),
        },
        "latest_round": round_record,
        "recent_round_count": len(recent_rounds),
        "recent_failure_count": len(recent_failures),
        "recent_eda_count": len(recent_eda),
        "updated_at": datetime.now().isoformat(),
    }
    _write_memory_json(memory_bank_path(task_dir, "state.json"), state)

    return {
        "status": "updated_memory_bank",
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "memory_bank_dir": str(memory_bank_dir(task_dir)),
    }
