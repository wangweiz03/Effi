from __future__ import annotations

from .common import *
from .constants import *

def sanitize_eda_skill_text(text: str | None) -> str:
    return sanitize_legacy_prediction_file_language(text, eda=True)


def build_fallback_eda_script() -> str:
    """Return a conservative local EDA script if Codex does not create one."""
    return r'''from __future__ import annotations

import csv
import json
import os
import wave
from collections import Counter
from pathlib import Path

DATA_DIR = Path(os.environ.get("LOCAL_DATA_DIR") or os.environ.get("DATA_DIR") or ".").resolve()
OUT_DIR = Path.cwd()

def rel(path: Path) -> str:
    try:
        return path.relative_to(DATA_DIR).as_posix()
    except Exception:
        return path.as_posix()

def file_manifest(root: Path) -> dict:
    files = []
    large_files = []
    total_bytes = 0
    types = Counter()
    top_dir_bytes = Counter()
    for dirpath, _, filenames in os.walk(root):
        dir_path = Path(dirpath)
        for name in filenames:
            path = dir_path / name
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            total_bytes += size
            types[path.suffix.lower() or "<none>"] += 1
            try:
                top_dir_bytes[path.relative_to(root).parts[0]] += size
            except Exception:
                pass
            if size >= 500 * 1024 * 1024:
                large_files.append({"path": rel(path), "size_mb": round(size / 1024 / 1024, 3)})
            if len(files) < 500:
                files.append({"path": rel(path), "size_mb": round(size / 1024 / 1024, 3)})
    top_dirs = [
        {"path": name, "size_gb": round(size / 1024 / 1024 / 1024, 3)}
        for name, size in top_dir_bytes.most_common(20)
        if size >= 1024 * 1024 * 1024
    ]
    return {
        "data_dir": str(root),
        "exists": root.exists(),
        "n_files": sum(types.values()),
        "total_size_mb": round(total_bytes / 1024 / 1024, 3),
        "total_size_gb": round(total_bytes / 1024 / 1024 / 1024, 3),
        "file_types": dict(types.most_common()),
        "large_files_over_500mb": sorted(large_files, key=lambda x: x["size_mb"], reverse=True)[:50],
        "large_top_level_dirs_over_1gb": top_dirs,
        "sample_files": files[:80],
    }

def csv_head(path: Path, max_rows: int = 5) -> dict:
    info = {"path": rel(path)}
    try:
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            rows = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(row[: min(len(row), 20)])
        n_rows = None
        if size <= 100 * 1024 * 1024:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
                n_rows = max(sum(1 for _ in f) - 1, 0)
        info.update({"columns": header, "n_columns": len(header), "n_rows": n_rows, "sample_rows": rows})
    except Exception as exc:
        info["error"] = repr(exc)
    return info

def text_head(path: Path, max_chars: int = 4000) -> dict:
    info = {"path": rel(path)}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        info.update({"size_chars": len(text), "head": text[:max_chars]})
    except Exception as exc:
        info["error"] = repr(exc)
    return info

def media_probe(root: Path) -> dict:
    probes = {"images": [], "audio": []}
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    audio_exts = {".wav", ".flac", ".mp3", ".ogg"}
    if not root.exists():
        return probes
    image_paths = [p for p in root.rglob("*") if p.suffix.lower() in image_exts][:8]
    audio_paths = [p for p in root.rglob("*") if p.suffix.lower() in audio_exts][:8]
    for path in image_paths:
        item = {"path": rel(path)}
        try:
            from PIL import Image
            with Image.open(path) as img:
                item.update({"width": img.size[0], "height": img.size[1], "mode": img.mode})
        except Exception as exc:
            item["error"] = repr(exc)
        probes["images"].append(item)
    for path in audio_paths:
        item = {"path": rel(path)}
        try:
            with wave.open(str(path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                item.update({
                    "channels": wf.getnchannels(),
                    "sample_rate": rate,
                    "duration_sec": round(frames / rate, 3) if rate else None,
                    "sample_width": wf.getsampwidth(),
                })
        except Exception as exc:
            item["error"] = repr(exc)
        probes["audio"].append(item)
    return probes

def main() -> None:
    findings = {
        "manifest": file_manifest(DATA_DIR),
        "csv_files": [],
        "text_files": [],
        "media_probe": {},
        "notes": [],
        "recommendations": [],
        "bottleneck_findings": [],
        "search_hypotheses": [],
        "recommended_next_changes": [],
    }
    manifest = findings["manifest"]
    if not manifest.get("exists"):
        findings["notes"].append("Local EDA data directory does not exist; planning must rely on metadata and runtime DATA_DIR inspection.")
    if manifest.get("total_size_gb", 0) >= 5 or manifest.get("large_files_over_500mb"):
        findings["notes"].append(
            "Large data detected. Downstream code should avoid full loads; use metadata scans, heads, chunks, and bounded samples."
        )
    for path in sorted(DATA_DIR.rglob("*.csv"), key=lambda p: p.as_posix())[:30] if DATA_DIR.exists() else []:
        findings["csv_files"].append(csv_head(path))
    for path in sorted(DATA_DIR.rglob("*.txt"), key=lambda p: p.as_posix())[:12] if DATA_DIR.exists() else []:
        findings["text_files"].append(text_head(path))
    findings["media_probe"] = media_probe(DATA_DIR)
    sample = next((x for x in findings["csv_files"] if "sample" in x["path"].lower()), None)
    if sample:
        findings["recommendations"].append(
            "Use sample_submission columns and row order as the submission contract: "
            + ", ".join(sample.get("columns", []))
        )
    findings["recommendations"].append("Infer train/test schema at runtime from DATA_DIR and keep robust fallbacks.")
    findings["recommendations"].append("Check file sizes before loading; use chunks, heads, metadata reads, or lazy loading for large data.")
    findings["search_hypotheses"].append("Use the discovered schema/submission/resource constraints to choose one bounded next change.")
    findings["recommended_next_changes"].append("Preserve DATA_DIR loading, sample_submission alignment, and a robust fallback path.")
    (OUT_DIR / "eda_findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    md = [
        "# EDA Findings",
        f"- Data directory: {DATA_DIR}",
        f"- Exists: {manifest.get('exists')}",
        f"- Files: {manifest.get('n_files')} total, {manifest.get('total_size_mb')} MB",
        f"- File types: {manifest.get('file_types')}",
        f"- Large files >500MB: {manifest.get('large_files_over_500mb', [])[:10]}",
        f"- Large top-level dirs >1GB: {manifest.get('large_top_level_dirs_over_1gb', [])[:10]}",
        "## CSV Schemas",
    ]
    for item in findings["csv_files"][:12]:
        rows = item.get("n_rows")
        row_note = f", {rows} rows" if rows is not None else ""
        md.append(f"- `{item['path']}`: {item.get('n_columns')} columns{row_note}; {item.get('columns', [])[:20]}")
    md.append("## Text File Heads")
    for item in findings["text_files"][:8]:
        head = str(item.get("head", "")).replace("\n", " ")[:500]
        md.append(f"- `{item['path']}`: {head}")
    md.append("## Media Probe")
    media = findings["media_probe"]
    for item in media.get("images", [])[:6]:
        md.append(f"- image `{item.get('path')}`: {item}")
    for item in media.get("audio", [])[:6]:
        md.append(f"- audio `{item.get('path')}`: {item}")
    md.extend(["## Notes", *[f"- {x}" for x in findings["notes"]]])
    md.extend(["## Bottleneck Findings", *[f"- {x}" for x in findings["bottleneck_findings"] or ["Fallback EDA did not identify a task-specific bottleneck."]]])
    md.extend(["## Search Hypotheses", *[f"- {x}" for x in findings["search_hypotheses"]]])
    md.extend(["## Recommendations", *[f"- {x}" for x in findings["recommendations"]]])
    (OUT_DIR / "eda_findings.md").write_text("\n".join(md) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
'''


