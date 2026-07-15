from __future__ import annotations

from pathlib import Path

from runtime.model_cache import (
    SANDBOX_MODEL_CACHE_RELATIVE_PATH,
    SANDBOX_MODEL_CACHE_SOURCE_PATH,
    persist_sandbox_model_cache,
)


def _inventory_rows(path: Path) -> list[list[str]]:
    return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]


def test_static_model_cache_contains_only_complete_entries() -> None:
    rows = _inventory_rows(SANDBOX_MODEL_CACHE_SOURCE_PATH)
    hf_rows = [row for row in rows if row[0] == "HF"]
    torch_rows = [row for row in rows if row[0] == "TORCH"]

    assert len(rows) == 648
    assert len(hf_rows) == 539
    assert len(torch_rows) == 109
    assert all(len(row) == 4 for row in hf_rows)
    assert all(len(row) == 3 for row in torch_rows)
    assert len({row[1] for row in hf_rows}) == 539
    assert len({row[1] for row in torch_rows}) == 109
    assert all(row[2].startswith("revision=") for row in hf_rows)
    assert all(row[-1].startswith("bytes=") for row in rows)

    upper = SANDBOX_MODEL_CACHE_SOURCE_PATH.read_text(encoding="utf-8").upper()
    assert "READY" not in upper
    assert "PARTIAL" not in upper
    assert "INCOMPLETE" not in upper


def test_persist_sandbox_model_cache_copies_static_inventory(tmp_path: Path) -> None:
    target = persist_sandbox_model_cache(tmp_path)

    assert target == tmp_path / SANDBOX_MODEL_CACHE_RELATIVE_PATH
    assert target.read_bytes() == SANDBOX_MODEL_CACHE_SOURCE_PATH.read_bytes()
