from __future__ import annotations

import shutil
from pathlib import Path


SANDBOX_MODEL_CACHE_RELATIVE_PATH = Path("context_sources/sandbox_model_cache.txt")
SANDBOX_MODEL_CACHE_SOURCE_PATH = Path(__file__).with_name("sandbox_model_cache.txt")


def persist_sandbox_model_cache(task_dir: Path) -> Path:
    """Copy the fixed offline model inventory into a task's context sources."""
    target = task_dir / SANDBOX_MODEL_CACHE_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SANDBOX_MODEL_CACHE_SOURCE_PATH, target)
    return target
