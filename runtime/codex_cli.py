from __future__ import annotations

from .common import *
from .constants import *


EDA_PHASE_NAMES = {"early_eda", "deep_eda"}


def codex_phase_timeout_seconds(phase_name: str) -> float:
    """Return the Codex CLI timeout, with optional per-run env overrides."""
    phase_key = re.sub(r"[^A-Za-z0-9]+", "_", str(phase_name or "coding")).upper().strip("_")
    candidates = [
        os.environ.get(f"CODEX_CLI_{phase_key}_TIMEOUT_SECONDS"),
        os.environ.get("CODEX_CLI_TIMEOUT_SECONDS"),
    ]
    for value in candidates:
        if value is None:
            continue
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return float(CODEX_PHASE_TIMEOUT_SECONDS.get(phase_name, CODEX_PHASE_TIMEOUT_SECONDS["coding"]))


def _strip_solution_output_contract_for_eda(content: str) -> str:
    """Remove the original solution.py/submission contract from EDA prompts."""
    text = str(content or "")
    text = re.sub(
        r"(?is)\n?Output Instructions:\s*.*?(?=\n\s*\*\*CONSTRAINTS\*\*:|\n\s*\[DATA DESCRIPTION\]|\n\s*\[TASK DESCRIPTION\]|\Z)",
        (
            "\n[EDA PHASE NOTE]\n"
            "Original solution.py output instructions are omitted for this EDA phase. "
            "Follow the EDA system prompt: create eda_analysis.py and write eda_findings.md/json only.\n"
        ),
        text,
        count=1,
    )
    text = re.sub(
        r"(?is)\n?\*\*SAVE PREDICTIONS.*?submission\.csv.*?(?=\n)",
        "",
        text,
    )
    return text


def _phase_prompt_messages(prompt_messages: list[dict[str, str]], phase_name: str) -> list[dict[str, str]]:
    if phase_name not in EDA_PHASE_NAMES:
        return prompt_messages
    cleaned: list[dict[str, str]] = []
    for msg in prompt_messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role.lower() == "user":
            content = _strip_solution_output_contract_for_eda(content)
        cleaned.append({**msg, "content": content})
    return cleaned

