from __future__ import annotations

from .common import *
from .constants import *

def classify_codex_stderr(stderr_text: str, return_code: int | None) -> str:
    text = (stderr_text or "").lower()
    transient_needles = (
        "selected model is at capacity",
        "failed to connect to websocket",
        "tls handshake eof",
        "transport channel closed",
        "http/request failed",
        "connection reset",
        "temporarily unavailable",
        "server overloaded",
    )
    if any(needle in text for needle in transient_needles):
        return "llm_transient_infra"
    if "usage limit" in text or "rate limit" in text or "quota" in text or "403 forbidden" in text:
        return "llm_quota_exhausted"
    if "context" in text or "token" in text or "maximum" in text:
        return "llm_context_limit"
    if return_code not in (0, None):
        return "llm_cli_error"
    return "llm_unknown_error"


def _token_ledger_path(run_dir: Path) -> Path:
    return run_dir / "index" / "token_ledger.json"


def record_token_usage(
    task_dir: Path,
    *,
    phase: str,
    usage: dict[str, Any],
    status: str,
    failure_type: str | None = None,
) -> None:
    """Best-effort local token/call ledger; this controls analysis and later scheduling."""
    path = _token_ledger_path(task_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        payload = {}
    totals = payload.setdefault("totals", {"input_tokens": 0, "output_tokens": 0, "calls": 0, "failed_calls": 0})
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    totals["input_tokens"] = int(totals.get("input_tokens") or 0) + input_tokens
    totals["output_tokens"] = int(totals.get("output_tokens") or 0) + output_tokens
    totals["calls"] = int(totals.get("calls") or 0) + 1
    if status != "ok":
        totals["failed_calls"] = int(totals.get("failed_calls") or 0) + 1
    by_phase = payload.setdefault("by_phase", {})
    phase_row = by_phase.setdefault(phase, {"input_tokens": 0, "output_tokens": 0, "calls": 0, "failed_calls": 0})
    phase_row["input_tokens"] = int(phase_row.get("input_tokens") or 0) + input_tokens
    phase_row["output_tokens"] = int(phase_row.get("output_tokens") or 0) + output_tokens
    phase_row["calls"] = int(phase_row.get("calls") or 0) + 1
    if status != "ok":
        phase_row["failed_calls"] = int(phase_row.get("failed_calls") or 0) + 1
    events = payload.setdefault("recent_events", [])
    events.append({
        "time": datetime.now().isoformat(),
        "phase": phase,
        "status": status,
        "failure_type": failure_type,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    })
    payload["recent_events"] = events[-50:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def shrink_text_middle(text: str | None, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    head = max(limit * 2 // 3, 0)
    tail = max(limit - head, 0)
    return text[:head] + "\n...[context truncated; inspect the referenced full source file if needed]...\n" + text[-tail:]


def select_complete_lines_under_limit(text: str | None, limit: int) -> tuple[str, dict[str, Any]]:
    """
    Select complete lines only.

    This deliberately avoids head/tail truncation and avoids emitting partial
    sentences. Omitted lines are handled by retrieval-index paths elsewhere.
    """
    raw = (text or "").strip()
    lines = [line.rstrip() for line in raw.splitlines()]
    selected: list[str] = []
    used = 0
    for line in lines:
        line_len = len(line) + (1 if selected else 0)
        if len(line) > limit:
            continue
        if used + line_len > limit:
            break
        selected.append(line)
        used += line_len
    selected_text = "\n".join(selected).strip()
    return selected_text, {
        "original_chars": len(raw),
        "packed_chars": len(selected_text),
        "total_lines": len(lines),
        "selected_lines": len(selected),
        "omitted_lines": max(len(lines) - len(selected), 0),
        "mode": "complete_lines",
    }


def text_or_retrieval_note(title: str, text: str | None, limit: int, source_path: str | None = None) -> tuple[str, dict[str, Any]]:
    selected, record = select_complete_lines_under_limit(text, limit)
    record["label"] = title
    record["source_path"] = source_path
    if selected:
        return selected, record
    note = f"{title}: full content is available in [CONTEXT SOURCE MAP]"
    if source_path:
        note += f" at {source_path}"
    record.update({"packed_chars": len(note), "mode": "retrieval_note"})
    return note, record


def compact_text_field(text: str | None, limit: int) -> str:
    selected, _ = select_complete_lines_under_limit(text, limit)
    return selected


def sanitize_operator_prompt_text(text: str | None) -> str:
    return sanitize_legacy_prediction_file_language(text)


def compact_operator_description(text: str | None, limit: int = 700) -> str:
    selected, _ = select_complete_lines_under_limit(sanitize_operator_prompt_text(text), limit)
    return selected


def compact_operator_card(operator_payload: dict[str, Any] | None) -> str:
    op = operator_payload or {}
    fields = {
        "name": op.get("name"),
        "intent": op.get("intent"),
        "family": op.get("family"),
        "cost": op.get("cost"),
        "risk": op.get("risk"),
        "source": op.get("source"),
        "description": compact_operator_description(str(op.get("description") or ""), 700),
    }
    return json.dumps({k: v for k, v in fields.items() if v}, ensure_ascii=False, indent=2)


def _parse_routed_skill_payload(skill_context: str | None) -> dict[str, Any]:
    """Parse the JSON payload embedded in a routed compact task-skill packet."""
    raw = (skill_context or "").strip()
    if not raw:
        return {}
    json_start = raw.find("{")
    if json_start < 0:
        return {}
    try:
        decoded, _ = json.JSONDecoder().raw_decode(raw[json_start:])
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def split_routed_skill_sections(skill_context: str | None) -> list[tuple[str, str]]:
    """Split route_skills_for_branch markdown blocks without losing non-JSON guards."""
    raw = (skill_context or "").strip()
    if not raw:
        return []
    route_titles = {
        "V4 Task Skill Packet For Draft",
        "Draft Schema And Runtime Guard",
        "Runtime Hardening Guard",
        "V4 Minimal Task Contract For Debug",
        "Failure Prevention Slice",
        "Debug Error Taxonomy Guard",
        "V4 Operator-Aware Task Skill Packet",
        "Improve Best Guard",
        "Explore Alternative Guard",
        "Task-Specific Knowledge",
    }
    matches = [
        match for match in re.finditer(r"(?m)^##\s+(.+?)\s*$", raw)
        if match.group(1).strip() in route_titles
    ]
    if not matches:
        return [("Selected Skill Context", raw)]
    sections: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        content = raw[start:end].strip()
        if content:
            sections.append((title, content))
    return sections


def needs_latest_failed_parent(branch_decision: dict[str, Any]) -> bool:
    branch = normalize_branch_name(str(branch_decision.get("branch") or ""))
    intent = str(branch_decision.get("search_intent") or "")
    return branch == "debug" or intent == INTENT_REPAIR_FAILURE


def _round_value(row: dict[str, Any]) -> int:
    try:
        return int(row.get("round"))
    except Exception:
        return -1


def _round_commit(row: dict[str, Any]) -> str:
    commit = (
        row.get("commit_hash")
        or row.get("commit")
        or row.get("node_id")
        or (row.get("graph_node") or {}).get("commit")
    )
    return str(commit or "").strip()


def _compact_inline(value: Any, limit: int = 400) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _round_failed(row: dict[str, Any]) -> bool:
    validation = row.get("validation") if isinstance(row.get("validation"), dict) else {}
    status = str(row.get("status") or validation.get("status") or "").strip().lower()
    failure_primary = str(
        row.get("failure_primary")
        or (validation.get("failure_taxonomy") or {}).get("primary")
        or ""
    ).strip().lower()
    score = row.get("score")
    if score is None:
        score = validation.get("score")
    if score is not None and status in {"success", "completed"} and failure_primary in {"", "none"}:
        return False
    return bool(status and status not in {"success", "completed"}) or failure_primary not in {"", "none"}


def _lookup_card_index_ref(task_dir: Path, *, round_num: int | None, commit: str | None) -> dict[str, Any]:
    rows = _load_jsonl(task_dir / "memory_bank" / "card_index.jsonl")
    commit_text = str(commit or "").strip()
    try:
        round_value = int(round_num) if round_num is not None else None
    except Exception:
        round_value = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_commit = str(row.get("commit") or "").strip()
        try:
            row_round = int(row.get("round")) if row.get("round") is not None else None
        except Exception:
            row_round = None
        if commit_text and row_commit and row_commit == commit_text:
            return row
        if round_value is not None and row_round == round_value:
            return row
    return {}


def find_latest_failed_parent_candidate(task_dir: Path) -> dict[str, Any] | None:
    """Find the newest failed commit that can be patched by a debug round."""
    rows: list[dict[str, Any]] = []
    rows.extend(_load_jsonl(task_dir / "memory_bank" / "rounds.jsonl"))
    rows.extend(_load_jsonl(graph_dir(task_dir) / "nodes.jsonl"))
    summary = safe_load_json_file(task_dir / "rounds_summary.json")
    rounds = summary.get("rounds")
    if isinstance(rounds, list):
        rows.extend(row for row in rounds if isinstance(row, dict))

    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not _round_failed(row):
            continue
        status = validation_status(row)
        if status in NON_DEBUG_NO_SCORE_STATUSES and status != "static_gate_blocked":
            continue
        commit = _round_commit(row)
        if commit:
            commit_dir = task_dir / "commits" / commit
            solution_path = commit_dir / "solution.py"
            feedback_path = commit_dir / "validation_feedback.txt"
            code_path = f"commits/{commit}/solution.py"
        else:
            code_value = str(row.get("code_path") or row.get("failure_artifact_code_path") or "").strip()
            feedback_value = str(row.get("validation_feedback_path") or row.get("failure_artifact_feedback_path") or "").strip()
            if not code_value or not feedback_value:
                continue
            solution_path = Path(code_value)
            if not solution_path.is_absolute():
                solution_path = task_dir / solution_path
            feedback_path = Path(feedback_value)
            if not feedback_path.is_absolute():
                feedback_path = task_dir / feedback_path
            try:
                code_path = str(solution_path.resolve().relative_to(task_dir.resolve()))
            except Exception:
                code_path = str(solution_path.resolve())
        if not solution_path.exists() or not feedback_path.exists():
            continue
        row_decision = row.get("branch_decision") if isinstance(row.get("branch_decision"), dict) else {}
        row_operator = round_effective_operator_payload(row)
        row_family = round_effective_method_family(row)
        row_intent = round_effective_search_intent(row)
        row_lineage = row.get("effective_lineage") if isinstance(row.get("effective_lineage"), dict) else {}
        row_round = _round_value(row)
        card_ref = _lookup_card_index_ref(task_dir, round_num=row_round, commit=commit)
        candidates.append({
            "commit": commit,
            "round": row_round,
            "branch": row.get("branch") or row_decision.get("branch"),
            "search_intent": row_intent or row.get("search_intent") or row_decision.get("search_intent"),
            "search_state": row.get("search_state") or row_decision.get("search_state"),
            "reason": row.get("reason") or row_decision.get("reason"),
            "operator": row_operator,
            "method_family": row_family,
            "seed_id": row_lineage.get("seed_id") or (f"seed:{commit}" if commit else ""),
            "effective_lineage": row_lineage,
            "solution_path": str(solution_path.resolve()),
            "code_path": code_path,
            "validation_feedback_path": str(feedback_path.resolve()),
            "card_path": row.get("memory_card_path") or row.get("card_path") or card_ref.get("card_path"),
            "diff_path": row.get("memory_diff_path") or row.get("diff_path") or card_ref.get("diff_path"),
            "status": row.get("status") or (row.get("validation") or {}).get("status"),
            "failure_primary": row.get("failure_primary")
                or ((row.get("validation") or {}).get("failure_taxonomy") or {}).get("primary"),
            "source": "latest_failed_validation" if commit else "latest_failed_static_gate_artifact",
        })
    if not candidates:
        return None
    candidates.sort(key=lambda item: (int(item.get("round") or -1), str(item.get("commit") or "")))
    return candidates[-1]


def apply_latest_failed_parent_fallback(task_dir: Path, branch_decision: dict[str, Any]) -> dict[str, Any]:
    """Point debug/repair rounds at the newest failed commit, not merely the best commit."""
    if str(branch_decision.get("schema_version") or "").startswith("branch_decision_v3"):
        return branch_decision
    if not needs_latest_failed_parent(branch_decision):
        return branch_decision
    candidate = find_latest_failed_parent_candidate(task_dir)
    if not candidate:
        return branch_decision
    enriched = dict(branch_decision)
    enriched["parent_commit"] = candidate["commit"]
    enriched["parent_code_path"] = candidate["code_path"]
    enriched["parent_validation_feedback_path"] = candidate["validation_feedback_path"]
    enriched["debug_parent_round"] = candidate["round"]
    enriched["debug_parent_commit"] = candidate["commit"]
    enriched["debug_parent_code_path"] = candidate["code_path"]
    enriched["debug_parent_validation_feedback_path"] = candidate["validation_feedback_path"]
    enriched["debug_parent_card_path"] = candidate.get("card_path")
    enriched["debug_parent_diff_path"] = candidate.get("diff_path")
    enriched["repair_seed_id"] = candidate.get("seed_id")
    enriched["repair_parent_method_family"] = candidate.get("method_family")
    enriched["debug_parent_fallback"] = {
        "source": candidate["source"],
        "round": candidate["round"],
        "commit": candidate["commit"],
        "seed_id": candidate.get("seed_id"),
        "branch": candidate.get("branch"),
        "search_intent": candidate.get("search_intent"),
        "search_state": candidate.get("search_state"),
        "reason": candidate.get("reason"),
        "operator": candidate.get("operator") or {},
        "method_family": candidate.get("method_family"),
        "effective_lineage": candidate.get("effective_lineage") or {},
        "code_path": candidate.get("code_path"),
        "feedback_path": candidate.get("validation_feedback_path"),
        "card_path": candidate.get("card_path"),
        "diff_path": candidate.get("diff_path"),
        "status": candidate.get("status"),
        "failure_primary": candidate.get("failure_primary"),
    }
    return enriched


def compact_branch_state(branch_decision: dict[str, Any], best_score: float | None = None) -> str:
    diagnostics = branch_decision.get("state_diagnostics") or {}
    anti = branch_decision.get("anti_repetition") or {}
    runtime_control = branch_decision.get("runtime_control") if isinstance(branch_decision.get("runtime_control"), dict) else {}
    state = {
        "branch": branch_decision.get("branch"),
        "reason": branch_decision.get("reason"),
        "search_state": branch_decision.get("search_state"),
        "search_intent": branch_decision.get("search_intent"),
        "portfolio_action": branch_decision.get("portfolio_action"),
        "portfolio_slot": branch_decision.get("portfolio_slot"),
        "runtime_control": {
            "selected_method_family": runtime_control.get("selected_method_family"),
            "selected_family_scored_successes": runtime_control.get("selected_family_scored_successes"),
            "timeout_profile": runtime_control.get("timeout_profile"),
            "strict_score_first_required": runtime_control.get("strict_score_first_required"),
        } if runtime_control else None,
        "best_score": best_score if best_score is not None else branch_decision.get("best_local_cv_score"),
        "parent_commit": branch_decision.get("parent_commit") or branch_decision.get("best_local_cv_commit"),
        "since_best_successes": diagnostics.get("since_best_successes"),
        "frontload_attempts": diagnostics.get("frontload_attempts"),
        "frontload_max_attempts": diagnostics.get("frontload_max_attempts"),
        "frontload_attempt_budget_exhausted": diagnostics.get("frontload_attempt_budget_exhausted"),
        "structural_success_family_count": diagnostics.get("structural_success_family_count"),
        "structural_success_families": diagnostics.get("structural_success_families"),
        "recent_timeouts": diagnostics.get("recent_timeouts"),
        "avoid_family": anti.get("avoid_method_family") or diagnostics.get("repeated_method_family"),
        "avoid_families": anti.get("avoid_method_families"),
        "avoid_operators": anti.get("avoid_operators"),
        "novelty_reasons": anti.get("novelty_reasons"),
    }
    return json.dumps({k: v for k, v in state.items() if v is not None}, ensure_ascii=False, indent=2)


def safe_load_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk without letting corrupt runtime state break prompt packing."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_text_if_exists(path: Path, limit: int | None = None) -> str:
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""
    if limit is not None:
        return select_complete_lines_under_limit(text, limit)[0]
    return text


def resolve_task_work_dir(work_dir: Path) -> Path:
    """Map auxiliary phase directories back to the task root that owns index/ and memory_bank/."""
    current = work_dir.resolve()
    if (current / "index").exists() or (current / "memory_bank").exists():
        return current
    if current.name.startswith("round_") and current.parent.name in {"early_eda", "deep_eda"}:
        return current.parent.parent
    return current


def detect_output_dir_contamination(output_path: Path) -> list[str]:
    """Detect path-layout problems that should never be produced by a clean run."""
    if not output_path.exists():
        return []
    findings: list[str] = []
    run_name = output_path.name

    for link in output_path.glob(f"*/{run_name}"):
        if link.is_symlink():
            try:
                target = os.readlink(link)
            except OSError:
                target = "<unreadable>"
            findings.append(f"task-level run-name symlink: {link} -> {target}")
            if len(findings) >= 4:
                return findings

    for task_dir in sorted(p for p in output_path.iterdir() if p.is_dir()):
        for eda_root_name in ("early_eda", "deep_eda"):
            eda_root = task_dir / eda_root_name
            if not eda_root.is_dir():
                continue
            round_dirs = sorted(p for p in eda_root.glob("round_*") if p.is_dir())
            if len(round_dirs) < 10:
                continue
            symlink_only_dirs = 0
            for round_dir in round_dirs:
                real_files = [p for p in round_dir.rglob("*") if p.is_file() and not p.is_symlink()]
                symlinks = [p for p in round_dir.iterdir() if p.is_symlink()]
                if symlinks and not real_files:
                    symlink_only_dirs += 1
            if symlink_only_dirs >= 10:
                findings.append(
                    f"prebuilt symlink-only {eda_root_name} rounds under {task_dir.name}: "
                    f"{symlink_only_dirs}/{len(round_dirs)}"
                )
                if len(findings) >= 8:
                    return findings
    return findings


def prompt_token_count(text: str | None) -> int:
    """Count prompt tokens with o200k_base when available; fall back conservatively."""
    raw = text or ""
    if not raw:
        return 0
    if tiktoken is not None:
        try:
            return len(tiktoken.get_encoding("o200k_base").encode(raw))
        except Exception:
            pass
    # Conservative fallback for mostly English/code prompts.
    return max(1, (len(raw) + 2) // 3)


def select_complete_lines_under_token_limit(text: str | None, token_limit: int) -> tuple[str, dict[str, Any]]:
    """Select complete lines under a token budget without mid-sentence cuts."""
    raw = (text or "").strip()
    lines = [line.rstrip() for line in raw.splitlines()]
    selected: list[str] = []
    for line in lines:
        candidate = "\n".join([*selected, line]).strip() if selected else line.strip()
        if prompt_token_count(candidate) > token_limit:
            if len(line) > 0 and not selected:
                # Fall back to character-safe complete-line selector for pathological long lines.
                selected_text, record = select_complete_lines_under_limit(raw, max(token_limit * 3, 1200))
                record.update({"token_limit": token_limit, "tokens": prompt_token_count(selected_text)})
                return selected_text, record
            break
        selected.append(line)
    selected_text = "\n".join(selected).strip()
    return selected_text, {
        "original_chars": len(raw),
        "packed_chars": len(selected_text),
        "original_tokens": prompt_token_count(raw),
        "packed_tokens": prompt_token_count(selected_text),
        "token_limit": token_limit,
        "total_lines": len(lines),
        "selected_lines": len(selected),
        "omitted_lines": max(len(lines) - len(selected), 0),
        "mode": "complete_lines_token_budget",
    }


def remove_marked_block(text: str, header: str, next_headers: tuple[str, ...]) -> str:
    """Remove a bracketed prompt block from header until the next known header."""
    start = text.find(header)
    if start < 0:
        return text
    end = len(text)
    for next_header in next_headers:
        idx = text.find(next_header, start + len(header))
        if idx >= 0:
            end = min(end, idx)
    return (text[:start].rstrip() + "\n\n" + text[end:].lstrip()).strip()


def insert_after_header(text: str, header: str, insertion: str) -> str:
    """Insert a prompt card immediately after a top-level bracket header."""
    if not insertion.strip():
        return text
    start = text.find(header)
    if start < 0:
        return insertion.strip() + "\n\n" + text.strip()
    end = start + len(header)
    return (text[:end].rstrip() + "\n\n" + insertion.strip() + "\n\n" + text[end:].lstrip()).strip()


CURRENT_FRAMEWORK_USER_CONTRACT = """[CURRENT FRAMEWORK USER CONTRACT]
The original benchmark user message may describe a chat-style answer with a markdown code block. In this framework, ignore legacy chat-output instructions and follow the Codex execution protocol above.
Original task/evaluation/submission requirements below remain binding; resolve schema-sensitive conflicts using `[PINNED HARD TASK CONTRACT]` when present, EDA paths in `[CONTEXT SOURCE MAP]`, and runtime DATA_DIR inspection."""


def extract_marked_block(text: str, header: str, next_headers: tuple[str, ...]) -> str:
    """Extract a bracketed prompt block from header until the next known header."""
    start = text.find(header)
    if start < 0:
        return ""
    content_start = start + len(header)
    end = len(text)
    for next_header in next_headers:
        idx = text.find(next_header, content_start)
        if idx >= 0:
            end = min(end, idx)
    return text[content_start:end].strip()


def _extract_preinstalled_packages(system_block: str) -> list[str]:
    match = re.search(r"preinstalled:\s*(.+?)(?:\.\s+If you need to|\n|$)", system_block, flags=re.S)
    if not match:
        return []
    packages = []
    for item in match.group(1).replace("\n", " ").split(","):
        name = item.strip().strip(".")
        if name:
            packages.append(name)
    return packages


def build_v35_sandbox_environment_card(user_task_raw: str, metadata: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Pin non-conflicting sandbox resources, package availability, and API compatibility notes."""
    system_block = extract_marked_block(
        user_task_raw,
        "\n[SYSTEM]",
        ("\n[USER]", "\n[REFINEMENT CONTEXT", "\n[METADATA]", "\n[TASK DESCRIPTION]"),
    )
    user_block = extract_marked_block(
        user_task_raw,
        "\n[USER]",
        ("\n[REFINEMENT CONTEXT", "\n[METADATA]", "\n[TASK DESCRIPTION]"),
    )
    metadata = metadata or {}
    record: dict[str, Any] = {
        "system_block_chars": len(system_block),
        "user_block_chars": len(user_block),
        "status": "missing",
    }

    packages = _extract_preinstalled_packages(system_block)
    package_groups = [
        ["numpy", "pandas", "scikit-learn", "scipy"],
        ["xgboost", "lightgbm", "catboost"],
        ["torch", "torchvision", "torchaudio", "timm"],
        ["transformers", "datasets", "tokenizers", "accelerate", "sentence-transformers"],
        ["opencv-python", "scikit-image", "pillow", "albumentations"],
        ["librosa", "soundfile", "speechbrain", "openai-whisper"],
        ["optuna", "bayesian-optimization", "shap"],
    ]
    available_groups: list[str] = []
    package_set = set(packages)
    for group in package_groups:
        present = [name for name in group if name in package_set]
        if present:
            available_groups.append(", ".join(present))
    other_packages = [
        name for name in packages
        if not any(name in group for group in package_groups)
    ]

    resource_lines = []
    for raw_line in system_block.splitlines():
        line = raw_line.strip()
        if line.startswith("- CPU:") or "System Memory" in line or "Shared Memory" in line or "GPU Memory" in line:
            resource_lines.append(line.lstrip("- ").strip())

    api_constraints: list[str] = []
    if "torch.optim.AdamW" in user_block:
        api_constraints.append("Use `torch.optim.AdamW`; do not import deprecated `AdamW` from `transformers`.")
    if "LightGBM" in user_block or "lightgbm.early_stopping" in user_block:
        api_constraints.append("For LightGBM, use callbacks such as `lightgbm.early_stopping(...)`; set model parameters during initialization, not deprecated `fit()` arguments.")
    if "eval_strategy" in user_block or "TrainingArguments" in user_block:
        api_constraints.append("For recent Transformers, use `eval_strategy`; handle class weighting in the loss rather than `TrainingArguments`.")
    if "albumentations" in user_block or "RandomResizedCrop" in user_block:
        api_constraints.append("For albumentations crop/geometric transforms, use verified APIs such as `size=(H, W)` and avoid guessed transform names/parameters.")

    lines = [
        "[PINNED SANDBOX ENVIRONMENT]",
        "Deterministic extraction from the original benchmark system/user message. This section keeps environment facts and API compatibility notes without restoring legacy chat-output instructions.",
    ]
    if metadata.get("cpu_gpu"):
        lines.append(f"Resource type from metadata: {metadata.get('cpu_gpu')}")
    if resource_lines:
        lines.append("Sandbox resources:")
        for line in resource_lines:
            lines.append(f"- {line}")
    if available_groups:
        lines.append("Preinstalled package groups:")
        for group in available_groups:
            lines.append(f"- {group}")
    if other_packages:
        lines.append(f"Other listed packages: {', '.join(other_packages)}")
    if "PyTorch rather than TensorFlow" in system_block:
        lines.append("Neural-network preference: prefer PyTorch over TensorFlow unless task evidence strongly suggests otherwise.")
    if {"torch", "torchvision", "timm"} & package_set or {"transformers", "sentence-transformers"} & package_set:
        lines.append("Model-weight handling:")
        lines.append("- Do not download weights from the internet during validation.")
        lines.append("- Package/framework caches may exist inside the sandbox; generated code may probe `TORCH_HOME`, `~/.cache/torch`, `~/.cache/huggingface`, and known mounted cache roots only in offline/cache mode.")
        lines.append("- For any pretrained attempt, print whether weights were actually loaded and keep a trained no-download fallback.")
    if api_constraints:
        lines.append("API compatibility constraints:")
        for item in api_constraints:
            lines.append(f"- {item}")
    if len(lines) <= 2:
        lines.append("No original sandbox environment block was found; use generic runtime caps and dependency fallbacks.")

    card = "\n".join(lines).strip()
    record.update({
        "status": "ok" if len(lines) > 2 else "missing",
        "packages_count": len(packages),
        "resource_lines": resource_lines,
        "api_constraints_count": len(api_constraints),
        "card_chars": len(card),
        "card_tokens": prompt_token_count(card),
    })
    return card, record


def filter_user_task_for_context_first_coding(user_task_raw: str) -> tuple[str, dict[str, Any]]:
    """Keep task/output instructions inline while dropping bulky metadata inventories."""
    filtered = user_task_raw.strip()
    next_headers = (
        "\n[DATA DESCRIPTION]",
        "\n[TASK DESCRIPTION]",
        "\n[REFINEMENT CONTEXT",
        "\n[USER]",
    )
    filtered = remove_marked_block(filtered, "\n[METADATA]", next_headers)
    filtered = remove_marked_block(filtered, "\n[DATA DESCRIPTION]", ("\n[TASK DESCRIPTION]", "\n[REFINEMENT CONTEXT"))
    # The embedded prompt-message system block duplicates the top-level system prompt and package list.
    filtered = remove_marked_block(filtered, "\n[SYSTEM]", ("\n[USER]", "\n[REFINEMENT CONTEXT", "\n[METADATA]", "\n[TASK DESCRIPTION]"))
    # The original benchmark [USER] block asks for a markdown-code answer. Coding runs must create files instead.
    filtered = remove_marked_block(filtered, "\n[USER]", ("\n[REFINEMENT CONTEXT", "\n[METADATA]", "\n[TASK DESCRIPTION]"))
    # v4 source maps replace the older retrieval-index wording, so keep only one retrieval model.
    filtered = remove_marked_block(filtered, "\n[REFINEMENT CONTEXT ROUTING]", ("\n[TASK DESCRIPTION]", "\n[METADATA]"))
    filtered = insert_after_header(filtered, "[USER TASK]", CURRENT_FRAMEWORK_USER_CONTRACT)
    filtered = re.sub(r"\n{4,}", "\n\n\n", filtered).strip()
    record: dict[str, Any] = {
        "original_chars": len(user_task_raw),
        "filtered_chars": len(filtered),
        "original_tokens": prompt_token_count(user_task_raw),
        "filtered_tokens": prompt_token_count(filtered),
        "removed_blocks": ["embedded_system", "metadata", "data_description", "legacy_user_output_contract", "legacy_refinement_context_routing"],
    }
    if prompt_token_count(filtered) > V35_FILTERED_USER_TASK_LIMIT_TOKENS:
        selected, budget_record = select_complete_lines_under_token_limit(filtered, V35_FILTERED_USER_TASK_LIMIT_TOKENS)
        filtered = selected.rstrip() + (
            "\n\n[USER TASK RETRIEVAL]\n"
            "The complete original user-task source is listed in `[CONTEXT SOURCE MAP]`. "
            "The pinned task contract and source-map EDA paths are authoritative for schema-sensitive details."
        )
        record["token_budget_reduction"] = budget_record
        record["filtered_chars"] = len(filtered)
        record["filtered_tokens"] = prompt_token_count(filtered)
    return filtered, record


def find_latest_eda_summary_path(task_dir: Path) -> Path | None:
    candidates: list[Path] = []
    for root_name in ("deep_eda", "early_eda"):
        root = task_dir / root_name
        if root.is_dir():
            candidates.extend(sorted(root.glob("round_*/eda_summary.md")))
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def find_latest_eda_findings_path(task_dir: Path) -> Path | None:
    """Return the freshest human-readable EDA findings across early/deep rounds."""
    candidates: list[Path] = []
    for root_name in ("deep_eda", "early_eda"):
        root = task_dir / root_name
        if root.is_dir():
            candidates.extend(sorted(root.glob("round_*/eda_findings.md")))
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _operator_name(operator_payload: dict[str, Any] | None) -> str:
    if not isinstance(operator_payload, dict):
        return ""
    return str(operator_payload.get("name") or "").strip()


def build_v35_hard_task_contract(
    skill_context: str | None,
    operator_override: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a deterministic hard-contract card from the routed skill packet."""
    raw_original = (skill_context or "").strip()
    raw = sanitize_legacy_prediction_file_language(raw_original).strip()
    record: dict[str, Any] = {
        "source": "routed_skill_context",
        "original_chars": len(raw_original),
        "original_tokens": prompt_token_count(raw_original),
        "sanitized_chars": len(raw),
        "sanitized_tokens": prompt_token_count(raw),
        "parsed_json_packet": False,
    }
    if not raw:
        record["mode"] = "missing"
        return "", record

    payload = _parse_routed_skill_payload(raw)
    record["parsed_json_packet"] = bool(payload)
    guard_only_context = (
        not payload
        and any(marker in raw for marker in (
            "## Draft Guard",
            "## Debug Error Taxonomy Guard",
            "## Improve Best Guard",
            "## Runtime Hardening Guard",
        ))
        and "[BRANCH INLINE GUARDS]" not in raw
    )

    lines = [
        "[PINNED HARD TASK CONTRACT]",
        "Deterministic extraction from routed task-skill packet. This section is authoritative for task units, target shape, metric/submission constraints, and avoid rules.",
    ]
    if payload:
        for key in ("task_contract", "validation_contract", "avoid_rules"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                selected, key_record = select_complete_lines_under_token_limit(value, 1100)
                lines.extend(["", f"[{key.upper()}]", selected.strip()])
                record[f"{key}_tokens"] = key_record.get("packed_tokens")
        operator = payload.get("selected_operator")
        effective_operator = operator_override if _operator_name(operator_override) else operator
        if isinstance(effective_operator, dict):
            operator_label = "[SELECTED_OPERATOR]"
            if _operator_name(operator_override) and _operator_name(operator) and _operator_name(operator_override) != _operator_name(operator):
                operator_label = "[SELECTED_OPERATOR - CODING CALL OVERRIDE]"
                record["selected_operator_overridden"] = {
                    "routed_skill_operator": _operator_name(operator),
                    "coding_call_operator": _operator_name(operator_override),
                }
            lines.extend(["", operator_label, json.dumps(effective_operator, ensure_ascii=False, indent=2)])
    elif guard_only_context:
        # Guard-only routed context has no task contract. The source-map section
        # explains required/optional task-skill reads; do not emit a placeholder
        # section that looks like task information.
        record["mode"] = "branch_inline_guards_skipped"
        return "", record
    else:
        selected, fallback_record = select_complete_lines_under_token_limit(raw, 2400)
        lines.extend(["", selected.strip()])
        record["fallback_reduction"] = fallback_record
    card = "\n".join(lines).strip()
    record.update({"card_chars": len(card), "card_tokens": prompt_token_count(card)})
    return card, record


def build_v35_selected_skill_card(
    skill_context: str | None,
    operator_override: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Keep routed-skill context inline without duplicating the hard task contract."""
    raw_original = (skill_context or "").strip()
    raw = sanitize_legacy_prediction_file_language(raw_original).strip()
    record: dict[str, Any] = {
        "original_chars": len(raw_original),
        "original_tokens": prompt_token_count(raw_original),
        "sanitized_chars": len(raw),
        "sanitized_tokens": prompt_token_count(raw),
        "mode": "compact_nonduplicative_card",
    }
    if not raw:
        return "", record

    payload = _parse_routed_skill_payload(raw)
    lines = [
        "[SELECTED SKILL CONTEXT]",
        "Compact routed-skill card. `[PINNED HARD TASK CONTRACT]` remains authoritative for task units, target shape, metric, and avoid rules; this card preserves branch-specific execution guidance that is not duplicated there.",
    ]
    if payload:
        record["parsed_json_packet"] = True
        operator = payload.get("selected_operator")
        effective_operator = operator_override if _operator_name(operator_override) else operator
        if _operator_name(operator_override) and _operator_name(operator) and _operator_name(operator_override) != _operator_name(operator):
            record["selected_operator_overridden"] = {
                "routed_skill_operator": _operator_name(operator),
                "coding_call_operator": _operator_name(operator_override),
            }
            lines.extend([
                "",
                "[OPERATOR ROUTING NOTE]",
                "The routed skill packet was created while the runtime trigger was still active. The coding-call operator below is authoritative for this solution.py generation.",
            ])
        if isinstance(effective_operator, dict) and effective_operator:
            lines.extend(["", "[SELECTED OPERATOR CARD]", compact_operator_card(effective_operator)])
        for key, label, budget in [
            ("first_run", "[FIRST-RUN BASELINE EXCERPT]", 520),
            ("strategy", "[HIGH-ROI STRATEGY EXCERPT]", 360),
            ("priorities", "[OPERATOR PRIORITIES EXCERPT]", 420),
        ]:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                excerpt, excerpt_record = select_complete_lines_under_token_limit(value, budget)
                if excerpt.strip():
                    lines.extend(["", label, excerpt.strip()])
                    record[f"{key}_tokens"] = excerpt_record.get("packed_tokens")
        upgrade_menu = payload.get("upgrade_menu")
        if isinstance(upgrade_menu, str) and upgrade_menu.strip():
            upgrade_excerpt, upgrade_record = select_complete_lines_under_token_limit(upgrade_menu, 850)
            if upgrade_excerpt:
                lines.extend([
                    "",
                    "[UPGRADE MENU EXCERPT]",
                    upgrade_excerpt.strip(),
                    "Full upgrade menu: read the routed skill source listed in `[CONTEXT SOURCE MAP]` if the branch needs details beyond this excerpt.",
                ])
                record["upgrade_menu_tokens"] = upgrade_record.get("packed_tokens")
        route_sections = split_routed_skill_sections(raw)
        guard_budget_by_title = {
            "Draft Schema And Runtime Guard": 260,
            "Failure Prevention Slice": 720,
            "Debug Error Taxonomy Guard": 260,
            "Improve Best Guard": 260,
            "Explore Alternative Guard": 260,
            "Runtime Hardening Guard": 420,
        }
        emitted_guard_titles: list[str] = []
        for title, content in route_sections:
            budget = guard_budget_by_title.get(title)
            if budget is None:
                continue
            excerpt, guard_record = select_complete_lines_under_token_limit(content, budget)
            if not excerpt.strip():
                continue
            marker = "[" + re.sub(r"[^A-Z0-9]+", "_", title.upper()).strip("_") + "]"
            lines.extend(["", marker, excerpt.strip()])
            emitted_guard_titles.append(title)
            record[f"route_section_{title}"] = guard_record.get("packed_tokens")
        if emitted_guard_titles:
            record["emitted_route_sections"] = emitted_guard_titles
        retrieval_notes = [
            payload.get("task_contract_retrieval"),
            payload.get("upgrade_menu_retrieval"),
            payload.get("validation_contract_retrieval"),
            payload.get("avoid_rules_retrieval"),
        ]
        retrieval_notes_raw = [
            str(note).strip()
            for note in retrieval_notes
            if str(note or "").strip()
        ]
        retrieval_notes = list(dict.fromkeys(retrieval_notes_raw))
        if retrieval_notes:
            lines.extend(["", "[SKILL SOURCE NOTES]"])
            for note in retrieval_notes[:4]:
                lines.append(f"- {note}")
    else:
        record["parsed_json_packet"] = False
        selected, fallback_record = select_complete_lines_under_token_limit(raw, V35_SELECTED_SKILL_CARD_LIMIT_TOKENS)
        if selected:
            lines.extend(["", selected.strip()])
            record["fallback_reduction"] = fallback_record

    card = "\n".join(lines).strip()
    if prompt_token_count(card) > V35_SELECTED_SKILL_CARD_LIMIT_TOKENS:
        selected, budget_record = select_complete_lines_under_token_limit(card, V35_SELECTED_SKILL_CARD_LIMIT_TOKENS)
        card = selected.rstrip() + (
            "\n\n[SELECTED SKILL SOURCE]\n"
            "Full routed task skill context is listed in `[CONTEXT SOURCE MAP]`; inspect it when this compact card is insufficient."
        )
        record["token_budget_reduction"] = budget_record
    record.update({"card_chars": len(card), "card_tokens": prompt_token_count(card)})
    return card, record


def build_v4_history_context_paths(
    task_dir: Path,
    *,
    branch: str,
    intent: str,
    best_path: str | None = None,
    parent_path: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Select a tiny, high-value set of prior complete-code paths.

    v4 deliberately does not dump every historical solution into the prompt.
    It exposes the current anchor plus a few top-scoring, method-diverse commits
    so Codex can inspect concrete implementations when planning improve/blend
    rounds without making draft rounds overfit old code.
    """
    portfolio = safe_load_json_file(task_dir / V3_GRAPH_DIR / "portfolio.json")
    commits = portfolio.get("candidates") if isinstance(portfolio, dict) else []
    if not isinstance(commits, list) or not commits:
        rounds = _load_jsonl(task_dir / "memory_bank" / "rounds.jsonl")
        commits = [
            {
                "commit": row.get("commit"),
                "round": row.get("round"),
                "score": row.get("score"),
                "method_family": row.get("method_family"),
            }
            for row in rounds
            if isinstance(row, dict) and row.get("score") is not None and row.get("commit")
        ]

    anchor_paths = {
        str(best_path or "").strip(),
        str(parent_path or "").strip(),
    }
    anchor_paths = {p for p in anchor_paths if p}
    selected: list[dict[str, Any]] = []
    seen_paths: set[str] = set(anchor_paths)
    seen_families: set[str] = set()
    max_items = 2 if branch == "draft" else limit
    candidate_idx = 0

    for row in commits:
        if not isinstance(row, dict):
            continue
        commit = str(row.get("commit") or "").strip()
        if not commit:
            continue
        solution = f"commits/{commit}/solution.py"
        if solution in seen_paths:
            continue
        if not (task_dir / solution).exists():
            continue
        family = str(row.get("method_family") or "").strip() or "unknown"
        if family in seen_families and len(selected) < max_items:
            continue
        candidate_idx += 1
        selected.append({
            "label": f"top_diverse_solution_{candidate_idx}",
            "path": solution,
            "commit": commit,
            "round": row.get("round"),
            "score": row.get("score"),
            "method_family": family,
        })
        seen_paths.add(solution)
        seen_families.add(family)

        feedback = f"commits/{commit}/validation_feedback.txt"
        if feedback and branch != "draft":
            selected.append({
                "label": f"top_diverse_feedback_{candidate_idx}",
                "path": feedback,
                "commit": commit,
                "method_family": family,
            })
        if len(seen_families) >= max_items:
            break

    return selected


def build_v35_context_source_map(pinned_info: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build one canonical path map instead of repeating mandatory and retrieval lists."""
    task_dir = Path(str(pinned_info.get("task_dir") or ".")).resolve()
    metadata = pinned_info.get("metadata") if isinstance(pinned_info.get("metadata"), dict) else {}
    phase_name = str(pinned_info.get("phase_name") or "coding").strip().lower()
    source_policy = pinned_info.get("source_policy") if isinstance(pinned_info.get("source_policy"), dict) else {}
    must_classes = set(str(item) for item in (source_policy.get("must") or []))
    context_eda_data_dir = str(
        pinned_info.get("context_eda_data_dir")
        or metadata.get("context_eda_data_dir")
        or metadata.get("data_dir")
        or ""
    ).strip()
    branch = normalize_branch_name(str(pinned_info.get("branch") or ""))
    intent = str(pinned_info.get("search_intent") or "")
    non_draft = branch != "draft"
    repair_round = branch == "debug" or intent == INTENT_REPAIR_FAILURE
    seen: set[str] = set()
    must: list[tuple[str, str, str]] = []
    optional: list[tuple[str, str, str]] = []

    def display_path(path: str) -> str:
        if path == "<missing>":
            return path
        try:
            path_obj = Path(path)
            resolved = path_obj.resolve() if path_obj.is_absolute() else (task_dir / path_obj).resolve()
            rel = resolved.relative_to(task_dir)
            return "." if str(rel) == "." else str(rel)
        except Exception:
            return path

    def add(bucket: list[tuple[str, str, str]], label: str, value: Any, *, include_missing: bool = False) -> None:
        path = str(value or "").strip()
        if not path or path == "<missing>":
            if include_missing:
                bucket.append((label, "<missing>", "<missing>"))
            return
        try:
            canonical = str((Path(path) if Path(path).is_absolute() else task_dir / path).resolve())
        except Exception:
            canonical = path
        if not Path(canonical).exists():
            if include_missing:
                bucket.append((label, canonical, display_path(canonical)))
            return
        if canonical in seen:
            return
        seen.add(canonical)
        bucket.append((label, canonical, display_path(canonical)))

    def classify_source_path(path_str: str) -> str:
        path_text = str(path_str)
        lower = path_text.lower()
        name = Path(path_text).name.lower()
        if "task_skill_source" in name:
            return "task_skill_source"
        if "failure_prevention_skill_source" in name:
            return "failure_prevention_skill_source"
        sniff = ""
        try:
            path_obj = Path(path_text)
            if not path_obj.is_absolute():
                path_obj = task_dir / path_obj
            if path_obj.is_file():
                sniff = path_obj.read_text(encoding="utf-8", errors="replace")[:1600].lower()
        except Exception:
            sniff = ""
        combined = f"{lower}\n{sniff}"
        if "mle-reimagined" in combined or re.search(r"skill_[a-z0-9_.-]+\.md", combined):
            if "mle_skill_error" not in combined and "failure prevention" not in combined:
                return "task_skill_source"
        if "mle_skill_error" in combined or "failure prevention" in combined or "ml failure prevention" in combined:
            return "failure_prevention_skill_source"
        if "SKILL_" in path_text or path_text.endswith("/SKILL.md") or "routed_skill_source_" in path_text:
            return "routed_skill_source"
        return "context_source"

    def source_class_for_label(label: str) -> str:
        if label == "task_skill_source":
            return "task_skill"
        if label == "failure_prevention_skill_source":
            return "failure_prevention_skill"
        if label == "routed_skill_source":
            return "task_skill" if "task_skill" in must_classes else "failure_prevention_skill"
        return label

    def add_source_path(value: Any, *, include_missing: bool = False) -> None:
        label = classify_source_path(str(value or ""))
        source_class = source_class_for_label(label)
        bucket = must if source_class in must_classes else optional
        add(bucket, label, value, include_missing=include_missing and bucket is must)

    independent_seed_draft = branch == "draft"
    draft_static_repair = independent_seed_draft and phase_name == "static_gate_repair"

    if draft_static_repair:
        add(must, "current_round_solution", task_dir / "solution.py")
        add(must, "current_context_readiness", task_dir / "context_readiness.md")
        add(must, "current_post_code_memory_summary", task_dir / POST_CODE_MEMORY_SUMMARY_FILENAME)

    if branch == "improve":
        add(must, "anchor_parent_card", pinned_info.get("anchor_parent_card_path"), include_missing=True)
        add(must, "anchor_parent_solution", pinned_info.get("anchor_parent_code_path") or pinned_info.get("parent_abs_path") or pinned_info.get("best_abs_path"), include_missing=True)
        add(must, "anchor_parent_feedback", pinned_info.get("anchor_parent_feedback_path") or pinned_info.get("parent_validation_feedback_path"), include_missing=True)
        add(optional, "anchor_parent_diff", pinned_info.get("anchor_parent_diff_path"))
    elif branch == "debug":
        add(must, "debug_parent_card", pinned_info.get("debug_parent_card_path"), include_missing=True)
        add(must, "debug_parent_solution", pinned_info.get("debug_parent_code_path") or pinned_info.get("parent_abs_path"), include_missing=True)
        add(must, "debug_parent_feedback", pinned_info.get("debug_parent_validation_feedback_path") or pinned_info.get("parent_validation_feedback_path"), include_missing=True)
        add(optional, "debug_parent_diff", pinned_info.get("debug_parent_diff_path"))
    elif not independent_seed_draft:
        add(optional, "parent_or_best_solution", pinned_info.get("parent_abs_path") or pinned_info.get("best_abs_path"))
        add(optional, "parent_validation_feedback", pinned_info.get("parent_validation_feedback_path"))
    latest_eda_findings = pinned_info.get("latest_eda_findings_path")
    if latest_eda_findings:
        add(must, "latest_eda_findings", latest_eda_findings, include_missing=True)
    elif pinned_info.get("latest_eda_summary_path"):
        add(must, "legacy_eda_summary_fallback", pinned_info.get("latest_eda_summary_path"), include_missing=True)
    else:
        add(must, "latest_eda_findings", "<missing>", include_missing=True)
    if phase_name != "static_gate_repair":
        high_level_path = task_dir / "memory_bank" / HIGH_LEVEL_MEMORY_FILENAME
        if high_level_path.exists() and "high_level_memory" in must_classes:
            add(must, "high_level_memory", high_level_path)
        elif high_level_path.exists():
            add(optional, "high_level_memory", high_level_path)
    memory_bucket = must if non_draft else optional
    if not draft_static_repair:
        add(memory_bucket, "memory_card_index", task_dir / "memory_bank" / "card_index.jsonl", include_missing=non_draft)
        add(optional, "memory_cards_dir", task_dir / "memory_bank" / "cards")
        add(optional, "memory_diffs_dir", task_dir / "memory_bank" / "diffs")
    add(optional, "eda_insights_store", task_dir / "memory_bank" / "eda_insights.jsonl", include_missing=True)

    add(optional, "full_user_task_prompt", pinned_info.get("user_task_source_path"))
    portfolio_bucket = must if non_draft else optional
    if not draft_static_repair:
        add(portfolio_bucket, "portfolio_json", task_dir / V3_GRAPH_DIR / "portfolio.json", include_missing=non_draft)
    if not independent_seed_draft:
        history_entries = build_v4_history_context_paths(
            task_dir,
            branch=branch,
            intent=intent,
            best_path=pinned_info.get("best_code_path"),
            parent_path=pinned_info.get("parent_code_path"),
        )
        for entry in history_entries:
            label = str(entry.get("label") or "top_diverse_context")
            add(optional, label, entry.get("path"))
    if not draft_static_repair:
        add(optional, "rounds_ledger", task_dir / "memory_bank" / "rounds.jsonl")
        add(optional, "failure_ledger", task_dir / "memory_bank" / "failure_ledger.jsonl")

    latest_eda = str(latest_eda_findings or pinned_info.get("latest_eda_summary_path") or "")
    if latest_eda:
        eda_dir = Path(latest_eda).parent
        add(optional, "full_eda_findings_json", eda_dir / "eda_findings.json", include_missing=True)

    for path in pinned_info.get("retrieval_paths") or []:
        path_str = str(path)
        try:
            path_obj = Path(path_str).resolve()
            if path_obj.is_dir() and path_obj == task_dir:
                continue
            if path_obj.is_dir() and task_dir in path_obj.parents:
                continue
        except Exception:
            pass
        add_source_path(path_str, include_missing=True)

    routed_must_classes = {source_class_for_label(label) for label, _path, _shown in must}
    required_skill_labels = {
        "task_skill": "task_skill_source",
        "failure_prevention_skill": "failure_prevention_skill_source",
    }
    for source_class, label in required_skill_labels.items():
        if source_class in must_classes and source_class not in routed_must_classes:
            add(must, label, "<missing>", include_missing=True)

    purposes = {
        "debug_parent_card": "method/failure summary for the linked failed parent",
        "debug_parent_solution": "patch baseline for this debug round",
        "debug_parent_feedback": "authoritative failure evidence",
        "anchor_parent_card": "method/score summary for the improve anchor",
        "anchor_parent_solution": "patch baseline for this improve round",
        "anchor_parent_feedback": "validation evidence for the anchor",
        "anchor_parent_diff": "parent-vs-child method change signal",
        "current_round_solution": "authoritative implementation to repair without changing its modeling route",
        "current_context_readiness": "current-round evidence audit and pre-code implementation plan",
        "current_post_code_memory_summary": "current-round method summary to preserve during repair",
        "task_skill_source": "task-specific high-quality modeling prior and core modeling basis, especially for draft/improve; extract recipe, feature views, validation hints, and traps",
        "failure_prevention_skill_source": "general MLE contract checklist for schema, alignment, runtime, dependency, and output safety",
        "routed_skill_source": "routed skill source; inspect header/original source to determine task-skill or failure-prevention role",
        "latest_eda_findings": "latest complete human-readable EDA findings and coding handoff",
        "legacy_eda_summary_fallback": "legacy EDA handoff used only when no findings markdown exists",
        "full_eda_findings_json": "structured complement for exact EDA fields when needed",
        "eda_insights_store": "cumulative initial/deep EDA findings; read for recent contract updates",
        "high_level_memory": "task-level positive, negative, and debug-recovery lessons derived from method diffs",
        "memory_card_index": "card inventory; read index first, then specific cards only as needed",
        "portfolio_json": "current frontier state and candidate inventory",
        "full_user_task_prompt": "original long benchmark/task prompt",
    }

    def format_source_line(label: str, shown: str, *, required: bool) -> str:
        purpose = purposes.get(label, "")
        suffix = f" - {purpose}" if purpose else ""
        displayed_path = shown
        if required and shown != "<missing>" and label in {"task_skill_source", "failure_prevention_skill_source"}:
            displayed_path = f"**{shown}**"
        source = f"{label}: {displayed_path}"
        return f"- {source}{suffix}"

    lines = [
        "[CONTEXT SOURCE MAP]",
        "This is the single canonical list of local context paths. Ignore older path lists if present in archived source files.",
        f"task_dir: {task_dir}",
        f"context_acquisition_data_dir: {context_eda_data_dir or '<unset>'}",
        "Task-local paths below are relative to `task_dir`; external paths remain absolute.",
        "The data directory is read-only context for bounded schema/shape/file-contract probes; do not copy its absolute path into solution.py.",
        "",
        "Must inspect before coding:",
    ]
    for label, _path, shown in must:
        lines.append(format_source_line(label, shown, required=True))
    lines.extend([
        "",
        "Pinned inline sections are authoritative and already available in this prompt:",
        "- [PINNED HARD TASK CONTRACT] when present",
        "- [ROUND DIRECTIVE]",
        "",
        "Optional expansion paths:",
    ])
    for label, _path, shown in optional:
        lines.append(format_source_line(label, shown, required=False))

    section = "\n".join(lines)
    return section, {
        "task_dir": str(task_dir),
        "must_inspect": [{"label": label, "path": path, "prompt_path": shown} for label, path, shown in must],
        "optional": [{"label": label, "path": path, "prompt_path": shown} for label, path, shown in optional],
        "context_acquisition_data_dir": context_eda_data_dir,
        "chars": len(section),
        "tokens": prompt_token_count(section),
    }


def build_v35_context_first_protocol(pinned_info: dict[str, Any]) -> str:
    """Prompt the coding agent to read local context before writing solution.py."""
    metadata = pinned_info.get("metadata") if isinstance(pinned_info.get("metadata"), dict) else {}
    context_eda_data_dir = str(
        pinned_info.get("context_eda_data_dir")
        or metadata.get("context_eda_data_dir")
        or metadata.get("data_dir")
        or ""
    ).strip()
    lines = [
        "[CONTEXT-FIRST PROTOCOL]",
        "Before writing or editing `solution.py`, perform a short context acquisition pass.",
        "First inspect every path under `Must inspect before coding` in `[CONTEXT SOURCE MAP]`.",
        f"Data-contract probe directory: {context_eda_data_dir or '`CONTEXT_EDA_DATA_DIR` if set by the harness'}. Treat it as read-only and never hardcode it in `solution.py`.",
        "You may run bounded read-only probes only to confirm file names, headers, schemas, shapes, tiny samples, submission alignment, label/source mapping, and failure-causing parser contracts. Acceptable probes are small `ls/find -maxdepth`, `head`, metadata reads, or tiny Python snippets that read limited rows/files and write no outputs.",
        f"Do not run `solution.py`, validation, sandbox jobs, training, EDA scripts, notebooks, model fitting, hyperparameter searches, full-directory scans, recursive media decoding, prediction-cache generation, internet access, or writes outside `context_readiness.md`, `solution.py`, and `{POST_CODE_MEMORY_SUMMARY_FILENAME}`.",
        "Do not edit `memory_bank/eda_insights.jsonl` or EDA findings files directly. If you use deep EDA, write a valid JSON object inside a fenced `json` block in `context_readiness.md`; after sandbox feedback the framework will append it to the EDA insight store and task-local initial EDA findings markdown.",
        "",
        "Treat `[ROUND DIRECTIVE]` as the single authority for this coding round.",
        "Use `top_diverse_*` optional paths when the directive involves improve, replacement, blend, plateau diagnosis, or when prior implementation details would change the plan.",
        "Use other optional expansion paths when the pinned contract, parent code, feedback, EDA findings/source-map facts, or memory leave an ambiguity.",
        "When scanning DATA_DIR, name discovered input-file mappings `input_paths`, `data_files`, or `source_files`; do not use names that imply reusable side outputs, cached products, or cross-round files.",
        "",
        "Then write `context_readiness.md` as the final pre-code plan and audit with these bullets. Keep this file pre-code only; do not append post-code memory fields here:",
        "- files inspected",
        "- submission unit and format",
        "- label source and split meaning",
        "- method_family: <stable concrete modeling family, e.g. sparse_text_logreg, descriptor_svc, cnn_image, audio_segment_mil, tabular_gbdt; never use draft/improve/debug/portfolio/control labels>",
        "- branch state, anchor/debug parent behavior, and any imported node ideas",
        "- score_feedback response and material-gain rationale when score feedback is present",
        "- deep EDA trigger, files checked, data-contract confirmations, confidence, and coding implication; write `not used` if no deep EDA was needed",
        "- fenced JSON deep EDA insight when used, with keys: source=`deep_eda`, trigger, files_checked, commands_or_reads, finding, confidence, coding_implication",
        "- modeling route and feature/data strategy",
        "- validation or sanity-check strategy",
        "- score-first path and heavy-tier order",
        "- runtime fallback and dependency downgrade plan",
        "- stdout diagnostic and candidate-comparison plan",
        "- known failure traps to avoid",
        "- exact implementation plan for this round",
        "",
        f"After writing `solution.py`, write `{POST_CODE_MEMORY_SUMMARY_FILENAME}` as the code-after memory payload for memory card/diff artifacts:",
        "- Start with heading `# Post-Code Memory Summary`.",
        "- card_method_summary: 1-2 dense English sentences describing the implemented solution.py method itself",
        "- card_method_profile: 3-5 concise English sentences covering feature/representation views, model family, validation/selection logic, runtime fallback, and main reuse/risk signal",
        "- card_core_components: comma-separated concrete components actually implemented",
        "- card_reuse_risk: what future rounds should reuse or avoid from this implementation",
        "- diff_action: if this round patches a parent/anchor, state the concrete code/logic changes; otherwise write `none`",
        "- diff_reason: if this round patches a parent/anchor, state why those changes were made; otherwise write `none`",
        "",
        "Deep EDA is an incremental detail patch to initial EDA, not a replacement. Do not repeat full dataset inventory; inspect only the smallest files/rows needed to resolve the current ambiguity or failure.",
        "If a mandatory file is missing, record that fact and continue using the pinned hard contract. If a retrieved file conflicts with pinned hard contract or source-map EDA facts, obey the pinned hard contract and mention the conflict.",
    ]
    return "\n".join(lines)


def _prompt_scalar(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _read_memory_card_fields(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    wanted = {"score", "method_summary"}
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*[-*]\s*([a-z_]+)\s*:\s*(.*)$", line, flags=re.IGNORECASE)
        if not match:
            continue
        key = match.group(1).lower()
        if key in wanted and match.group(2).strip():
            fields[key] = match.group(2).strip()
    return fields


def _compact_parent_memory_card(parent: dict[str, Any], card_path: str) -> str:
    if not parent:
        return ""
    card = _read_memory_card_fields(card_path)
    return "\n".join([
        "[PARENT MEMORY CARD]",
        f"- round: {parent.get('round') if parent.get('round') is not None else '-'}",
        f"- score: {parent.get('score') if parent.get('score') is not None else card.get('score') or '-'}",
        f"- method_summary: {card.get('method_summary') or 'unavailable'}",
    ])


def _draft_card_signature(row: dict[str, Any]) -> str:
    family = _prompt_scalar(row.get("method_family") or "unknown", 80).lower()
    keywords = row.get("method_keywords") if isinstance(row.get("method_keywords"), list) else []
    controls = {"draft", "initial_seed", "required_seed", "plateau_new_seed", "new_seed_score_first"}
    useful = [re.sub(r"\W+", "_", str(item).lower()).strip("_") for item in keywords]
    useful = [item for item in useful if item and item not in controls][:4]
    return "|".join([family, *useful])


def _select_prior_draft_cards(rows: list[dict[str, Any]], higher_is_better: bool, limit: int = 4) -> list[dict[str, Any]]:
    rows = sorted(rows, key=lambda row: int(row.get("round") if row.get("round") is not None else -1))
    if len(rows) <= limit:
        return rows
    selected: dict[int, dict[str, Any]] = {}

    def add(row: dict[str, Any]) -> None:
        try:
            round_num = int(row.get("round"))
        except Exception:
            return
        if round_num in selected or len(selected) < limit:
            selected[round_num] = row

    scored = [row for row in rows if isinstance(row.get("score"), (int, float))]
    if scored:
        add((max if higher_is_better else min)(scored, key=lambda row: float(row["score"])))
    add(rows[-1])
    for row in reversed(rows):
        if str(row.get("status") or "").lower() not in {"success", "completed"}:
            add(row)
    seen_signatures = {_draft_card_signature(row) for row in selected.values()}
    for row in reversed(rows):
        signature = _draft_card_signature(row)
        if signature not in seen_signatures:
            add(row)
            seen_signatures.add(signature)
    for row in [rows[0], *reversed(rows)]:
        if len(selected) >= limit:
            break
        add(row)
    return sorted(selected.values(), key=lambda row: int(row.get("round") if row.get("round") is not None else -1))


def _build_prior_draft_memory(
    task_dir: Path,
    current_round: int,
    higher_is_better: bool,
    frozen: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    if frozen is not None:
        rows = frozen.get("cards") if isinstance(frozen.get("cards"), list) else []
    else:
        indexed = _load_jsonl(task_dir / "memory_bank" / "card_index.jsonl")
        rows = []
        for row in indexed:
            try:
                round_num = int(row.get("round") if row.get("round") is not None else -1)
            except (TypeError, ValueError):
                continue
            if str(row.get("branch") or "") == "draft" and round_num < current_round:
                rows.append(row)
        if not rows:
            for row in _load_jsonl(task_dir / "memory_bank" / "rounds.jsonl"):
                try:
                    round_num = int(row.get("round") if row.get("round") is not None else -1)
                except (TypeError, ValueError):
                    continue
                if normalize_branch_name(str(row.get("branch") or "")) != "draft" or round_num >= current_round:
                    continue
                summary = row.get("round_summary") if isinstance(row.get("round_summary"), dict) else {}
                rows.append({
                    "round": round_num,
                    "status": row.get("status") or (row.get("validation") or {}).get("status"),
                    "score": _round_score(row),
                    "method_family": row.get("effective_method_family") or row.get("method_family") or summary.get("method_family"),
                    "method_keywords": summary.get("core_components") if isinstance(summary.get("core_components"), list) else [],
                    "card_path": row.get("memory_card_path"),
                })
    selected = _select_prior_draft_cards(rows, higher_is_better, limit=4)
    if not selected:
        return "[PRIOR DRAFT MEMORY]\n- no prior draft cards", []
    lines = ["[PRIOR DRAFT MEMORY]"]
    paths: list[str] = []
    for row in selected:
        card_path = str(row.get("card_path") or "").strip()
        resolved_card_path = ""
        if card_path:
            path = Path(card_path)
            resolved_card_path = str(path if path.is_absolute() else task_dir / path)
            paths.append(card_path)
        card = _read_memory_card_fields(resolved_card_path)
        summary = row.get("method_summary") or card.get("method_summary") or "unavailable"
        lines.append(
            f"- round: {int(row.get('round') or 0)}; "
            f"score: {row.get('score') if row.get('score') is not None else '-'}; "
            f"method_summary: {summary}"
        )
    return "\n".join(lines), paths


def _round_score(row: dict[str, Any]) -> float | None:
    score = row.get("score")
    if score is None and isinstance(row.get("validation"), dict):
        score = row["validation"].get("score")
    return float(score) if isinstance(score, (int, float)) else None


def _build_round_history(rows: list[dict[str, Any]], parent_round: int | None, higher_is_better: bool) -> str:
    rows = sorted(rows, key=lambda row: int(row.get("round") if row.get("round") is not None else -1))
    if len(rows) > 24:
        selected: dict[int, dict[str, Any]] = {}
        mandatory = [rows[0], *rows[-8:]]
        best_score: float | None = None
        transitions: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        branch_changes: list[dict[str, Any]] = []
        previous_state = ""
        for row in rows:
            round_value = int(row.get("round") if row.get("round") is not None else -1)
            if parent_round is not None and round_value == parent_round:
                mandatory.append(row)
            score = _round_score(row)
            if score is not None and (best_score is None or (score > best_score if higher_is_better else score < best_score)):
                best_score = score
                transitions.append(row)
            if str(row.get("status") or "") not in {"success", "completed"}:
                failures.append(row)
            state = f"{row.get('branch')}/{row.get('branch_state')}"
            if previous_state and state != previous_state:
                branch_changes.append(row)
            previous_state = state
        for row in mandatory + list(reversed(transitions)) + list(reversed(failures)) + list(reversed(branch_changes)) + list(reversed(rows)):
            if len(selected) >= 24:
                break
            selected[int(row.get("round") if row.get("round") is not None else -1)] = row
        shown = sorted(selected.values(), key=lambda row: int(row.get("round") if row.get("round") is not None else -1))
    else:
        shown = rows
    lines = ["[ROUND HISTORY]", "round | branch/state | status | score | method_family | commit | marker"]
    best_score = None
    for row in rows:
        score = _round_score(row)
        if score is not None and (best_score is None or (score > best_score if higher_is_better else score < best_score)):
            best_score = score
        if row not in shown:
            continue
        round_value = int(row.get("round") if row.get("round") is not None else -1)
        marker = "parent" if parent_round is not None and round_value == parent_round else ("best" if score is not None and score == best_score else "-")
        family = _prompt_scalar(row.get("method_family") or row.get("effective_method_family") or "-", 48)
        if family == "agent_selected_after_context":
            family = "-"
        lines.append(
            f"{round_value} | {_prompt_scalar(row.get('branch') or '-', 16)}/{_prompt_scalar(row.get('branch_state') or '-', 24)} | "
            f"{_prompt_scalar(row.get('status') or '-', 32)} | {format(score, '.6g') if score is not None else '-'} | "
            f"{family} | {str(row.get('commit') or row.get('commit_hash') or '-')[:8]} | {marker}"
        )
    omitted = max(0, len(rows) - len(shown))
    if omitted:
        lines.append(f"Omitted historical rounds: {omitted}")
    return select_complete_lines_under_limit("\n".join(lines), 3200)[0]


def _build_score_context(score_feedback: dict[str, Any], branch: str, branch_state: str) -> str:
    if not score_feedback:
        return ""
    lines = ["[SCORE CONTEXT]"]
    latest = score_feedback.get("latest") if isinstance(score_feedback.get("latest"), dict) else {}
    incumbent = score_feedback.get("best") if isinstance(score_feedback.get("best"), dict) else {}
    same_identity = bool(latest and incumbent and (
        (latest.get("commit") and latest.get("commit") == incumbent.get("commit"))
        or (
            latest.get("round") is not None
            and latest.get("round") == incumbent.get("round")
        )
    ))
    rows = [("latest_scored", latest)]
    if not same_identity:
        rows.append(("incumbent", incumbent))
    for label, row in rows:
        if not row:
            continue
        parts = [
            f"round={row.get('round') if row.get('round') is not None else '-'}",
            f"commit={str(row.get('commit') or '-')[:8]}",
            f"score={row.get('score') if row.get('score') is not None else '-'}",
            f"family={_prompt_scalar(row.get('method_family') or 'unknown', 80)}",
        ]
        for optional in ("selected_candidate", "local_metric", "best_local_score", "selected_local_score"):
            if row.get(optional) not in {None, ""}:
                parts.append(f"{optional}={_prompt_scalar(row.get(optional), 80)}")
        if row.get("large_local_validation_gap"):
            parts.append(f"local_validation_gap={row.get('local_validation_gap')}")
        lines.append(f"{label}: " + "; ".join(parts))
    if same_identity:
        lines.append("latest_is_incumbent: true")
    for key in ("latest_delta_vs_previous_best", "latest_delta_vs_current_best", "material_tolerance"):
        if score_feedback.get(key) is not None:
            lines.append(f"{key}: {score_feedback[key]}")
    if branch == "debug":
        lines.append("required_response: prioritize the linked failure evidence; do not switch routes for score stagnation in this repair round.")
    elif branch_state == "final_audit":
        lines.append("required_response: audit the validation-best implementation for runtime, schema, submission, and fallback correctness; do not start a new route.")
    else:
        issues = score_feedback.get("issues") if isinstance(score_feedback.get("issues"), list) else []
        for issue in issues[:3]:
            if not isinstance(issue, dict):
                continue
            lines.append(f"issue: type={_prompt_scalar(issue.get('type'), 80)}; severity={_prompt_scalar(issue.get('severity'), 24)}; detail={_prompt_scalar(issue.get('detail'), 260)}")
        responses = score_feedback.get("required_response") if isinstance(score_feedback.get("required_response"), list) else []
        for response in responses[:2]:
            text = _prompt_scalar(response, 360)
            if any(token in text.lower() for token in ("nb-svm", "linearsvc", "text views", "vocabulary variants")):
                text = "Compare additional affordable variants appropriate to the chosen task and method family before relying on blends."
            lines.append(f"required_response: {text}")
    return select_complete_lines_under_limit("\n".join(lines), 1200)[0]


def _build_branch_memory_section(
    *,
    task_dir: Path,
    branch_decision: dict[str, Any],
    branch: str,
    parent: dict[str, Any],
    parent_card_path: str,
    round_index: int,
    higher_is_better: bool,
) -> tuple[str, list[str]]:
    """Route exactly one branch-specific memory section into Part 3."""
    if branch == "draft":
        frozen = branch_decision.get("draft_prior_memory") if isinstance(branch_decision.get("draft_prior_memory"), dict) else None
        return _build_prior_draft_memory(
            task_dir,
            round_index,
            higher_is_better,
            frozen=frozen,
        )
    if branch in {"debug", "improve"}:
        return _compact_parent_memory_card(parent, parent_card_path), []
    raise ValueError(f"unsupported branch for Part 3 memory routing: {branch}")


def _build_round_context_packet(
    task_dir: Path,
    metadata: dict[str, Any],
    branch_decision: dict[str, Any],
    branch: str,
    parent: dict[str, Any],
    parent_card_path: str,
    all_rounds: list[dict[str, Any]],
    phase_name: str = "coding",
) -> tuple[str, list[str]]:
    branch = normalize_branch_name(branch)
    state = str(branch_decision.get("branch_state") or branch_decision.get("search_state") or "unknown")
    round_index = int(branch_decision.get("round") or len(all_rounds))
    higher_is_better = bool(metadata.get("higher_is_better", True))
    runtime_profile = str(branch_decision.get("runtime_profile") or RUNTIME_PROFILE_STANDARD)
    runtime_control = branch_decision.get("runtime_control") if isinstance(branch_decision.get("runtime_control"), dict) else {}
    strict_score_first = runtime_control.get("strict_score_first_required")
    if strict_score_first is None:
        strict_score_first = runtime_profile in {
            RUNTIME_PROFILE_NEW_SEED_SCORE_FIRST,
            RUNTIME_PROFILE_TIMEOUT_RECOVERY,
            RUNTIME_PROFILE_HIGH_RISK_PARENT,
        }
    lines = [
        "[ROUND DIRECTIVE]",
        f"round_index: {round_index}",
        f"branch: {branch}",
        f"state: {state}",
        f"reason: {_prompt_scalar(branch_decision.get('branch_reason') or branch_decision.get('reason') or 'unknown', 300)}",
        f"runtime_profile: {_prompt_scalar(runtime_profile, 80)}",
        f"strict_score_first_required: {str(bool(strict_score_first)).lower()}",
        f"metric_direction: {'higher' if higher_is_better else 'lower'}",
    ]
    draft_static_repair = branch == "draft" and phase_name == "static_gate_repair"
    if draft_static_repair:
        lines.append("action: repair the current-round solution only; preserve its modeling route and fix the reported blocker without consulting historical implementations.")
    elif branch == "draft":
        lines.append("action: create an independent strong seed with no parent or code prefill; use prior draft memory only to avoid repeating an existing implementation.")
    elif branch == "debug":
        lines.append("action: repair exactly the linked failed parent and preserve its method family unless the failure evidence proves it cannot run.")
    elif state == "final_audit":
        lines.append("action: audit and safely finalize the validation-best parent; do not start a new modeling route.")
    else:
        lines.append("action: patch the validation-best parent and make one evidence-backed improvement.")
    sections = ["\n".join(lines)]
    if draft_static_repair:
        memory_section, draft_paths = "", []
    else:
        memory_section, draft_paths = _build_branch_memory_section(
            task_dir=task_dir,
            branch_decision=branch_decision,
            branch=branch,
            parent=parent,
            parent_card_path=parent_card_path,
            round_index=round_index,
            higher_is_better=higher_is_better,
        )
    if memory_section:
        sections.append(memory_section)
    score_context = _build_score_context(
        branch_decision.get("score_feedback") if isinstance(branch_decision.get("score_feedback"), dict) else {},
        branch,
        state,
    )
    if score_context:
        sections.append(score_context)
    if not draft_static_repair:
        parent_round = parent.get("round") if isinstance(parent.get("round"), int) else None
        sections.append(_build_round_history(all_rounds, parent_round, higher_is_better))
    budget = branch_decision.get("budget") if isinstance(branch_decision.get("budget"), dict) else {}
    remaining = budget.get("remaining_budget")
    validation_timeout = branch_decision.get("validation_timeout_seconds") or remaining
    sections.append("\n".join([
        "[EXTERNAL VALIDATION TIMEOUT]",
        f"validation_timeout_seconds: {validation_timeout if validation_timeout is not None else '-'}",
        f"remaining_sandbox_runtime_seconds: {remaining if remaining is not None else '-'}",
        "The framework enforces this single timeout externally, while task accounting charges only actual sandbox runtime. It is read-only and not negotiable. Do not request a runtime budget in context_readiness.md, copy this value into solution.py, or implement internal timers, deadlines, remaining-time guards, or budget exceptions. Choose a statically bounded workload that can complete and write submission.csv before the external timeout.",
    ]))
    return "\n\n".join(section for section in sections if section), draft_paths


def build_pinned_runtime_context(
    work_dir: Path,
    metadata: dict[str, Any],
    refinement_context: str | None,
    phase_name: str,
) -> tuple[str, dict[str, Any]]:
    """
    Build the non-droppable runtime packet.

    Older versions used a global middle truncation pass, which often removed incumbent best
    code paths, memory, and EDA. This packet is packed before lower-priority
    sections so search-critical state survives even under tight prompt caps.
    """
    task_dir = resolve_task_work_dir(work_dir)
    raw_skill_sources = metadata.get("skill_sources")
    if isinstance(raw_skill_sources, (str, Path)):
        raw_skill_sources = [raw_skill_sources]
    retrieval_paths = [
        str(path).strip()
        for path in raw_skill_sources or []
        if isinstance(path, (str, Path)) and str(path).strip()
    ] if isinstance(raw_skill_sources, (list, tuple)) else []
    branch_decision = safe_load_json_file(task_dir / "index" / "current_branch_decision.json")
    branch_decision = apply_latest_failed_parent_fallback(task_dir, branch_decision)
    best_candidate = safe_load_json_file(task_dir / "index" / "best_validation_candidate.json")

    branch = metadata.get("branch") or branch_decision.get("branch")
    runtime_trigger_intent = branch_decision.get("search_intent")
    search_intent = metadata.get("search_intent") or runtime_trigger_intent
    search_operator = metadata.get("search_operator") or branch_decision.get("search_operator") or {}
    if not isinstance(search_operator, dict):
        search_operator = {}
    if phase_name == "early_eda" and metadata.get("slim_eda_prompt"):
        compact_lines = [
            "[PINNED RUNTIME CONTROL - DO NOT TRUNCATE]",
            f"Task: {metadata.get('task_name', task_dir.name)}",
            f"Phase: {phase_name}",
            f"Task directory: {task_dir}",
            f"Local EDA data directory: {metadata.get('data_dir', '')}",
            f"Higher is better: {metadata.get('higher_is_better', 'unknown')}",
            "Early EDA scope: inspect local public files and fixed-EDA output paths, then write a task-fact handoff. Do not use branch-state or method-family assumptions in this phase.",
        ]
        pinned_context = "\n".join(compact_lines)
        info = {
            "task_dir": str(task_dir),
            "phase_name": phase_name,
            "metadata": {
                "task_name": metadata.get("task_name"),
                "cpu_gpu": metadata.get("cpu_gpu"),
                "higher_is_better": metadata.get("higher_is_better"),
                "data_dir": metadata.get("data_dir"),
            },
            "context_eda_data_dir": metadata.get("context_eda_data_dir") or metadata.get("data_dir"),
            "branch": branch,
            "search_intent": search_intent,
            "runtime_trigger_intent": runtime_trigger_intent,
            "search_operator": search_operator,
            "operator_name": search_operator.get("name"),
            "operator_family": search_operator.get("family") or search_operator.get("method_family"),
            "portfolio_state": {},
            "portfolio_action": branch_decision.get("portfolio_action"),
            "portfolio_slot": compact_portfolio_slot(branch_decision.get("portfolio_slot") or {}),
            "best_commit": "",
            "best_code_path": "",
            "best_abs_path": "",
            "best_code_exists": False,
            "parent_commit": "",
            "parent_code_path": "",
            "parent_abs_path": "",
            "parent_code_exists": False,
            "parent_validation_feedback_path": "",
            "parent_validation_feedback_exists": False,
            "independent_seed_draft": True,
            "debug_parent_round": branch_decision.get("debug_parent_round"),
            "debug_parent_commit": branch_decision.get("debug_parent_commit"),
            "debug_parent_code_path": "",
            "debug_parent_validation_feedback_path": "",
            "repair_seed_id": branch_decision.get("repair_seed_id"),
            "repair_parent_method_family": branch_decision.get("repair_parent_method_family"),
            "latest_eda_summary_path": "",
            "latest_eda_summary_exists": False,
            "latest_eda_findings_path": "",
            "latest_eda_findings_exists": False,
            "latest_eda_source_kind": "missing",
            "incumbent_prefill": {},
            "source_presence": {
                "memory": False,
                "latest_eda_summary": False,
                "latest_eda_findings": False,
                "round_directive": False,
                "integrated_context_first_planning": False,
            },
            "inline_presence": {
                "deep_eda_summary": False,
                "early_eda_summary": False,
            },
            "pinned_loss_records": [],
            "retrieval_paths": retrieval_paths,
            "user_task_source_path": metadata.get("user_task_source_path"),
            "chars": len(pinned_context),
        }
        return pinned_context, info
    branch_name = normalize_branch_name(str(branch or ""))
    parent_binding = branch_decision.get("parent_binding") if isinstance(branch_decision.get("parent_binding"), dict) else {}
    anchor_parent = branch_decision.get("anchor_parent") if isinstance(branch_decision.get("anchor_parent"), dict) else {}
    debug_parent = branch_decision.get("debug_parent") if isinstance(branch_decision.get("debug_parent"), dict) else {}
    if parent_binding:
        if branch_name == "improve":
            anchor_parent = parent_binding
        elif branch_name == "debug":
            debug_parent = parent_binding
    elif branch_name == "debug":
        parent_binding = debug_parent
    elif branch_name == "improve":
        parent_binding = anchor_parent
    if branch_name == "draft":
        parent_binding = {}
        anchor_parent = {}
        debug_parent = {}
    parent_commit = (
        parent_binding.get("commit")
        or branch_decision.get("parent_commit")
        or branch_decision.get("best_local_cv_commit")
        or best_candidate.get("commit_hash")
        or best_candidate.get("commit")
    )
    if branch_name == "improve" and anchor_parent:
        parent_commit = anchor_parent.get("commit") or parent_commit
    if branch_name == "debug" and debug_parent:
        parent_commit = debug_parent.get("commit") or parent_commit
    best_commit = best_candidate.get("commit_hash") or best_candidate.get("commit") or branch_decision.get("best_local_cv_commit")
    best_code_path = best_candidate.get("code_path")
    parent_code_path = str(branch_decision.get("parent_code_path") or "").strip()
    if not parent_code_path and anchor_parent:
        parent_code_path = str(anchor_parent.get("code_path") or "").strip()
    if not parent_code_path and debug_parent:
        parent_code_path = str(debug_parent.get("code_path") or "").strip()
    if not parent_code_path and parent_commit:
        parent_code_path = f"commits/{parent_commit}/solution.py"

    def resolve_prompt_path(path_value: Any) -> str:
        text = str(path_value or "").strip()
        if not text:
            return ""
        path = Path(text)
        return str((path if path.is_absolute() else task_dir / path).resolve())

    best_abs_path = resolve_prompt_path(best_code_path)
    parent_abs_path = resolve_prompt_path(parent_code_path)
    parent_validation_feedback_path = str(branch_decision.get("parent_validation_feedback_path") or "").strip()
    if not parent_validation_feedback_path and anchor_parent:
        parent_validation_feedback_path = str(anchor_parent.get("feedback_path") or "").strip()
    if not parent_validation_feedback_path and debug_parent:
        parent_validation_feedback_path = str(debug_parent.get("feedback_path") or "").strip()
    if not parent_validation_feedback_path and parent_commit:
        parent_validation_feedback_path = str((task_dir / "commits" / str(parent_commit) / "validation_feedback.txt").resolve())
    elif parent_validation_feedback_path:
        parent_validation_feedback_path = resolve_prompt_path(parent_validation_feedback_path)
    latest_eda_findings_path = find_latest_eda_findings_path(task_dir)
    latest_eda_summary_path = find_latest_eda_summary_path(task_dir)
    best_code_exists = bool(best_abs_path and Path(best_abs_path).exists())
    parent_code_exists = bool(parent_abs_path and Path(parent_abs_path).exists())
    parent_validation_feedback_exists = bool(parent_validation_feedback_path and Path(parent_validation_feedback_path).exists())
    independent_seed_draft = branch_name == "draft"
    if independent_seed_draft:
        parent_commit = ""
        parent_code_path = ""
        parent_abs_path = ""
        parent_code_exists = False
        parent_validation_feedback_path = ""
        parent_validation_feedback_exists = False
    anchor_parent_card_path = resolve_prompt_path(anchor_parent.get("memory_card_path") or anchor_parent.get("card_path")) if anchor_parent else ""
    anchor_parent_diff_path = resolve_prompt_path(anchor_parent.get("diff_path") or anchor_parent.get("memory_diff_path")) if anchor_parent else ""
    debug_parent_card_path = resolve_prompt_path(debug_parent.get("memory_card_path") or debug_parent.get("card_path")) if debug_parent else ""
    debug_parent_diff_path = resolve_prompt_path(debug_parent.get("diff_path") or debug_parent.get("memory_diff_path")) if debug_parent else ""
    latest_eda_summary_exists = bool(latest_eda_summary_path and latest_eda_summary_path.exists())
    latest_eda_findings_exists = bool(latest_eda_findings_path and latest_eda_findings_path.exists())
    latest_eda_source_kind = (
        "findings"
        if latest_eda_findings_exists
        else "summary_fallback"
        if latest_eda_summary_exists
        else "missing"
    )
    incumbent_prefill = metadata.get("incumbent_prefill") if isinstance(metadata.get("incumbent_prefill"), dict) else {}
    parent_card_path = debug_parent_card_path if branch_name == "debug" else anchor_parent_card_path
    all_rounds = _load_jsonl(memory_bank_path(task_dir, "rounds.jsonl"))
    pinned_context, prior_draft_card_paths = _build_round_context_packet(
        task_dir=task_dir,
        metadata=metadata,
        branch_decision=branch_decision,
        branch=branch_name,
        parent=parent_binding,
        parent_card_path=parent_card_path,
        all_rounds=all_rounds,
        phase_name=phase_name,
    )
    source_presence = {
        "memory": bool((task_dir / "memory_bank").exists()),
        "latest_eda_summary": latest_eda_summary_exists,
        "latest_eda_findings": latest_eda_findings_exists,
        "round_directive": True,
        "integrated_context_first_planning": False,
    }
    inline_presence = {
        "deep_eda_summary": False,
        "early_eda_summary": False,
    }

    info = {
        "task_dir": str(task_dir),
        "phase_name": phase_name,
        "metadata": {
            "task_name": metadata.get("task_name"),
            "cpu_gpu": metadata.get("cpu_gpu"),
            "higher_is_better": metadata.get("higher_is_better"),
            "data_dir": metadata.get("data_dir"),
        },
        "context_eda_data_dir": metadata.get("context_eda_data_dir") or metadata.get("data_dir"),
        "branch": branch,
        "branch_state": branch_decision.get("branch_state"),
        "runtime_profile": branch_decision.get("runtime_profile"),
        "parent_binding": parent_binding,
        "source_policy": branch_decision.get("source_policy") if isinstance(branch_decision.get("source_policy"), dict) else {},
        "best_commit": best_commit,
        "best_code_path": best_code_path,
        "best_abs_path": best_abs_path,
        "best_code_exists": best_code_exists,
        "parent_commit": parent_commit,
        "parent_code_path": parent_code_path,
        "parent_abs_path": parent_abs_path,
        "parent_code_exists": parent_code_exists,
        "parent_validation_feedback_path": parent_validation_feedback_path,
        "parent_validation_feedback_exists": parent_validation_feedback_exists,
        "anchor_parent": anchor_parent,
        "anchor_parent_card_path": anchor_parent_card_path,
        "anchor_parent_diff_path": anchor_parent_diff_path,
        "anchor_parent_code_path": parent_code_path if branch_name == "improve" else "",
        "anchor_parent_feedback_path": parent_validation_feedback_path if branch_name == "improve" else "",
        "independent_seed_draft": independent_seed_draft,
        "debug_parent_round": debug_parent.get("round"),
        "debug_parent_commit": debug_parent.get("commit"),
        "debug_parent": debug_parent,
        "debug_parent_card_path": debug_parent_card_path,
        "debug_parent_diff_path": debug_parent_diff_path,
        "debug_parent_code_path": debug_parent.get("code_path") if branch_name == "debug" else "",
        "debug_parent_validation_feedback_path": debug_parent.get("feedback_path") if branch_name == "debug" else "",
        "repair_seed_id": branch_decision.get("repair_seed_id"),
        "repair_parent_method_family": branch_decision.get("repair_parent_method_family"),
        "latest_eda_summary_path": str(latest_eda_summary_path) if latest_eda_summary_path else "",
        "latest_eda_summary_exists": latest_eda_summary_exists,
        "latest_eda_findings_path": str(latest_eda_findings_path) if latest_eda_findings_path else "",
        "latest_eda_findings_exists": latest_eda_findings_exists,
        "latest_eda_source_kind": latest_eda_source_kind,
        "incumbent_prefill": incumbent_prefill,
        "source_presence": source_presence,
        "inline_presence": inline_presence,
        "prior_draft_card_paths": prior_draft_card_paths,
        "retrieval_paths": retrieval_paths,
        "user_task_source_path": metadata.get("user_task_source_path"),
        "chars": len(pinned_context),
    }
    return pinned_context, info
