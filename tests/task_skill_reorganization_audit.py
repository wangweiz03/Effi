#!/usr/bin/env python3
"""Generate and audit content-conserving task-skill reorganizations.

The audit treats every Markdown prose paragraph and every list item as an
immutable content block. Headings and blank lines are structural. A candidate
is valid only when every non-deleted source block appears exactly once and no
new content block appears.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


DEFAULT_SOURCE_DIR = Path(
    "/hpc_data/weizwang@weizwang/frameworks/resources/mle-reimagined"
)
DEFAULT_CANDIDATE_DIR = Path("/tmp/task_skill_reorganization_candidates")
DEFAULT_MANIFEST = Path(__file__).with_name("task_skill_reorganization_manifest.json")

TASK_FILES = (
    "SKILL_siim-isic-melanoma-classification.md",
    "SKILL_aptos2019-blindness-detection.md",
    "SKILL_jigsaw-toxic-comment-classification-challenge.md",
    "SKILL_tabular-playground-series-may-2022.md",
    "SKILL_ranzcr-clip-catheter-line-classification.md",
)

TARGET_SECTIONS = (
    "Task Contract And Traps",
    "Seed Route",
    "Improve Library",
    "Debug And Fallback",
    "Validation Contract",
    "Avoid Or Delay",
)

TASK_CONTRACT = TARGET_SECTIONS[0]
SEED_ROUTE = TARGET_SECTIONS[1]
IMPROVE_LIBRARY = TARGET_SECTIONS[2]
DEBUG_FALLBACK = TARGET_SECTIONS[3]
VALIDATION_CONTRACT = TARGET_SECTIONS[4]
AVOID_DELAY = TARGET_SECTIONS[5]


@dataclass(frozen=True)
class Block:
    source_section: str
    text: str
    ordinal: int


@dataclass(frozen=True)
class DeletionRule:
    fragment: str
    reason: str


# These are the only content deletions permitted by the final plan. Matching is
# intentionally exact enough to fail if a source paragraph changes silently.
DELETION_RULES: dict[str, tuple[DeletionRule, ...]] = {
    "SKILL_siim-isic-melanoma-classification.md": (),
    "SKILL_aptos2019-blindness-detection.md": (
        DeletionRule(
            "Compute is enough for serious image training but not a large research stack",
            "obsolete fixed 12-hour runtime assumption",
        ),
        DeletionRule(
            "Save artifacts for later rounds:",
            "cross-round artifact persistence",
        ),
        DeletionRule(
            "Fallback if training is too slow:",
            "fallback paragraph requires preserving cross-round artifacts",
        ),
    ),
    "SKILL_jigsaw-toxic-comment-classification-challenge.md": (
        DeletionRule(
            "Resource shape: 6 CPU cores, 200 GB RAM, 24 GB VRAM, and 12 hours",
            "obsolete fixed 12-hour runtime assumption",
        ),
        DeletionRule(
            "A full sparse ensemble can be trained on CPU well inside the runtime budget",
            "obsolete runtime-feasibility claim",
        ),
        DeletionRule(
            "Then make the strong first run in the same script:",
            "same-script first-valid-to-strong connection",
        ),
        DeletionRule(
            "Transformer branch for the same first-round script",
            "same-script first-valid-to-strong connection",
        ),
        DeletionRule(
            "Save OOF/test logits and probabilities so later rounds can blend without retraining.",
            "cross-round artifact persistence",
        ),
        DeletionRule(
            "For OOF artifacts, save at minimum:",
            "cross-round artifact persistence",
        ),
    ),
    "SKILL_tabular-playground-series-may-2022.md": (
        DeletionRule(
            "Compute: 6 CPU cores, 200 GB RAM, 24 GB VRAM, and 12 hours",
            "obsolete fixed 12-hour runtime assumption",
        ),
        DeletionRule(
            "Strong first run after the smoke path works:",
            "same-script first-valid-to-strong connection",
        ),
        DeletionRule(
            "Save artifacts: fold assignments",
            "cross-round artifact persistence",
        ),
        DeletionRule(
            "Required artifacts for later rounds are OOF predictions",
            "cross-round artifact persistence",
        ),
        DeletionRule(
            "Save every base model's OOF/test predictions.",
            "cross-round artifact persistence",
        ),
    ),
    "SKILL_ranzcr-clip-catheter-line-classification.md": (
        DeletionRule(
            "Compute: 6 CPU cores, 200 GB RAM, 16 GB shared memory, 24 GB VRAM, and 12 hours",
            "obsolete fixed 12-hour runtime assumption",
        ),
        DeletionRule(
            "Artifact saving: keep fold assignments",
            "cross-round artifact persistence",
        ),
        DeletionRule(
            "A small diverse ensemble is more feasible than many near-identical checkpoints under the 12-hour budget.",
            "obsolete fixed 12-hour runtime assumption",
        ),
    ),
}


LIST_ITEM_RE = re.compile(r"^\s*(?:[-+*]|\d+\.)\s+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
NUMBERED_SECTION_RE = re.compile(r"^(\d+)\.\s+")


def _normalize_block(lines: list[str]) -> str:
    return "\n".join(line.strip() for line in lines).strip()


def parse_blocks(text: str) -> tuple[str, list[Block]]:
    """Return the level-one title and immutable non-heading content blocks."""
    title = ""
    source_section = ""
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        normalized = _normalize_block(paragraph)
        if normalized:
            blocks.append(Block(source_section, normalized, len(blocks)))
        paragraph.clear()

    for raw_line in text.splitlines():
        heading_match = HEADING_RE.match(raw_line.strip())
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            if level == 1 and not title:
                title = heading
            elif level == 2:
                source_section = heading
            continue

        if not raw_line.strip():
            flush_paragraph()
            continue

        if LIST_ITEM_RE.match(raw_line):
            flush_paragraph()
            blocks.append(Block(source_section, raw_line.strip(), len(blocks)))
            continue

        paragraph.append(raw_line)

    flush_paragraph()
    if not title:
        raise ValueError("Markdown source has no level-one title")
    return title, blocks


def _section_number(source_section: str) -> int:
    match = NUMBERED_SECTION_RE.match(source_section)
    if not match:
        raise ValueError(f"Unrecognized source section: {source_section!r}")
    return int(match.group(1))


def _matches(text: str, *fragments: str) -> bool:
    return any(fragment in text for fragment in fragments)


def route_block(task_file: str, block: Block) -> str:
    """Map an unchanged source block to one of the six target sections."""
    section = _section_number(block.source_section)
    text = block.text

    if section == 1:
        return TASK_CONTRACT
    if section == 5:
        return VALIDATION_CONTRACT
    if section == 6:
        return IMPROVE_LIBRARY
    if section == 7:
        if task_file == "SKILL_siim-isic-melanoma-classification.md" and _matches(
            text, "Do not repeat a timed-out parent unchanged."
        ):
            return DEBUG_FALLBACK
        return AVOID_DELAY
    if section == 4:
        if task_file == "SKILL_siim-isic-melanoma-classification.md" and _matches(
            text, "For timeout/OOM debug"
        ):
            return DEBUG_FALLBACK
        return IMPROVE_LIBRARY

    if section == 2:
        if task_file == "SKILL_aptos2019-blindness-detection.md":
            if _matches(text, "Treat validation as", "Select models and postprocessing"):
                return VALIDATION_CONTRACT
            if _matches(
                text,
                "Converge toward a fold ensemble",
                "Primary model families:",
                "The endpoint is probability averaging",
            ):
                return IMPROVE_LIBRARY
        elif task_file == "SKILL_jigsaw-toxic-comment-classification-challenge.md":
            if _matches(
                text,
                "Converge toward a compact ensemble",
                "a strong sparse linear family:",
                "a shared-encoder transformer family",
                "an OOF-trained blend or stack",
            ):
                return IMPROVE_LIBRARY
            if _matches(text, "highest-value validation geometry", "For the metric, preserve order"):
                return VALIDATION_CONTRACT
            if _matches(text, "Do not over-invest in calibration"):
                return AVOID_DELAY
        elif task_file == "SKILL_ranzcr-clip-catheter-line-classification.md":
            if _matches(text, "Use `PatientID` grouped folds"):
                return VALIDATION_CONTRACT
            if _matches(
                text,
                "Converge toward an ensemble",
                "First-class model families:",
                "Annotation-assisted endpoint:",
                "Inference: average fold probabilities",
            ):
                return IMPROVE_LIBRARY
            if _matches(text, "Final postprocessing should remain probability-preserving"):
                return VALIDATION_CONTRACT
        elif task_file == "SKILL_siim-isic-melanoma-classification.md":
            if _matches(
                text,
                "Improve only the validation-best parent.",
                "For each completed fold, infer validation and test scores",
            ):
                return IMPROVE_LIBRARY
            if _matches(text, "External 2017/2018/2019 data"):
                return AVOID_DELAY
        elif task_file == "SKILL_tabular-playground-series-may-2022.md":
            if _matches(text, "Use stratified 5-fold CV as the main score surface"):
                return VALIDATION_CONTRACT
            if _matches(
                text,
                "Converge toward an OOF-driven ensemble",
                "Build around three base families:",
                "`gbdt_interaction_auc`:",
                "`oof_target_encoding_gbdt_auc`:",
                "`xgb_regularized_interaction_auc`:",
                "`catboost_stringcat_auc`:",
                "`tabular_embedding_mlp_auc`:",
                "The final endpoint should blend",
            ):
                return IMPROVE_LIBRARY
        return SEED_ROUTE

    if section != 3:
        raise AssertionError(f"Unhandled source section {section}")

    if task_file == "SKILL_aptos2019-blindness-detection.md":
        if _matches(text, "First-valid path:", "Train one fast fold", "Compute OOF probabilities", "Save fold predictions"):
            return SEED_ROUTE
        if _matches(text, "Fallback if training is too slow"):
            return DEBUG_FALLBACK
        return IMPROVE_LIBRARY

    if task_file == "SKILL_jigsaw-toxic-comment-classification-challenge.md":
        if _matches(
            text,
            "Start with a fast first-valid path:",
            "Build a 3-fold multilabel",
            "Vectorize `comment_text` with a moderate",
            "Train one-vs-rest",
            "Produce OOF predictions",
        ):
            return SEED_ROUTE
        if _matches(text, "Fallback if the transformer route"):
            return DEBUG_FALLBACK
        return IMPROVE_LIBRARY

    if task_file == "SKILL_tabular-playground-series-may-2022.md":
        if _matches(
            text,
            "First-valid submission path:",
            "Load train, test, and sample submission.",
            "Drop `id` from the model features initially.",
            "Split `f_27` into ten character-position",
            "Train a 3-fold or 5-fold LightGBM",
            "Score OOF with `roc_auc_score",
        ):
            return SEED_ROUTE
        if _matches(text, "Fallback: if CatBoost is too slow"):
            return DEBUG_FALLBACK
        return IMPROVE_LIBRARY

    if task_file == "SKILL_ranzcr-clip-catheter-line-classification.md":
        if _matches(text, "Strong first run: train"):
            return IMPROVE_LIBRARY
        if _matches(text, "Runtime fallback:"):
            return DEBUG_FALLBACK
        return SEED_ROUTE

    if task_file == "SKILL_siim-isic-melanoma-classification.md":
        return SEED_ROUTE

    raise AssertionError(f"Unhandled task file {task_file}")


def deletion_reason(task_file: str, block: Block) -> str | None:
    matched = [rule.reason for rule in DELETION_RULES[task_file] if rule.fragment in block.text]
    if len(matched) > 1:
        raise AssertionError(f"Multiple deletion rules match block: {block.text}")
    return matched[0] if matched else None


def build_candidate(task_file: str, source_text: str) -> tuple[str, list[tuple[Block, str]]]:
    title, blocks = parse_blocks(source_text)
    routed: dict[str, list[Block]] = defaultdict(list)
    deleted: list[tuple[Block, str]] = []
    for block in blocks:
        reason = deletion_reason(task_file, block)
        if reason:
            deleted.append((block, reason))
            continue
        routed[route_block(task_file, block)].append(block)

    lines = [f"# {title}", ""]
    for section in TARGET_SECTIONS:
        lines.extend((f"## {section}", ""))
        for block in routed[section]:
            lines.extend((block.text, ""))
    return "\n".join(lines).rstrip() + "\n", deleted


def _content_counter(text: str) -> Counter[str]:
    _, blocks = parse_blocks(text)
    return Counter(block.text for block in blocks)


def audit_candidate(task_file: str, source_text: str, candidate_text: str) -> dict[str, object]:
    source_title, source_blocks = parse_blocks(source_text)
    source_counter = Counter(block.text for block in source_blocks)
    candidate_counter = _content_counter(candidate_text)
    deleted = [(block, deletion_reason(task_file, block)) for block in source_blocks]
    deleted = [(block, reason) for block, reason in deleted if reason]
    deleted_counter = Counter(block.text for block, _ in deleted)

    expected_counter = source_counter - deleted_counter
    added = candidate_counter - expected_counter
    missing = expected_counter - candidate_counter
    duplicated = candidate_counter - source_counter
    if added or missing or duplicated:
        raise AssertionError(
            f"{task_file}: provenance mismatch; added={dict(added)}, "
            f"missing={dict(missing)}, duplicated={dict(duplicated)}"
        )

    candidate_title, candidate_blocks = parse_blocks(candidate_text)
    if candidate_title != source_title:
        raise AssertionError(
            f"{task_file}: title changed from {source_title!r} to {candidate_title!r}"
        )

    expected_routing = Counter(
        (block.text, route_block(task_file, block))
        for block in source_blocks
        if deletion_reason(task_file, block) is None
    )
    actual_routing = Counter((block.text, block.source_section) for block in candidate_blocks)
    if expected_routing != actual_routing:
        raise AssertionError(f"{task_file}: one or more source blocks are in the wrong target section")

    level_two = [
        match.group(2).strip()
        for line in candidate_text.splitlines()
        if (match := HEADING_RE.match(line.strip())) and len(match.group(1)) == 2
    ]
    if tuple(level_two) != TARGET_SECTIONS:
        raise AssertionError(
            f"{task_file}: target headings are {level_two}, expected {TARGET_SECTIONS}"
        )

    forbidden_patterns = (
        r"\b12[- ]hours?\b",
        r"same first-round script",
        r"strong first run in the same script",
        r"Save artifacts for later rounds",
        r"Required artifacts for later rounds",
        r"Artifact saving: keep fold assignments",
    )
    for pattern in forbidden_patterns:
        if re.search(pattern, candidate_text, flags=re.IGNORECASE):
            raise AssertionError(f"{task_file}: forbidden stale content remains: {pattern}")

    section_counts: Counter[str] = Counter()
    for block in candidate_blocks:
        section_counts[block.source_section] += 1

    digest = hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()
    return {
        "title": source_title,
        "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "source_blocks": sum(source_counter.values()),
        "candidate_blocks": sum(candidate_counter.values()),
        "deleted_blocks": len(deleted),
        "deleted": [
            {
                "sha256": hashlib.sha256(block.text.encode("utf-8")).hexdigest(),
                "reason": reason,
                "text": block.text,
            }
            for block, reason in deleted
        ],
        "section_counts": {section: section_counts[section] for section in TARGET_SECTIONS},
        "candidate_sha256": digest,
        "expected_routing": [
            {
                "content_sha256": hashlib.sha256(block.text.encode("utf-8")).hexdigest(),
                "section": route_block(task_file, block),
            }
            for block in source_blocks
            if deletion_reason(task_file, block) is None
        ],
    }


def audit_candidate_against_manifest(
    task_file: str,
    candidate_text: str,
    expected: dict[str, object],
) -> dict[str, object]:
    """Audit an installed skill without depending on the overwritten source file."""
    title, blocks = parse_blocks(candidate_text)
    if title != expected["title"]:
        raise AssertionError(f"{task_file}: title differs from immutable manifest")

    actual_routing = Counter(
        (hashlib.sha256(block.text.encode("utf-8")).hexdigest(), block.source_section)
        for block in blocks
    )
    expected_routing = Counter(
        (str(item["content_sha256"]), str(item["section"]))
        for item in expected["expected_routing"]
    )
    if actual_routing != expected_routing:
        added = actual_routing - expected_routing
        missing = expected_routing - actual_routing
        raise AssertionError(
            f"{task_file}: immutable provenance mismatch; added={dict(added)}, missing={dict(missing)}"
        )

    headings = [
        match.group(2).strip()
        for line in candidate_text.splitlines()
        if (match := HEADING_RE.match(line.strip())) and len(match.group(1)) == 2
    ]
    if tuple(headings) != TARGET_SECTIONS:
        raise AssertionError(f"{task_file}: standardized headings changed: {headings}")

    digest = hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()
    if digest != expected["candidate_sha256"]:
        raise AssertionError(
            f"{task_file}: exact candidate digest changed: {digest} != {expected['candidate_sha256']}"
        )
    section_counts = Counter(block.source_section for block in blocks)
    return {
        "candidate_blocks": len(blocks),
        "deleted_blocks": len(expected.get("deleted", [])),
        "section_counts": {section: section_counts[section] for section in TARGET_SECTIONS},
        "candidate_sha256": digest,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_CANDIDATE_DIR)
    parser.add_argument("--write-candidates", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()

    if args.write_candidates:
        args.candidate_dir.mkdir(parents=True, exist_ok=True)

    manifest_payload: dict[str, object] = {
        "schema_version": "task_skill_reorganization_manifest_v1",
        "files": {},
    }
    installed_manifest = None
    if args.manifest.exists() and not args.write_manifest and not args.write_candidates:
        installed_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    for task_file in TASK_FILES:
        source_path = args.source_dir / task_file
        candidate_path = args.candidate_dir / task_file
        if installed_manifest is not None:
            candidate_text = candidate_path.read_text(encoding="utf-8")
            result = audit_candidate_against_manifest(
                task_file,
                candidate_text,
                installed_manifest["files"][task_file],
            )
            counts = ", ".join(
                f"{section}={count}" for section, count in result["section_counts"].items()
            )
            print(
                f"PASS {task_file}: candidate={result['candidate_blocks']} "
                f"deleted={result['deleted_blocks']} sha256={result['candidate_sha256']}"
            )
            print(f"  sections: {counts}")
            continue
        source_text = source_path.read_text(encoding="utf-8")
        _, source_blocks = parse_blocks(source_text)
        for rule in DELETION_RULES[task_file]:
            matched = [block for block in source_blocks if rule.fragment in block.text]
            if len(matched) != 1:
                raise AssertionError(
                    f"{task_file}: deletion rule {rule.fragment!r} matched "
                    f"{len(matched)} source blocks; expected exactly one"
                )
        if args.write_candidates:
            candidate_text, _ = build_candidate(task_file, source_text)
            candidate_path.write_text(candidate_text, encoding="utf-8")
        else:
            candidate_text = candidate_path.read_text(encoding="utf-8")

        result = audit_candidate(task_file, source_text, candidate_text)
        manifest_payload["files"][task_file] = result
        counts = ", ".join(
            f"{section}={count}" for section, count in result["section_counts"].items()
        )
        print(
            f"PASS {task_file}: source={result['source_blocks']} "
            f"candidate={result['candidate_blocks']} deleted={result['deleted_blocks']} "
            f"sha256={result['candidate_sha256']}"
        )
        print(f"  sections: {counts}")
        for item in result["deleted"]:
            print(f"  deleted {item['sha256'][:12]} {item['reason']}: {item['text']}")

    if args.write_manifest:
        args.manifest.write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
