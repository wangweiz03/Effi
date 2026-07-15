from __future__ import annotations

from .common import *
from .constants import *

def _v41_part(title: str, description: str, sections: list[str]) -> str:
    body = "\n\n".join(section.strip() for section in sections if str(section or "").strip())
    if not body:
        return ""
    return "\n\n".join([f"# {title}", description.strip(), body]).strip()


def _round_context_token_counts(text: str) -> dict[str, int]:
    markers = {
        "[ROUND DIRECTIVE]": "directive",
        "[PARENT MEMORY CARD]": "parent_memory",
        "[PRIOR DRAFT MEMORY]": "prior_draft_memory",
        "[SCORE CONTEXT]": "score_context",
        "[ROUND HISTORY]": "round_history",
        "[DRAFT WORKLOAD CEILING]": "draft_workload_ceiling",
        "[OBSERVED RUNTIME EVIDENCE]": "observed_runtime_evidence",
        "[EXTERNAL VALIDATION TIMEOUT]": "external_validation_timeout",
    }
    sections: dict[str, list[str]] = {}
    current = "unclassified"
    for line in str(text or "").splitlines():
        current = markers.get(line.strip(), current)
        sections.setdefault(current, []).append(line)
    return {
        name: prompt_token_count("\n".join(lines))
        for name, lines in sections.items()
        if any(line.strip() for line in lines)
    }


V50_PROMPT_HEADING_LEVELS = {
    "[SYSTEM INSTRUCTIONS]": 2,
    "[PINNED SANDBOX ENVIRONMENT]": 2,
    "[CONTEXT-FIRST PROTOCOL]": 2,
    "[OUTPUT CONTRACT]": 2,
    "[PINNED HARD TASK CONTRACT]": 2,
    "[USER TASK]": 2,
    "[ROUND DIRECTIVE]": 2,
    "[PARENT MEMORY CARD]": 2,
    "[PRIOR DRAFT MEMORY]": 2,
    "[SCORE CONTEXT]": 2,
    "[ROUND HISTORY]": 2,
    "[DRAFT WORKLOAD CEILING]": 2,
    "[OBSERVED RUNTIME EVIDENCE]": 2,
    "[EXTERNAL VALIDATION TIMEOUT]": 2,
    "[CONTEXT SOURCE MAP]": 2,
    "[CURRENT FRAMEWORK USER CONTRACT]": 3,
    "[TASK DESCRIPTION]": 3,
    "[METADATA]": 3,
    "[TASK_CONTRACT]": 3,
    "[VALIDATION_CONTRACT]": 3,
    "[AVOID_RULES]": 3,
    "[PINNED RUNTIME RETRIEVAL]": 3,
}


def _promote_prompt_heading_markers(text: str) -> str:
    """Render standalone prompt markers as Markdown headings while preserving markers."""
    out: list[str] = []
    in_fence = False
    marker_pattern = re.compile(r"^\[[A-Z0-9][A-Z0-9 _/\-]*\]$")
    markdown_heading_pattern = re.compile(r"^(#{1,6})(\s+.+)$")
    current_container_level = 0
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and line.startswith("# PART "):
            current_container_level = 1
            out.append(line)
            continue
        if not in_fence and marker_pattern.match(stripped):
            level = V50_PROMPT_HEADING_LEVELS.get(stripped, 3)
            current_container_level = level
            out.append(f"{'#' * level} {stripped}")
            continue
        heading_match = markdown_heading_pattern.match(line)
        if not in_fence and heading_match and current_container_level:
            level = len(heading_match.group(1))
            if level <= current_container_level:
                level = min(current_container_level + 1, 6)
                out.append("#" * level + heading_match.group(2))
                continue
            out.append(line)
        else:
            out.append(line)
    return "\n".join(out).strip()


