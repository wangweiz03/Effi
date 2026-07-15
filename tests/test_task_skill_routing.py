from __future__ import annotations

from pathlib import Path

from runtime.skills import (
    STANDARD_TASK_SKILL_SECTIONS,
    build_branch_task_skill_view,
    extract_skill_schema,
)
from runtime.bootstrap import SkillRoute, persist_runtime_skill_sources


def _standard_skill() -> str:
    lines = ["# Example", ""]
    for section in STANDARD_TASK_SKILL_SECTIONS:
        lines.extend((f"## {section}", "", f"content:{section}", ""))
    return "\n".join(lines)


def test_standard_task_skill_is_scoped_by_branch_without_truncation() -> None:
    skill = _standard_skill()
    expected = {
        "draft": {"Task Contract And Traps", "Seed Route", "Validation Contract", "Avoid Or Delay"},
        "debug": {"Task Contract And Traps", "Debug And Fallback", "Validation Contract", "Avoid Or Delay"},
        "improve": {"Task Contract And Traps", "Improve Library", "Validation Contract", "Avoid Or Delay"},
    }
    for branch, included in expected.items():
        routed, scoped = build_branch_task_skill_view(skill, branch)
        assert scoped is True
        for section in STANDARD_TASK_SKILL_SECTIONS:
            assert (f"content:{section}" in routed) is (section in included)


def test_legacy_task_skill_remains_full_for_compatibility() -> None:
    legacy = (
        "# Legacy\n\n"
        "## 1. Task-specific reading\n\nKeep this exact text.\n\n"
        "## 7. What to avoid or delay\n\nKeep this old avoid section.\n"
    )
    routed, scoped = build_branch_task_skill_view(legacy, "draft")
    assert scoped is False
    assert routed == legacy
    schema = extract_skill_schema(legacy)
    assert "Keep this exact text." in schema["task_contract"]
    assert "Keep this old avoid section." in schema["avoid_rules"]


def test_standard_schema_exposes_debug_fallback() -> None:
    schema = extract_skill_schema(_standard_skill())
    assert "content:Seed Route" in schema["first_run"]
    assert "content:Improve Library" in schema["upgrade_menu"]
    assert "content:Debug And Fallback" in schema["debug_fallback"]


def test_installed_heavy_task_skill_uses_standard_schema() -> None:
    path = Path(
        "/hpc_data/weizwang@weizwang/frameworks/resources/mle-reimagined/"
        "SKILL_jigsaw-toxic-comment-classification-challenge.md"
    )
    routed, scoped = build_branch_task_skill_view(path.read_text(encoding="utf-8"), "draft")
    assert scoped is True
    assert "## Seed Route" in routed
    assert "## Improve Library" not in routed
    assert "## Debug And Fallback" not in routed


def test_persisted_task_skill_source_is_the_branch_view(tmp_path: Path) -> None:
    task_dir = tmp_path / "demo"
    task_dir.mkdir()
    source = tmp_path / "SKILL_demo.md"
    source.write_text(_standard_skill(), encoding="utf-8")
    route = SkillRoute(branch="debug", reason="test", sources=[str(source)], content="guard")

    persisted = persist_runtime_skill_sources(task_dir, route)
    text = Path(persisted.sources[0]).read_text(encoding="utf-8")

    assert "Phase scoped: true" in text
    assert "## Debug And Fallback" in text
    assert "## Seed Route" not in text
    assert "## Improve Library" not in text