def build_deterministic_eda_summary(eda_context: str, *, eda_mode: str = "early") -> str:
    """Build a compact EDA handoff without spending another LLM call."""
    raw_context = eda_context or ""
    context = shrink_text_middle(raw_context, 9000)
    context_note = (
        "The excerpt below is compacted; inspect eda_findings.md, eda_findings.json, "
        "eda_stdout.txt, and eda_run_result.json in this EDA round directory when more detail is needed."
        if len(raw_context) > 9000 else
        "The excerpt below is the collected EDA context for this round; the same EDA round directory also contains eda_findings.md/json."
    )
    mode_label = "Deep Bottleneck" if eda_mode == "deep_bottleneck" else "Early"
    return (
        "# EDA Summary\n\n"
        "## Data Contract\n"
        f"{mode_label} EDA used the local read-only public data directory and produced the bounded context below. "
        "Use it as concrete schema/resource evidence, but re-read DATA_DIR defensively in solution.py.\n\n"
        "## Submission Contract\n"
        "Read sample_submission.csv at runtime when present and preserve its columns, row count, row order, and ID formatting.\n\n"
        "## Resource And Size Risks\n"
        "Check file and directory sizes before loading data. Use metadata scans, heads, chunked reads, lazy loading, and bounded samples for large data.\n\n"
        "## Modeling Signals\n"
        "Infer target columns, modality, train/test alignment, and validation strategy from public files, task description, routed task skill, and validation feedback.\n\n"
        "## Bounded EDA Context\n"
        f"{context_note}\n\n"
        f"{context}\n\n"
        "## Planning Constraints\n"
        "- Read all competition data from DATA_DIR.\n"
        "- Do not hardcode local EDA paths in solution.py.\n"
        "- Avoid full-loading multi-GB data.\n"
        "- Write only submission.csv as the required output file.\n"
    )


