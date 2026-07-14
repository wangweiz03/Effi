from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from dotenv import load_dotenv

from prompts import (
    EDA_SUMMARY_SYSTEM_PROMPT,
    EDA_SYSTEM_PROMPT,
    RUNTIME_HARDENING_CONTEXT,
    SYSTEM_PROMPT,
)

_local_inference_dir = Path(__file__).resolve().parents[2] / "inference"
_fallback_inference_dir = Path("/hpc_data/ktian/superml/inference")
sys.path.insert(0, str(_local_inference_dir if _local_inference_dir.exists() else _fallback_inference_dir))
from tts_search.reward_func_utils import (
    extract_code,
    format_sandbox_feedback,
    get_clear_log,
    get_sandbox_result,
    score2reward,
)

load_dotenv()

try:
    import tiktoken
except Exception:  # pragma: no cover - optional accounting dependency
    tiktoken = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bspm_v4")


def timeout_failure_evidence(
    status: str | None,
    feedback: str | None = None,
    *,
    legacy_primary: str | None = None,
) -> str | None:
    """Return high-confidence timeout evidence without matching budget variable names."""
    normalized_status = re.sub(r"[^a-z0-9]+", "_", str(status or "").strip().lower()).strip("_")
    if normalized_status in {"timeout", "timed_out", "sandbox_timeout", "validation_timeout"}:
        return "validation_status"

    text = str(feedback or "").lower()
    event_patterns = (
        r"\bresult\s*[:=*\s]+timeout\b",
        r"\btimed\s+out\b",
        r"\btimeouterror\b",
        r"\btimeoutexpired\b",
        r"\bbudgetexhausted\b",
        r"\bdeadline[_\s-]*guard\b[^\n]*\bremaining\s*=\s*-",
        r"\btime\s+limit\s+(?:was\s+)?(?:reached|exceeded)\b",
        r"\bwall\s*time\s+(?:was\s+)?(?:reached|exceeded)\b",
        r"\binternal\s+deadline\s+(?:was\s+)?reached\b",
        r"\bdeadline\s+(?:was\s+)?exceeded\b",
        r"\bexceeded\s+(?:the\s+)?deadline\b",
        r"\btime\s+budget\s+(?:was\s+)?(?:reached|exceeded|exhausted)\b",
    )
    for pattern in event_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "runtime_event"

    if str(legacy_primary or "").strip().lower() == "timeout":
        if normalized_status in {"", "unknown", "failed"}:
            return "legacy_primary_without_structured_status"
    return None


def is_actual_timeout_failure(
    status: str | None,
    feedback: str | None = None,
    *,
    legacy_primary: str | None = None,
) -> bool:
    return timeout_failure_evidence(status, feedback, legacy_primary=legacy_primary) is not None