async def call_codex_cli(
    work_dir: Path,
    prompt_messages: list[dict[str, str]],
    metadata: dict[str, Any],
    system_prompt: str = SYSTEM_PROMPT,
    model: str = "o4-mini",
    reasoning_level: str = "high",
    max_tokens: int = 32768,
    temperature: float = 0.6,
    trace_file: Path | None = None,
    refinement_context: str | None = None,
    skill_context: str | None = None,
    phase_name: str = "coding",
) -> tuple[str, dict[str, Any]]:
    """
    Call OpenAI Codex CLI for code generation via subprocess.
    """
    try:
        work_dir.mkdir(parents=True, exist_ok=True)

        task_name = metadata.get("task_name", "unknown")
        effective_prompt_messages = _phase_prompt_messages(prompt_messages, phase_name)
        prompt_parts = []

        for msg in effective_prompt_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role and content:
                prompt_parts.append(f"[{role.upper()}]\n{content}")

        if refinement_context and phase_name == "coding":
            prompt_parts.append(
                "\n[REFINEMENT CONTEXT ROUTING]\n"
                "Runtime search state, memory, EDA, incumbent paths, and context sources are provided in the pinned runtime packet and unified `[CONTEXT SOURCE MAP]`. "
                "Use source-map paths to inspect full local files when exact details are needed."
            )
        elif refinement_context:
            prompt_parts.append(f"\n[REFINEMENT CONTEXT]\n{refinement_context}")

        prompt_parts.append(build_metadata_prompt(metadata))
        user_task_full_text = "\n\n".join(["[USER TASK]", *prompt_parts])
        try:
            context_source_dir = work_dir / "context_sources"
            context_source_dir.mkdir(parents=True, exist_ok=True)
            user_task_source_path = context_source_dir / f"{phase_name}_user_task_full.md"
            user_task_source_path.write_text(user_task_full_text, encoding="utf-8")
            metadata = dict(metadata)
            metadata["user_task_source_path"] = str(user_task_source_path.resolve())
        except Exception:
            user_task_source_path = None

        prompt_cap = int(V35_MAX_PROMPT_TOKENS.get(phase_name, V35_MAX_PROMPT_TOKENS["coding"]))
        if phase_name == "coding" and metadata.get("branch"):
            prompt_cap = int(V35_MAX_PROMPT_TOKENS.get(str(metadata.get("branch")), prompt_cap))
        pinned_context, pinned_info = build_pinned_runtime_context(
            work_dir=work_dir,
            metadata=metadata,
            refinement_context=refinement_context,
            phase_name=phase_name,
        )
        full_prompt, prompt_pack = pack_prompt_with_pinned_runtime(
            system_prompt=system_prompt,
            pinned_context=pinned_context,
            pinned_info=pinned_info,
            skill_context=skill_context,
            prompt_parts=prompt_parts,
            phase_name=phase_name,
            prompt_cap=prompt_cap,
        )
        try:
            context_source_dir = work_dir / "context_sources"
            context_source_dir.mkdir(parents=True, exist_ok=True)
            (context_source_dir / f"{phase_name}_prompt_after_pack.md").write_text(full_prompt, encoding="utf-8")
            (context_source_dir / f"{phase_name}_prompt_after_pack.json").write_text(
                json.dumps(prompt_pack, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

        cmd = [
            "codex",
            "exec",
            "--full-auto",
            "--ephemeral",
            "--skip-git-repo-check",
            "--model", model,
            "-c", f"reasoning_level={json.dumps(reasoning_level)}",
        ]

        env = dict(os.environ)
        context_eda_data_dir = metadata.get("context_eda_data_dir") or metadata.get("data_dir")
        if phase_name == "coding" and context_eda_data_dir:
            env["CONTEXT_EDA_DATA_DIR"] = str(context_eda_data_dir)

        start_time = datetime.now()
        trace_data = {
            "timestamp": start_time.isoformat(),
            "model": model,
            "reasoning_level": reasoning_level,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "work_dir": str(work_dir),
            "task_name": task_name,
            "prompt_messages": effective_prompt_messages,
            "metadata": metadata,
            "phase_name": phase_name,
            "system_prompt": system_prompt,
            "refinement_context": refinement_context,
            "skill_context_used": bool(skill_context),
            "full_prompt": full_prompt,
            "prompt_pack": prompt_pack,
            "cmd": cmd,
            "response_text": "",
            "stderr": "",
            "return_code": None,
            "usage": {},
            "duration_seconds": 0,
        }

        logger.debug("Running Codex CLI: %s ... in %s", " ".join(cmd[:4]), work_dir)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(work_dir),
            env=env,
        )

        timeout_seconds = codex_phase_timeout_seconds(phase_name)
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=full_prompt.encode("utf-8")),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Codex CLI timed out after %.1fs in phase %s", timeout_seconds, phase_name)
            proc.terminate()
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            except Exception:
                proc.kill()
                stdout, stderr = await proc.communicate()
            response_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
            usage = {
                "input_tokens": len(full_prompt) // 4,
                "output_tokens": len(response_text) // 4,
            }
            end_time = datetime.now()
            trace_data["response_text"] = response_text
            trace_data["stderr"] = stderr_text + f"\nCodex CLI timed out after {timeout_seconds:.1f}s in phase {phase_name}."
            trace_data["return_code"] = proc.returncode
            trace_data["usage"] = usage
            trace_data["duration_seconds"] = (end_time - start_time).total_seconds()
            trace_data["end_timestamp"] = end_time.isoformat()
            trace_data["timeout_seconds"] = timeout_seconds
            if trace_file:
                trace_file.parent.mkdir(parents=True, exist_ok=True)
                trace_file.write_text(json.dumps(trace_data, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info("Saved execution trace to %s", trace_file)
            record_token_usage(work_dir, phase=phase_name, usage=usage, status="failed", failure_type="llm_cli_timeout")
            raise CodexCliError(
                f"Codex CLI timed out after {timeout_seconds:.1f}s in phase {phase_name}",
                failure_type="llm_cli_timeout",
                return_code=proc.returncode,
                stderr=trace_data["stderr"],
                usage=usage,
            )

        response_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            logger.warning("Codex CLI exited with code %s", proc.returncode)
        if stderr_text:
            logger.debug("Codex CLI stderr: %s", stderr_text[:500])

        usage = {
            "input_tokens": len(full_prompt) // 4,
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
            logger.info("Saved execution trace to %s", trace_file)

        status = "ok" if proc.returncode == 0 else "failed"
        failure_type = None if proc.returncode == 0 else classify_codex_stderr(stderr_text, proc.returncode)
        record_token_usage(work_dir, phase=phase_name, usage=usage, status=status, failure_type=failure_type)
        if proc.returncode != 0:
            raise CodexCliError(
                f"Codex CLI {failure_type} in phase {phase_name}: {stderr_text[:500]}",
                failure_type=failure_type or "llm_cli_error",
                return_code=proc.returncode,
                stderr=stderr_text,
                usage=usage,
            )

        return response_text, usage

    except CodexCliError:
        raise
    except Exception as e:
        logger.error("Codex CLI call failed: %s", e)
        raise
