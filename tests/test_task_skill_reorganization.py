from __future__ import annotations

import json

from task_skill_reorganization_audit import (
    DEFAULT_MANIFEST,
    DEFAULT_SOURCE_DIR,
    TASK_FILES,
    audit_candidate_against_manifest,
)


def test_installed_task_skills_match_immutable_provenance_manifest() -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    for task_file in TASK_FILES:
        candidate = (DEFAULT_SOURCE_DIR / task_file).read_text(encoding="utf-8")
        result = audit_candidate_against_manifest(
            task_file,
            candidate,
            manifest["files"][task_file],
        )
        assert result["candidate_sha256"] == manifest["files"][task_file]["candidate_sha256"]