def pack_prompt_with_pinned_runtime(
    system_prompt: str,
    pinned_context: str,
    pinned_info: dict[str, Any],
    skill_context: str | None,
    prompt_parts: list[str],
    phase_name: str,
    prompt_cap: int,
) -> tuple[str, dict[str, Any]]:
    """
    Pack prompt sections without dropping task contracts.

    v4 switches coding prompts from retrieval-substitution to context-first
    pinned-contract packing. The agent is explicitly required to inspect key
    local paths before coding. Schema-critical task contract facts remain
    inline; EDA details are source-map-only so the coding prompt does not repeat
    the completed EDA report. Large sections may be reduced by complete lines,
    while branch behavior stays in the round directive and routed skill bodies
    remain available through the source map.
    """
    system_section = "[SYSTEM INSTRUCTIONS]\n\n" + system_prompt
    pinned_section = "[PINNED RUNTIME PACKET]\n\n" + pinned_context if pinned_context else ""
    user_task_raw = "\n\n".join(["[USER TASK]", *prompt_parts])
    skill_raw = skill_context or ""

    original_prompt = "\n\n".join(part for part in [system_section, pinned_section, skill_raw, user_task_raw] if part)
    original_prompt_chars = len(original_prompt)
    original_prompt_tokens = prompt_token_count(original_prompt)
    reduction_events: list[dict[str, Any]] = []

    if phase_name in {"coding", "static_gate_repair"}:
        task_dir = Path(str(pinned_info.get("task_dir") or "."))
        round_context_section = str(pinned_context or "").strip()
        context_first_section = build_v35_context_first_protocol(pinned_info)
        context_source_map_section, context_source_map_record = build_v35_context_source_map(pinned_info)
        sandbox_environment_section, sandbox_environment_record = build_v35_sandbox_environment_card(
            user_task_raw,
            metadata=pinned_info.get("metadata") if isinstance(pinned_info.get("metadata"), dict) else None,
        )
        eda_record = {
            "status": "source_map_only",
            "reason": "EDA is not inlined in coding prompts; read latest_eda_findings and optional structured EDA paths from CONTEXT SOURCE MAP.",
        }
        hard_contract_section, hard_contract_record = build_v35_hard_task_contract(skill_raw)

        branch_routing_record = {
            "original_chars": len(skill_raw),
            "original_tokens": prompt_token_count(skill_raw),
            "inlined": False,
            "source": "part3_round_directive_and_part4_skill_paths",
        }

        filtered_user_task, user_record = filter_user_task_for_context_first_coding(user_task_raw)
        if user_record.get("token_budget_reduction"):
            reduction_events.append({
                "section": "user_task_coding",
                "action": "metadata_data_description_removed_then_complete_lines_token_budget_reduction",
                **user_record["token_budget_reduction"],
            })
        else:
            reduction_events.append({
                "section": "user_task_coding",
                "action": "metadata_data_description_and_embedded_system_removed",
                "original_chars": user_record.get("original_chars"),
                "filtered_chars": user_record.get("filtered_chars"),
                "original_tokens": user_record.get("original_tokens"),
                "filtered_tokens": user_record.get("filtered_tokens"),
            })
        user_section = filtered_user_task

        if phase_name == "static_gate_repair":
            output_section = (
                "[OUTPUT CONTRACT]\n"
                "Repair the required local artifacts and make the final response only confirm that `solution.py` was repaired."
            )
        else:
            output_section = (
                "[OUTPUT CONTRACT]\n"
                "Create the required local artifacts and make the final response only confirm that `solution.py` was created."
            )

        def build_part_sections() -> dict[str, str]:
            part1 = _v41_part(
                "PART 1 - HARD EXECUTION RULES AND SANDBOX",
                "Static execution protocol, sandbox facts, package/API constraints, and output contract.",
                [system_section, sandbox_environment_section, context_first_section, output_section],
            )
            part2 = _v41_part(
                "PART 2 - TASK DESCRIPTION AND CONTRACT",
                "Original task description and executable task contract. EDA artifacts are not repeated inline; read required EDA paths from the source map.",
                [hard_contract_section, user_section],
            )
            part3 = _v41_part(
                "PART 3 - CURRENT ROUND ITERATION STATE",
                "Authoritative current-round metadata, branch action, parent or prior-draft memory, score context, bounded history, and the external validation timeout.",
                [round_context_section],
            )
            part4 = _v41_part(
                "PART 4 - REQUIRED AND OPTIONAL SOURCE PATHS",
                "Read every must-inspect path before coding. Optional paths expose only branch-routed expansion sources for the current phase.",
                [context_source_map_section],
            )
            return {
                "part1_hard_rules_sandbox": part1,
                "part2_task_contract_eda": part2,
                "part3_round_state": part3,
                "part4_source_paths": part4,
            }

        def build_prompt() -> str:
            parts = build_part_sections()
            return _promote_prompt_heading_markers("\n\n".join(
                section for section in [
                    parts["part1_hard_rules_sandbox"],
                    parts["part2_task_contract_eda"],
                    parts["part3_round_state"],
                    parts["part4_source_paths"],
                ]
                if section
            ))

        full_prompt = build_prompt()

        def path_reference_present(path_value: Any) -> bool:
            path_text = str(path_value or "").strip()
            if not path_text:
                return False
            if path_text in full_prompt:
                return True
            try:
                rel_text = str(Path(path_text).resolve().relative_to(task_dir.resolve()))
            except Exception:
                rel_text = ""
            return bool(rel_text and rel_text in full_prompt)

        pinned_markers_after_pack = {
            "context_first_protocol": "[CONTEXT-FIRST PROTOCOL]" in full_prompt,
            "context_readiness": "context_readiness.md" in full_prompt,
            "user_task": "[USER TASK]" in full_prompt,
            "hard_task_contract": bool(hard_contract_section.strip()) and "[PINNED HARD TASK CONTRACT]" in full_prompt,
            "round_state": "[ROUND DIRECTIVE]" in full_prompt,
            "context_source_map": "[CONTEXT SOURCE MAP]" in full_prompt,
            "sandbox_environment": "[PINNED SANDBOX ENVIRONMENT]" in full_prompt,
            "round_directive": "[ROUND DIRECTIVE]" in full_prompt,
            "draft_workload_ceiling": "[DRAFT WORKLOAD CEILING]" in full_prompt,
            "parent_abs_path": path_reference_present(pinned_info.get("parent_abs_path")),
            "parent_validation_feedback": path_reference_present(pinned_info.get("parent_validation_feedback_path")),
            "latest_eda_findings": path_reference_present(
                pinned_info.get("latest_eda_findings_path") or pinned_info.get("latest_eda_summary_path")
            ),
        }
        critical_failures = [
            name for name, present in pinned_markers_after_pack.items()
            if name in {
                "context_first_protocol",
                "context_readiness",
                "user_task",
                "round_state",
                "context_source_map",
                "sandbox_environment",
            } and not present
        ]
        source_presence = pinned_info.get("source_presence") if isinstance(pinned_info.get("source_presence"), dict) else {}
        if source_presence.get("round_directive") and not pinned_markers_after_pack["round_directive"]:
            critical_failures.append("round_directive")
        prompt_branch = normalize_branch_name(str(pinned_info.get("branch") or ""))
        if phase_name in {"coding", "static_gate_repair"} and prompt_branch == "draft" and not pinned_markers_after_pack["draft_workload_ceiling"]:
            critical_failures.append("draft_workload_ceiling")
        if prompt_token_count(full_prompt) > prompt_cap:
            critical_failures.append(f"prompt_token_cap_exceeded:{prompt_token_count(full_prompt)}>{prompt_cap}")

        prompt_pack = {
            "policy": V33_LLM_POLICY,
            "packing": "v54_draft_workload_ceiling",
            "round_context_schema": "part3_compact_v3",
            "cap_tokens": prompt_cap,
            "phase_name": phase_name,
            "prompt_chars_before_pack": original_prompt_chars,
            "prompt_tokens_before_pack": original_prompt_tokens,
            "prompt_chars_after_pack": len(full_prompt),
            "prompt_tokens_after_pack": prompt_token_count(full_prompt),
            "truncated": False,
            "retrieval_substituted": False,
            "section_chars": {
                "system": len(system_section),
                "context_first": len(context_first_section),
                "context_source_map": len(context_source_map_section),
                "sandbox_environment": len(sandbox_environment_section),
                "round_context": len(round_context_section),
                "hard_task_contract": len(hard_contract_section),
                "user_task": len(user_section),
                "output": len(output_section),
                **{key: len(value) for key, value in build_part_sections().items()},
            },
            "section_tokens": {
                "system": prompt_token_count(system_section),
                "context_first": prompt_token_count(context_first_section),
                "context_source_map": prompt_token_count(context_source_map_section),
                "sandbox_environment": prompt_token_count(sandbox_environment_section),
                "round_context": prompt_token_count(round_context_section),
                "hard_task_contract": prompt_token_count(hard_contract_section),
                "user_task": prompt_token_count(user_section),
                "output": prompt_token_count(output_section),
                **{key: prompt_token_count(value) for key, value in build_part_sections().items()},
            },
            "round_context_section_tokens": _round_context_token_counts(round_context_section),
            "context_reduction_events": reduction_events,
            "critical_marker_failures": critical_failures,
            "pinned_runtime": pinned_info,
            "eda_source_policy": eda_record,
            "context_source_map": context_source_map_record,
            "sandbox_environment": sandbox_environment_record,
            "hard_task_contract": hard_contract_record,
            "user_task_filter": user_record,
            "branch_context_routing": branch_routing_record,
            "pinned_markers_after_pack": pinned_markers_after_pack,
        }
        if critical_failures:
            raise RuntimeError(f"Prompt packing dropped critical context: {critical_failures}")
        return full_prompt, prompt_pack

    skill_section = "[SELECTED SKILL CONTEXT]\n\n" + skill_raw if skill_raw else ""
    user_section = user_task_raw

    def build_prompt() -> str:
        return "\n\n".join(section for section in [system_section, pinned_section, skill_section, user_section] if section)

    full_prompt = build_prompt()

    if prompt_token_count(full_prompt) > prompt_cap and skill_section:
        reduction_events.append({
            "section": "selected_skill_context",
            "action": "complete_lines_token_budget_reduction",
            "original_chars": len(skill_section),
        })
        selected_skill, skill_record = select_complete_lines_under_token_limit(
            skill_section,
            max(prompt_cap // 4, 1200),
        )
        reduction_events[-1].update(skill_record)
        skill_section = selected_skill
        full_prompt = build_prompt()

    if prompt_token_count(full_prompt) > prompt_cap:
        available_for_user = max(
            prompt_cap - prompt_token_count(system_section) - prompt_token_count(pinned_section) - prompt_token_count(skill_section) - 256,
            1200,
        )
        selected_user, user_record = select_complete_lines_under_token_limit(user_task_raw, available_for_user)
        reduction_events.append({
            "section": "user_task_non_coding",
            "action": "complete_lines_token_budget_reduction",
            **user_record,
        })
        user_section = selected_user or "[USER TASK]\nUse pinned runtime context and source-map paths; original user task did not fit as complete lines."
        full_prompt = build_prompt()

    independent_seed_draft = bool(pinned_info.get("independent_seed_draft"))
    best_code_path = "" if independent_seed_draft else str(pinned_info.get("best_code_path") or "")
    parent_commit = str(pinned_info.get("parent_commit") or "")
    parent_code_path = "" if independent_seed_draft else str(pinned_info.get("parent_code_path") or "")
    best_abs_path = "" if independent_seed_draft else str(pinned_info.get("best_abs_path") or "")
    parent_abs_path = "" if independent_seed_draft else str(pinned_info.get("parent_abs_path") or "")
    source_presence = pinned_info.get("source_presence") if isinstance(pinned_info.get("source_presence"), dict) else {}
    inline_presence = pinned_info.get("inline_presence") if isinstance(pinned_info.get("inline_presence"), dict) else source_presence
    pinned_markers_after_pack = {
        "pinned_runtime_control": "[PINNED RUNTIME CONTROL - DO NOT TRUNCATE]" in full_prompt,
        "deep_eda_summary": "[DEEP EDA SUMMARY]" in full_prompt,
        "early_eda_summary": "[EARLY EDA SUMMARY]" in full_prompt,
        "best_code_path": bool(best_code_path and best_code_path in full_prompt),
        "best_abs_path": bool(best_abs_path and best_abs_path in full_prompt),
        "parent_commit": bool(parent_commit and parent_commit in full_prompt),
        "parent_code_path": bool(parent_code_path and parent_code_path in full_prompt),
        "parent_abs_path": bool(parent_abs_path and parent_abs_path in full_prompt),
    }
    critical_failures: list[str] = []
    if not pinned_markers_after_pack["pinned_runtime_control"]:
        critical_failures.append("pinned_runtime_control")
    if best_code_path and not pinned_markers_after_pack["best_code_path"]:
        critical_failures.append("best_code_path")
    if best_abs_path and not pinned_markers_after_pack["best_abs_path"]:
        critical_failures.append("best_abs_path")
    if parent_commit and not pinned_markers_after_pack["parent_commit"]:
        critical_failures.append("parent_commit")
    if parent_code_path and not pinned_markers_after_pack["parent_code_path"]:
        critical_failures.append("parent_code_path")
    if inline_presence.get("deep_eda_summary") and not pinned_markers_after_pack["deep_eda_summary"]:
        critical_failures.append("deep_eda_summary")
    if inline_presence.get("early_eda_summary") and not pinned_markers_after_pack["early_eda_summary"]:
        critical_failures.append("early_eda_summary")
    if prompt_token_count(full_prompt) > prompt_cap:
        critical_failures.append(f"prompt_token_cap_exceeded:{prompt_token_count(full_prompt)}>{prompt_cap}")

    prompt_pack = {
        "policy": V33_LLM_POLICY,
        "packing": "v35_non_coding_complete_line_token_budget",
        "cap_tokens": prompt_cap,
        "phase_name": phase_name,
        "prompt_chars_before_pack": original_prompt_chars,
        "prompt_tokens_before_pack": original_prompt_tokens,
        "prompt_chars_after_pack": len(full_prompt),
        "prompt_tokens_after_pack": prompt_token_count(full_prompt),
        "truncated": False,
        "retrieval_substituted": False,
        "section_chars": {
            "system": len(system_section),
            "pinned_runtime": len(pinned_section),
            "skill": len(skill_section),
            "user_task": len(user_section),
        },
        "section_tokens": {
            "system": prompt_token_count(system_section),
            "pinned_runtime": prompt_token_count(pinned_section),
            "skill": prompt_token_count(skill_section),
            "user_task": prompt_token_count(user_section),
        },
        "context_reduction_events": reduction_events,
        "critical_marker_failures": critical_failures,
        "pinned_runtime": pinned_info,
        "pinned_markers_after_pack": pinned_markers_after_pack,
    }
    if critical_failures:
        raise RuntimeError(f"Prompt packing dropped critical context: {critical_failures}")
    return full_prompt, prompt_pack


def normalize_branch_name(branch: str) -> str:
    """Map legacy branch names to the active draft/debug/improve branch set."""
    clean = branch.strip().lower()
    return BRANCH_ALIASES.get(clean, clean)