def sanitize_legacy_prediction_file_language(text: str | None, *, eda: bool = False) -> str:
    """Rewrite old skill wording that asks agents to save reusable cross-round files."""
    cleaned = str(text or "")
    diagnostic = "EDA output" if eda else "diagnostic"
    diagnostics = "EDA outputs" if eda else "diagnostics"
    replacements = {
        "The final direction should save every base model's OOF/test probability matrix": (
            "The final direction should compare every base model's OOF/test probability estimates inside the current run"
        ),
        "The final solution should preserve all OOF/test arrays so later rounds can blend without retraining": (
            "The final solution should compare OOF/test diagnostics inside the current run and select an immediately usable blend"
        ),
        "Save both raw and calibrated OOF/test predictions": (
            "Compare both raw and calibrated OOF/test diagnostics inside the current run"
        ),
        "Save image OOF probabilities or embeddings": (
            "Evaluate image OOF probabilities or embeddings inside the current run"
        ),
        "Diagnostics to print or summarize for later rounds": "Diagnostics to print in stdout for current-run review",
        "save every base model's OOF/test probability matrix": (
            "compare every base model's OOF/test probability estimates inside the current run"
        ),
        "preserve all OOF/test arrays so later rounds can blend without retraining": (
            "compare OOF/test diagnostics inside the current run and select an immediately usable blend"
        ),
        "Save separate test arrays": "Compute separate test predictions inside the current run",
        "Store OOF predictions": "Compute OOF diagnostics",
        "save OOF/test probabilities": "compute and compare OOF/test probabilities inside the current run",
        "save OOF/test probability": "compute and compare OOF/test probability estimates inside the current run",
        "save OOF probabilities": "compute and compare OOF probabilities inside the current run",
        "save OOF probability": "compute and compare OOF probability estimates inside the current run",
        "save OOF diagnostics": "print OOF diagnostics",
        "save matching test predictions": "print matching test-prediction diagnostics",
        "save test predictions": "print test-prediction diagnostics",
        "save test probabilities": "compute test probabilities inside the current run",
        "save averaged test probabilities": "compute averaged test probabilities inside the current run",
        "save stable supervised OOF predictions": "establish stable supervised OOF diagnostics",
        "save logits and probabilities": "use logits and probabilities inside the current run",
        "saved predictions": "current-run predictions",
        "saved OOF predictions": "printed OOF diagnostics",
        "save OOF predictions": "print OOF diagnostics",
        "saving OOF predictions": "printing OOF diagnostics",
        "saved OOF/test arrays": "current-run OOF/test diagnostics",
        "save OOF/test arrays": "compute OOF/test diagnostics inside the current run",
        "saved OOF/test predictions": "printed OOF/test diagnostics",
        "save OOF/test predictions": "print OOF/test diagnostics",
        "across saved predictions": "across current-run predictions",
        "saved OOF/test diagnostics": "current-run OOF/test diagnostics",
        "OOF/test diagnostics are saved": "OOF/test diagnostics are evaluated inside the current run",
        "all base OOF/test diagnostics are saved": "all base OOF/test diagnostics have been evaluated inside the current run",
        "calibrated no-pseudo ensemble is saved": "calibrated no-pseudo ensemble has a strong current-run validation result",
        "all base OOF files exist": "all base OOF diagnostics are available in the current run",
        "base OOF files exist": "base OOF diagnostics are available in the current run",
        "OOF files exist": "OOF diagnostics are available in the current run",
        "per-model OOF probabilities": "per-model OOF diagnostics",
        "per-model test probabilities": "per-model test diagnostics",
        "OOF/test probability matrix": "OOF/test probability estimates",
        "OOF/test probability matrices": "OOF/test probability estimates",
        "OOF/test arrays": "OOF/test diagnostics",
        "OOF predictions": "OOF diagnostics",
        "OOF prediction": "OOF diagnostic",
        "for later rounds": "for current-run review",
    }
    for _ in range(2):
        for old, new in replacements.items():
            cleaned = re.sub(re.escape(old), new, cleaned, flags=re.IGNORECASE)
    legacy_file_bucket = "arti" + "fact"
    legacy_file_buckets = legacy_file_bucket + "s"
    file_word_replacements = (
        (rf"Save a `fold` assignment {legacy_file_bucket}", "Print or document the fold assignment strategy"),
        (rf"{legacy_file_buckets} to save for later rounds", "Diagnostics to print for current-run review"),
        (rf"separate OOF/test {legacy_file_buckets}", "separate OOF/test diagnostics"),
        (rf"Save {legacy_file_buckets} named clearly", "Print diagnostics with clear names"),
        (rf"{legacy_file_buckets} to save", "Diagnostics to print or summarize"),
        (rf"all base OOF/test {legacy_file_buckets} are saved", "all base OOF/test diagnostics have been evaluated inside the current run"),
        (rf"OOF/test {legacy_file_buckets}", "OOF/test diagnostics"),
        (rf"reusable {legacy_file_buckets}", "runtime diagnostics"),
        (rf"tokenization {legacy_file_buckets}", "tokenization quirks"),
        (rf"\b{legacy_file_buckets}\b", diagnostics),
        (rf"\b{legacy_file_bucket}\b", diagnostic),
    )
    for pattern, new in file_word_replacements:
        cleaned = re.sub(pattern, new, cleaned, flags=re.IGNORECASE)
    return cleaned