async def run_local_eda_script(
    work_dir: Path,
    eda_data_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run generated EDA locally, outside the sandbox service, with bounded time."""
    work_dir = work_dir.resolve()
    eda_data_dir = eda_data_dir.resolve()
    script_file = work_dir / "eda_analysis.py"
    env = dict(os.environ)
    env["LOCAL_DATA_DIR"] = str(eda_data_dir)
    env["DATA_DIR"] = str(eda_data_dir)
    start_time = datetime.now()
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_file),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(work_dir),
        env=env,
    )

    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        stdout, stderr = await proc.communicate()

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    (work_dir / "eda_stdout.txt").write_text(stdout_text, encoding="utf-8")
    (work_dir / "eda_stderr.txt").write_text(stderr_text, encoding="utf-8")

    result = {
        "timestamp": start_time.isoformat(),
        "end_timestamp": datetime.now().isoformat(),
        "data_dir": str(eda_data_dir),
        "return_code": proc.returncode,
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "stdout": _truncate_text(stdout_text, 12000),
        "stderr": _truncate_text(stderr_text, 12000),
    }
    (work_dir / "eda_run_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def collect_eda_context(work_dir: Path, run_result: dict[str, Any]) -> str:
    """Collect EDA outputs into a compact planning context."""
    parts = [
        "[LOCAL EDA RUN]",
        json.dumps(
            {
                "data_dir": run_result.get("data_dir"),
                "return_code": run_result.get("return_code"),
                "timed_out": run_result.get("timed_out"),
                "stderr": run_result.get("stderr"),
            },
            indent=2,
        ),
    ]
    for name in ("eda_findings.md", "eda_findings.json", "findings.md", "findings.json"):
        path = work_dir / name
        if path.exists():
            try:
                parts.extend([f"\n[{name}]", _truncate_text(path.read_text(encoding="utf-8"), 12000)])
            except Exception as exc:
                parts.extend([f"\n[{name}]", f"Failed to read EDA output: {exc!r}"])
    if run_result.get("stdout"):
        parts.extend(["\n[EDA STDOUT]", str(run_result["stdout"])])
    return _truncate_text("\n".join(parts), 24000)


EARLY_EDA_ARCHIVE_REQUIRED_FILES = ("eda_summary.md", "eda_findings.md", "eda_findings.json", "eda_run_result.json")
EARLY_EDA_ARCHIVE_SKIP_DIRS = {".git", "__pycache__"}


def early_eda_archive_dir(task_name: str, archive_root: Path = DEFAULT_EARLY_EDA_ARCHIVE_ROOT) -> Path:
    """Return the default archive directory for a task's early EDA output."""
    return archive_root / task_name


def early_eda_archive_available(task_name: str, archive_root: Path = DEFAULT_EARLY_EDA_ARCHIVE_ROOT) -> bool:
    """A usable early EDA archive has the summary and core collected output files."""
    archive_dir = early_eda_archive_dir(task_name, archive_root)
    if not archive_dir.is_dir():
        return False
    return all((archive_dir / name).is_file() for name in EARLY_EDA_ARCHIVE_REQUIRED_FILES)


def _copy_eda_tree(source_dir: Path, target_dir: Path) -> list[str]:
    """Copy EDA artifacts while skipping cache/control directories."""
    copied: list[str] = []
    source_dir = source_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in source_dir.rglob("*"):
        rel = path.relative_to(source_dir)
        if any(part in EARLY_EDA_ARCHIVE_SKIP_DIRS for part in rel.parts):
            continue
        if path.is_dir():
            (target_dir / rel).mkdir(parents=True, exist_ok=True)
            continue
        if path.suffix == ".pyc":
            continue
        destination = target_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append(rel.as_posix())
    return copied


def load_early_eda_archive(
    task_name: str,
    work_dir: Path,
    archive_root: Path = DEFAULT_EARLY_EDA_ARCHIVE_ROOT,
) -> tuple[str, str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Copy archived early EDA into this run and return context/summary metadata."""
    archive_dir = early_eda_archive_dir(task_name, archive_root)
    if not early_eda_archive_available(task_name, archive_root):
        raise FileNotFoundError(f"usable early EDA archive not found for {task_name}: {archive_dir}")

    copied_files = _copy_eda_tree(archive_dir, work_dir)
    run_result_path = work_dir / "eda_run_result.json"
    try:
        run_result = json.loads(run_result_path.read_text(encoding="utf-8"))
    except Exception:
        run_result = {
            "timestamp": datetime.now().isoformat(),
            "data_dir": None,
            "return_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "source": "early_eda_archive_without_run_result",
        }
    eda_context = collect_eda_context(work_dir, run_result)
    summary_text = (work_dir / "eda_summary.md").read_text(encoding="utf-8", errors="replace")
    archive_record = {
        "enabled": True,
        "hit": True,
        "source_dir": str(archive_dir),
        "target_dir": str(work_dir),
        "copied_files": copied_files,
        "required_files": list(EARLY_EDA_ARCHIVE_REQUIRED_FILES),
    }
    (work_dir / "early_eda_archive.json").write_text(json.dumps(archive_record, indent=2), encoding="utf-8")
    return eda_context, summary_text, {"input_tokens": 0, "output_tokens": 0}, run_result, archive_record


def archive_early_eda_outputs(
    task_name: str,
    work_dir: Path,
    archive_root: Path = DEFAULT_EARLY_EDA_ARCHIVE_ROOT,
) -> dict[str, Any]:
    """Persist newly executed early EDA outputs for future runs."""
    archive_dir = early_eda_archive_dir(task_name, archive_root)
    record = {
        "enabled": True,
        "hit": False,
        "source_dir": str(work_dir),
        "target_dir": str(archive_dir),
        "status": "not_started",
        "copied_files": [],
        "required_files": list(EARLY_EDA_ARCHIVE_REQUIRED_FILES),
    }
    missing = [name for name in EARLY_EDA_ARCHIVE_REQUIRED_FILES if not (work_dir / name).is_file()]
    if missing:
        record.update({
            "status": "skipped_missing_required_files",
            "missing_required_files": missing,
        })
        return record
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        copied_files = _copy_eda_tree(work_dir, archive_dir)
        record.update({
            "status": "archived",
            "copied_files": copied_files,
        })
        (archive_dir / "early_eda_archive.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    except Exception as exc:
        record.update({
            "status": "archive_failed",
            "error": repr(exc),
        })
        logger.warning("[%s] Failed to archive early EDA outputs to %s: %s", task_name, archive_dir, exc)
    return record


def compact_eda_json(payload: Any, limit: int) -> str:
    try:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    except Exception:
        text = repr(payload)
    return shrink_text_middle(text, limit)


def build_fixed_eda_prompt_card(work_dir: Path, run_result: dict[str, Any]) -> str:
    """List deterministic EDA output paths; the personalized agent should inspect them."""
    full_paths = [
        f"- {work_dir / 'eda_findings.md'}",
        f"- {work_dir / 'eda_findings.json'}",
        f"- {work_dir / 'eda_run_result.json'}",
        f"- {work_dir / 'eda_stdout.txt'}",
        f"- {work_dir / 'eda_stderr.txt'}",
    ]
    sections = [
        "[FIXED EDA OUTPUT PATHS]",
        "The deterministic fixed EDA has already read the public files safely. Inspect these files before writing personalized EDA. Do not duplicate their generic manifest; add missing task-specific evidence.",
        f"Fixed EDA run status: return_code={run_result.get('return_code')}, timed_out={run_result.get('timed_out')}, data_dir={run_result.get('data_dir')}",
        *full_paths,
        "",
        "[PERSONALIZED EDA GAP]",
        "Do not duplicate the fixed manifest. Write a second-pass EDA script that adds missing task-specific evidence: target/source interpretation, label or class distribution, train/test or sample-submission alignment, fold/group/time/leakage clues, text/image/audio-specific bounded statistics, and concrete modeling handoff hypotheses.",
    ]
    return "\n".join(sections)


def build_deep_eda_focus_context(
    task_dir: Path,
    branch_decision: dict[str, Any],
    higher_is_better: bool,
) -> str:
    """Build a targeted bottleneck brief so EDA searches for new evidence, not generic facts."""
    diagnostics = branch_decision.get("state_diagnostics") or {}
    anti = branch_decision.get("anti_repetition") or {}
    focus = {
        "trigger_reason": branch_decision.get("reason"),
        "search_state": branch_decision.get("search_state"),
        "search_intent": branch_decision.get("search_intent"),
        "selected_operator": branch_decision.get("search_operator"),
        "since_best_successes": diagnostics.get("since_best_successes"),
        "valid_successes": diagnostics.get("valid_successes"),
        "recent_valid_scores": diagnostics.get("recent_valid_scores") or anti.get("recent_valid_scores"),
        "repeated_method_family": diagnostics.get("repeated_method_family") or anti.get("observed_repeated_method_family"),
        "no_recent_best_improvement": diagnostics.get("no_recent_best_improvement"),
        "deep_eda_reason": diagnostics.get("deep_eda_reason"),
        "best_local_cv_score": branch_decision.get("best_local_cv_score"),
        "best_local_cv_commit": branch_decision.get("best_local_cv_commit"),
        "higher_is_better": higher_is_better,
    }
    return "\n\n".join([
        "[DEEP EDA BOTTLENECK BRIEF]",
        json.dumps({k: v for k, v in focus.items() if v is not None}, indent=2, ensure_ascii=False),
        shrink_text_middle(get_branch_scoreboard(task_dir, higher_is_better=higher_is_better), 1400),
        shrink_text_middle(get_commit_log_summary(task_dir, limit=5), 2000),
        shrink_text_middle(get_latest_failure_context(task_dir), 1600),
        (
            "[DEEP EDA QUESTIONS]\n"
            "- What data/metric/submission detail could explain why recent valid attempts are not improving?\n"
            "- Is there train/test, target, label, group, leakage, distribution, or file-layout evidence that suggests a different route?\n"
            "- Which one concrete modeling, feature, validation, calibration, thresholding, or postprocessing change should be tried next?\n"
            "- What resource constraint must the next implementation respect?"
        ),
    ])


def build_slim_early_eda_metadata(
    metadata: dict[str, Any],
    *,
    task_name: str,
    eda_data_dir: Path,
    branch_decision: dict[str, Any],
) -> dict[str, Any]:
    """Keep early EDA metadata small; the local files are the source of schema truth."""
    slim: dict[str, Any] = {
        "task_name": task_name,
        "cpu_gpu": metadata.get("cpu_gpu"),
        "data_dir": str(eda_data_dir),
        "higher_is_better": metadata.get("higher_is_better"),
        "theoretical_min": metadata.get("theoretical_min"),
        "theoretical_max": metadata.get("theoretical_max"),
        "slim_eda_prompt": True,
    }
    for key in ("metric", "metric_name", "evaluation_metric", "competition_id"):
        value = metadata.get(key)
        if value:
            slim[key] = value
    return slim


def load_early_eda_task_description(metadata: dict[str, Any], eda_data_dir: Path) -> str:
    """Prefer the complete competition description for early personalized EDA."""
    for key in ("task_description", "description"):
        text = str(metadata.get(key) or "").strip()
        if text:
            return text
    description_file = eda_data_dir / "description.txt"
    if description_file.exists():
        try:
            return description_file.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass
    return str(metadata.get("data_description") or "").strip()


def build_slim_early_eda_messages(
    metadata: dict[str, Any],
    *,
    task_name: str,
    eda_data_dir: Path,
    branch_decision: dict[str, Any],
) -> list[dict[str, str]]:
    """Build a compact, task-directed EDA request instead of replaying the full coding prompt."""
    task_description = load_early_eda_task_description(metadata, eda_data_dir)
    content = "\n".join([
        "[EARLY EDA REQUEST]",
        f"Task: {task_name}",
        f"Local data directory: {eda_data_dir}",
        "",
        "Create exactly one Python file named `eda_analysis.py` in the current working directory.",
        "The script must read only LOCAL_DATA_DIR/DATA_DIR, finish quickly, and write `eda_findings.md` plus `eda_findings.json`.",
        "",
        "Focus on evidence the later coding round needs:",
        "- concrete train/test/sample_submission files, schemas, row counts, labels, IDs, and submission unit;",
        "- metric direction and any target/source ambiguity visible from public files;",
        "- resource risks: total size, large files, media layout, expensive scans, dependency assumptions;",
        "- validation and leakage risks suggested by filenames, groups, time/order fields, duplicated IDs, or train/test mismatch;",
        "- 2-4 high-value modeling or feature hypotheses grounded in the task and data, without assuming a preselected method family.",
        "",
        "Do not train models, run broad hyperparameter search, write `solution.py`, or write `planning.md`.",
        "For media-heavy data, inspect CSV/manifests first and avoid recursive full-directory scans unless bounded.",
        "First inspect the fixed-EDA result paths in `[REFINEMENT CONTEXT]`; do not duplicate the fixed manifest.",
        "",
        "[FULL TASK DESCRIPTION]",
        task_description or "No complete task description was available; rely on fixed EDA paths and local file inspection.",
    ])
    return [{"role": "user", "content": content}]


def build_slim_early_eda_skill_context() -> str:
    """Compact EDA guidance for first-pass schema/resource discovery."""
    return (
        "[COMPACT EDA SKILL CONTEXT]\n"
        "- Purpose: produce a small task-specific evidence handoff before coding, not a model solution.\n"
        "- Inputs: LOCAL_DATA_DIR/DATA_DIR and the deterministic prescan excerpt in refinement context.\n"
        "- Required output files: eda_analysis.py, eda_findings.md, eda_findings.json.\n"
        "- eda_findings.json should include manifest/schema facts plus bottleneck_findings, "
        "search_hypotheses, and recommended_next_changes when possible.\n"
        "- Keep runtime bounded: heads, schema reads, small samples, file-size checks, CSV-first media lookup, "
        "and no training or full-data expensive scans."
    )


async def generate_round_eda(
    work_dir: Path,
    output_dir: Path,
    round_num: int,
    prompt_messages: list[dict[str, str]],
    metadata: dict[str, Any],
    refinement_context: str | None,
    model: str,
    reasoning_level: str,
    max_tokens: int,
    temperature: float,
    eda_skill_dir: Path,
    local_eda_data_root: Path,
    eda_timeout_seconds: int,
    eda_mode: str = "early",
    branch_decision: dict[str, Any] | None = None,
    higher_is_better: bool = True,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """Generate and locally run bounded EDA code before integrated coding."""
    task_name = metadata.get("task_name", "unknown")
    eda_data_dir = resolve_local_eda_data_dir(task_name, local_eda_data_root)
    eda_file = work_dir / "eda_analysis.py"
    usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0}
    raw_text = ""
    max_eda_retries = 1
    mode_title = "Deep Bottleneck EDA" if eda_mode == "deep_bottleneck" else "Pre-Plan Local EDA"
    if eda_mode == "deep_bottleneck":
        eda_path, eda_skill = load_skill_package(eda_skill_dir / "SKILL.md", limit=200000)
        skill_context = "\n\n".join([
            f"## {mode_title} Guardrails",
            EDA_SKILL_GUIDANCE,
            f"Source: {eda_path or eda_skill_dir}",
            sanitize_eda_skill_text(eda_skill) or "EDA skill package was not available; use the system prompt and task metadata.",
        ])
        eda_prompt_messages = prompt_messages
        eda_metadata = metadata
        base_navigation_context = refinement_context
    else:
        skill_context = build_slim_early_eda_skill_context()
        eda_prompt_messages = build_slim_early_eda_messages(
            metadata,
            task_name=task_name,
            eda_data_dir=eda_data_dir,
            branch_decision=branch_decision or {},
        )
        eda_metadata = build_slim_early_eda_metadata(
            metadata,
            task_name=task_name,
            eda_data_dir=eda_data_dir,
            branch_decision=branch_decision or {},
        )
        base_navigation_context = None

    eda_context_prefix = (
        "[LOCAL EDA DATA]\n"
        f"Task name: {task_name}\n"
        f"Read-only public data directory: {eda_data_dir}\n"
        "The generated script must only read this directory via LOCAL_DATA_DIR or DATA_DIR. "
        "All generated files must be written in the current working directory.\n"
    )
    deep_focus = (
        build_deep_eda_focus_context(output_dir, branch_decision or {}, higher_is_better)
        if eda_mode == "deep_bottleneck" else None
    )
    mode_contract = (
        "[DEEP EDA MODE]\n"
        "This EDA is triggered by search stagnation. Do not produce a generic manifest only. "
        "Write bounded analyses that answer the bottleneck questions, inspect task-specific slices safely, "
        "and produce explicit next-round hypotheses in eda_findings.md/json."
        if eda_mode == "deep_bottleneck" else
        "[EARLY EDA MODE]\nUse EDA to establish schema, resource, metric, and submission contracts before the first plan."
    )
    base_refinement = "\n\n".join([
        part for part in [base_navigation_context, eda_context_prefix, deep_focus, mode_contract] if part
    ])

    deterministic_context = ""
    if eda_mode != "deep_bottleneck":
        deterministic_dir = work_dir / "deterministic_scan"
        deterministic_dir.mkdir(parents=True, exist_ok=True)
        logger.info("[%s] Round %s - running deterministic early EDA prescan", task_name, round_num + 1)
        (deterministic_dir / "eda_analysis.py").write_text(build_fallback_eda_script(), encoding="utf-8")
        deterministic_result = await run_local_eda_script(
            work_dir=deterministic_dir,
            eda_data_dir=eda_data_dir,
            timeout_seconds=min(eda_timeout_seconds, 300),
        )
        deterministic_context = build_fixed_eda_prompt_card(deterministic_dir, deterministic_result)
        if eda_file.exists():
            eda_file.unlink()
        base_refinement = "\n\n".join([
            base_refinement,
            (
                "[DETERMINISTIC EDA PRESCAN]\n"
                "A fast fixed EDA scan has already run and its full outputs are on disk. "
                "Use the compact card below as the base evidence, inspect the listed fixed-EDA files only if needed, "
                "and write a personalized second-pass EDA script that adds missing task-specific evidence. "
                "Do not duplicate the generic manifest.\n\n"
                f"{deterministic_context}"
            ),
        ])

    for retry in range(max_eda_retries + 1):
        retry_suffix = f"_retry_{retry}" if retry > 0 else ""
        trace_file = output_dir / "traces" / f"round_{round_num}{retry_suffix}_eda_trace.json"
        current_refinement = base_refinement

        if retry > 0:
            retry_hint = (
                f"\n\n[CRITICAL - EDA RETRY {retry}/{max_eda_retries}]\n"
                "Your previous attempt did NOT produce eda_analysis.py.\n"
                "You MUST create exactly one Python file named `eda_analysis.py` in the current working directory.\n"
                "Do NOT create planning.md or solution.py during the EDA phase."
            )
            current_refinement = (current_refinement or "") + retry_hint
            if eda_file.exists():
                eda_file.unlink()

        try:
            raw_text, attempt_usage = await call_codex_cli(
                work_dir=work_dir,
                prompt_messages=eda_prompt_messages,
                metadata=eda_metadata,
                system_prompt=EDA_SYSTEM_PROMPT,
                model=model,
                reasoning_level=reasoning_level,
                max_tokens=max_tokens,
                temperature=temperature,
                trace_file=trace_file,
                refinement_context=current_refinement,
                skill_context=skill_context,
                phase_name="deep_eda" if eda_mode == "deep_bottleneck" else "early_eda",
            )
        except CodexCliError as exc:
            usage["input_tokens"] += exc.usage.get("input_tokens", 0)
            usage["output_tokens"] += exc.usage.get("output_tokens", 0)
            logger.warning(
                "[%s] Round %s - EDA Codex generation failed (%s); using fallback EDA if retries are exhausted",
                task_name,
                round_num + 1,
                exc.failure_type,
            )
            if retry < max_eda_retries and exc.failure_type not in {"llm_cli_timeout"}:
                continue
            break
        usage["input_tokens"] += attempt_usage.get("input_tokens", 0)
        usage["output_tokens"] += attempt_usage.get("output_tokens", 0)

        for forbidden_name in ("planning.md", "solution.py"):
            forbidden = work_dir / forbidden_name
            if forbidden.exists():
                forbidden.unlink()

        if eda_file.exists() and len(eda_file.read_text(encoding="utf-8", errors="replace").strip()) > 100:
            break

        code = extract_code(raw_text)
        if code and len(code.strip()) > 100:
            eda_file.write_text(code, encoding="utf-8")
            break

        if retry < max_eda_retries:
            logger.warning(
                "[%s] Round %s - eda_analysis.py not found, retrying (%s/%s)",
                task_name,
                round_num + 1,
                retry + 1,
                max_eda_retries,
            )

    if not eda_file.exists():
        logger.warning("[%s] Round %s - using fallback EDA script", task_name, round_num + 1)
        eda_file.write_text(build_fallback_eda_script(), encoding="utf-8")

    run_result = await run_local_eda_script(
        work_dir=work_dir,
        eda_data_dir=eda_data_dir,
        timeout_seconds=eda_timeout_seconds,
    )
    eda_context = collect_eda_context(work_dir, run_result)
    return eda_context, raw_text, usage, run_result


async def generate_eda_summary(
    work_dir: Path,
    output_dir: Path,
    round_num: int,
    prompt_messages: list[dict[str, str]],
    metadata: dict[str, Any],
    refinement_context: str | None,
    eda_context: str,
    model: str,
    reasoning_level: str,
    max_tokens: int,
    temperature: float,
    eda_mode: str = "early",
) -> tuple[str, str, dict[str, Any]]:
    """Generate eda_summary.md as the compact EDA-derived planning handoff."""
    summary_file = work_dir / "eda_summary.md"
    usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0}
    raw_text = ""
    max_summary_retries = 0

    if eda_mode != "deep_bottleneck":
        summary = build_deterministic_eda_summary(eda_context, eda_mode=eda_mode)
        summary_file.write_text(summary, encoding="utf-8")
        return summary, raw_text, usage

    summary_context = "\n\n".join([
        part for part in [
            refinement_context,
            (
                "[LOCAL EDA OUTPUTS]\n"
                "Summarize these outputs into eda_summary.md. Later integrated coding will see this "
                "summary plus compact v4 branch context and pinned EDA findings extraction, not raw EDA files.\n"
                f"EDA mode: {eda_mode}. "
                "If this is deep_bottleneck mode, emphasize bottleneck findings and concrete next-round hypotheses.\n\n"
                f"{eda_context}"
            ),
        ]
        if part
    ])

    for retry in range(max_summary_retries + 1):
        retry_suffix = f"_retry_{retry}" if retry > 0 else ""
        trace_file = output_dir / "traces" / f"round_{round_num}{retry_suffix}_eda_summary_trace.json"
        current_refinement = summary_context

        if retry > 0:
            retry_hint = (
                f"\n\n[CRITICAL - EDA SUMMARY RETRY {retry}/{max_summary_retries}]\n"
                "Your previous attempt did NOT produce eda_summary.md.\n"
                "You MUST create exactly one markdown file named `eda_summary.md` in the current working directory.\n"
                "Do NOT create planning.md or solution.py during the EDA summary phase."
            )
            current_refinement = (current_refinement or "") + retry_hint
            if summary_file.exists():
                summary_file.unlink()

        raw_text, attempt_usage = await call_codex_cli(
            work_dir=work_dir,
            prompt_messages=prompt_messages,
            metadata=metadata,
            system_prompt=EDA_SUMMARY_SYSTEM_PROMPT,
            model=model,
            reasoning_level=reasoning_level,
            max_tokens=max_tokens,
            temperature=temperature,
            trace_file=trace_file,
            refinement_context=current_refinement,
            skill_context=None,
            phase_name="deep_eda_summary" if eda_mode == "deep_bottleneck" else "early_eda_summary",
        )
        usage["input_tokens"] += attempt_usage.get("input_tokens", 0)
        usage["output_tokens"] += attempt_usage.get("output_tokens", 0)

        for forbidden_name in ("planning.md", "solution.py"):
            forbidden = work_dir / forbidden_name
            if forbidden.exists():
                forbidden.unlink()

        if summary_file.exists():
            summary_text = summary_file.read_text(encoding="utf-8").strip()
            if len(summary_text) > 50:
                return summary_text, raw_text, usage

        response_summary = raw_text.strip()
        if len(response_summary) > 50:
            summary_file.write_text(response_summary + "\n", encoding="utf-8")
            return response_summary, raw_text, usage

        if retry < max_summary_retries:
            logger.warning(
                "[%s] Round %s - eda_summary.md not found, retrying (%s/%s)",
                metadata.get("task_name", "unknown"),
                round_num + 1,
                retry + 1,
                max_summary_retries,
            )

    fallback_summary = (
        "# EDA Summary\n\n"
        "## Data Contract\n"
        "EDA summary generation did not produce usable markdown. Use task metadata, description, and runtime DATA_DIR inspection carefully.\n\n"
        "## Submission Contract\n"
        "Read sample_submission.csv at runtime when present and preserve its columns, row count, row order, and ID formatting.\n\n"
        "## Resource And Size Risks\n"
        "Check file and directory sizes before loading data. Use metadata scans, heads, chunked reads, lazy loading, and bounded samples for large data.\n\n"
        "## Modeling Signals\n"
        "Infer target columns, modality, train/test alignment, and validation strategy from the public files and task description.\n\n"
        "## Bottleneck Findings\n"
        "No generated deep-EDA bottleneck findings were available. Use validation feedback, task skill, and safe runtime inspection.\n\n"
        "## Search Hypotheses\n"
        "- Try one data-driven change only after confirming it from task files or validation feedback.\n\n"
        "## Planning Constraints\n"
        "- Read all competition data from DATA_DIR.\n"
        "- Do not hardcode local EDA paths in solution.py.\n"
        "- Avoid full-loading multi-GB data.\n"
        "- Write submission.csv exactly in the required format.\n"
    )
    summary_file.write_text(fallback_summary, encoding="utf-8")
    return fallback_summary, raw_text, usage
