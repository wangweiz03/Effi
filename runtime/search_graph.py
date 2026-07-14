from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import *
from .constants import *


EMPTY_VALUES = (None, "", [], {})


def _safe_load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_jsonl_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _rel_path(task_dir: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(task_dir.resolve()))
    except Exception:
        return str(path)


def _atomic_replace_file(tmp: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(target)


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _shorten(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _format_score(value: Any) -> str:
    score = _as_float(value)
    if score is None:
        return "-"
    return f"{score:.6g}"


def _format_time(value: Any) -> str:
    seconds = _as_float(value)
    if seconds is None:
        return "-"
    if seconds >= 3600:
        return f"{seconds / 3600:.2f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"


def _parent_round_from_payload(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    return _as_int(payload.get("round") or payload.get("parent_round") or payload.get("debug_parent_round"))


def _parent_commit_from_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("commit") or payload.get("parent_commit") or payload.get("debug_parent_commit") or "").strip()


def _merge_round_record(records: dict[int, dict[str, Any]], record: dict[str, Any]) -> None:
    round_num = _as_int(record.get("round"))
    if round_num is None:
        return
    existing = records.setdefault(round_num, {"round": round_num, "sources": []})
    source = str(record.pop("_source", "") or "")
    if source and source not in existing["sources"]:
        existing["sources"].append(source)
    for key, value in record.items():
        if value in EMPTY_VALUES:
            continue
        if key == "round":
            existing[key] = round_num
            continue
        if key not in existing or existing.get(key) in EMPTY_VALUES:
            existing[key] = value
            continue
        if key in {
            "branch",
            "effective_branch",
            "branch_state",
            "status",
            "score",
            "raw_score",
            "run_time",
            "wall_time",
            "failure_primary",
            "feedback_excerpt",
            "error_excerpt",
            "method_family",
            "method_summary",
            "memory_card_path",
            "memory_diff_path",
            "code_path",
            "validation_feedback_path",
        }:
            existing[key] = value


def _record_from_graph_node(row: dict[str, Any]) -> dict[str, Any]:
    validation = row.get("validation") if isinstance(row.get("validation"), dict) else {}
    method = row.get("method") if isinstance(row.get("method"), dict) else {}
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    static_gate = row.get("static_gate") if isinstance(row.get("static_gate"), dict) else {}
    commit_paths = row.get("commit_paths") if isinstance(row.get("commit_paths"), dict) else {}
    failure_primary = validation.get("failure_primary")
    blockers = static_gate.get("blockers") if isinstance(static_gate.get("blockers"), list) else []
    return {
        "_source": "graph_nodes",
        "round": row.get("round"),
        "node_id": row.get("node_id"),
        "commit": row.get("commit"),
        "branch": row.get("branch"),
        "effective_branch": row.get("effective_branch"),
        "status": validation.get("status"),
        "score": validation.get("score"),
        "raw_score": validation.get("raw_score"),
        "run_time": validation.get("run_time"),
        "wall_time": row.get("wall_time"),
        "failure_primary": failure_primary or (blockers[0] if blockers else ""),
        "method_family": method.get("family_canonical") or method.get("family"),
        "method_summary": method.get("summary"),
        "parent_commit": row.get("parent_commit"),
        "anchor_parent": row.get("anchor_parent"),
        "debug_parent": row.get("debug_parent"),
        "memory_card_path": row.get("memory_card_path"),
        "memory_diff_path": row.get("memory_diff_path"),
        "code_path": commit_paths.get("solution_path"),
        "validation_feedback_path": (
            f"commits/{row.get('commit')}/validation_feedback.txt" if row.get("commit") else None
        ),
    }


def _record_from_summary_round(row: dict[str, Any]) -> dict[str, Any]:
    validation = row.get("validation") if isinstance(row.get("validation"), dict) else {}
    quality = validation.get("quality") if isinstance(validation.get("quality"), dict) else {}
    failure_taxonomy = validation.get("failure_taxonomy") if isinstance(validation.get("failure_taxonomy"), dict) else {}
    branch_decision = row.get("branch_decision") if isinstance(row.get("branch_decision"), dict) else {}
    round_summary = row.get("round_summary") if isinstance(row.get("round_summary"), dict) else {}
    status = row.get("status") or validation.get("status")
    failure_primary = failure_taxonomy.get("primary") or quality.get("reason") or row.get("failure_primary")
    feedback_excerpt = validation.get("feedback_excerpt") or round_summary.get("result_reflection")
    return {
        "_source": "rounds_summary",
        "round": row.get("round"),
        "commit": row.get("commit_hash") or row.get("commit"),
        "branch": row.get("branch"),
        "effective_branch": row.get("effective_branch"),
        "branch_state": branch_decision.get("branch_state"),
        "branch_reason": branch_decision.get("branch_reason") or branch_decision.get("reason"),
        "status": status,
        "score": validation.get("score") if validation else row.get("score"),
        "raw_score": validation.get("raw_score"),
        "run_time": validation.get("run_time"),
        "wall_time": row.get("round_wall_time"),
        "failure_primary": failure_primary,
        "feedback_excerpt": feedback_excerpt,
        "error_excerpt": row.get("error_excerpt"),
        "method_family": row.get("effective_method_family") or round_summary.get("method_family"),
        "method_summary": round_summary.get("method_summary"),
        "parent_commit": branch_decision.get("parent_commit"),
        "anchor_parent": branch_decision.get("anchor_parent"),
        "debug_parent": branch_decision.get("debug_parent"),
        "memory_card_path": row.get("memory_card_path"),
        "memory_diff_path": row.get("memory_diff_path"),
        "code_path": row.get("code_path"),
        "validation_feedback_path": row.get("validation_feedback_path"),
        "input_tokens": row.get("input_tokens"),
        "output_tokens": row.get("output_tokens"),
    }


def _record_from_memory_round(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "_source": "memory_rounds",
        "round": row.get("round"),
        "commit": row.get("commit"),
        "branch": row.get("branch"),
        "effective_branch": row.get("effective_branch"),
        "branch_state": row.get("branch_state"),
        "branch_reason": row.get("branch_reason") or row.get("reason"),
        "status": row.get("status"),
        "score": row.get("score"),
        "run_time": row.get("run_time"),
        "wall_time": row.get("wall_time"),
        "failure_primary": row.get("failure_primary"),
        "feedback_excerpt": row.get("reflection"),
        "method_family": row.get("method_family"),
        "method_summary": row.get("summary"),
        "anchor_parent": row.get("anchor_parent"),
        "debug_parent": row.get("debug_parent"),
        "memory_card_path": row.get("memory_card_path"),
        "memory_diff_path": row.get("memory_diff_path"),
        "input_tokens": row.get("input_tokens"),
        "output_tokens": row.get("output_tokens"),
    }


def _record_from_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "_source": "graph_events",
        "round": row.get("round"),
        "branch": row.get("branch"),
        "status": row.get("status") or row.get("event"),
        "wall_time": row.get("wall_time"),
        "failure_primary": row.get("status") or row.get("event"),
        "error_excerpt": row.get("error"),
    }


def _record_from_card_index(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "_source": "card_index",
        "round": row.get("round"),
        "commit": row.get("commit"),
        "branch": row.get("branch"),
        "branch_state": row.get("branch_state"),
        "branch_reason": row.get("branch_reason"),
        "status": row.get("status"),
        "score": row.get("score"),
        "run_time": row.get("sandbox_run_time"),
        "method_family": row.get("method_family"),
        "memory_card_path": row.get("card_path"),
        "memory_diff_path": row.get("diff_path"),
        "anchor_parent": row.get("anchor_parent"),
        "debug_parent": row.get("debug_parent"),
        "delta_label": row.get("delta_label"),
        "risk_tags": row.get("risk_tags"),
    }


def _resolve_parent(record: dict[str, Any], commit_to_round: dict[str, int]) -> tuple[int | None, str, str]:
    branch = str(record.get("branch") or "").lower()
    if branch == "draft":
        return None, "", ""
    ordered_refs: list[tuple[str, Any]] = []
    if branch == "debug":
        ordered_refs.extend([("debug", record.get("debug_parent")), ("anchor", record.get("anchor_parent"))])
    elif branch == "improve":
        ordered_refs.extend([("anchor", record.get("anchor_parent")), ("debug", record.get("debug_parent"))])
    else:
        ordered_refs.extend([("anchor", record.get("anchor_parent")), ("debug", record.get("debug_parent"))])
    ordered_refs.append(("parent", {"commit": record.get("parent_commit")}))
    for kind, payload in ordered_refs:
        parent_round = _parent_round_from_payload(payload)
        parent_commit = _parent_commit_from_payload(payload)
        if parent_round is None and parent_commit:
            parent_round = commit_to_round.get(parent_commit)
        if parent_round is None:
            continue
        if parent_round == record.get("round"):
            continue
        return parent_round, parent_commit, kind
    parent_commit = str(record.get("parent_commit") or "").strip()
    if parent_commit and parent_commit in commit_to_round and commit_to_round[parent_commit] != record.get("round"):
        return commit_to_round[parent_commit], parent_commit, "parent"
    return None, parent_commit, ""


def _status_class(node: dict[str, Any]) -> str:
    status = str(node.get("status") or "").lower()
    failure = str(node.get("failure_primary") or node.get("error_excerpt") or "").lower()
    if node.get("is_best"):
        return "best"
    if _as_float(node.get("score")) is not None:
        return "scored"
    if "llm" in status or "infra" in status or "connection" in failure:
        return "infra"
    if "timeout" in status or "timeout" in failure:
        return "timeout"
    if any(token in status or token in failure for token in ("error", "fail", "blocked", "duplicate", "no_commit")):
        return "failed"
    return "unknown"


def _node_color(node: dict[str, Any]) -> tuple[str, str]:
    status_class = _status_class(node)
    colors = {
        "best": ("#fff3bf", "#f08c00"),
        "scored": ("#d3f9d8", "#2f9e44"),
        "infra": ("#e5dbff", "#7048e8"),
        "timeout": ("#ffe8cc", "#f08c00"),
        "failed": ("#ffe3e3", "#e03131"),
        "unknown": ("#f1f3f5", "#868e96"),
    }
    return colors.get(status_class, colors["unknown"])


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return (0, 0, 0)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except Exception:
        return (0, 0, 0)


def _draw_text(draw: Any, xy: tuple[float, float], text: Any, *, fill: str = "#212529", font: Any = None) -> None:
    safe = str(text or "").encode("ascii", "replace").decode("ascii")
    draw.text(xy, safe, fill=_hex_to_rgb(fill), font=font)


def _draw_arrow(draw: Any, start: tuple[float, float], end: tuple[float, float], *, fill: str, width: int = 2) -> None:
    x1, y1 = start
    x2, y2 = end
    color = _hex_to_rgb(fill)
    if abs(y2 - y1) <= 8:
        points = [(x1, y1), (x2, y2)]
    elif x2 > x1 + 50:
        mid_x = min(x1 + 26, x2 - 24)
        points = [(x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)]
    else:
        mid_x = (x1 + x2) / 2
        points = [(x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)]
    draw.line(points, fill=color, width=width, joint="curve")
    arrow = [(x2, y2), (x2 - 9, y2 - 5), (x2 - 9, y2 + 5)]
    draw.polygon(arrow, fill=color)


def _graph_layout(state: dict[str, Any]) -> tuple[list[str], dict[str, int], dict[str, tuple[int, int]], int, int]:
    nodes = state.get("nodes") if isinstance(state.get("nodes"), list) else []
    branches = ["draft", "improve", "debug"]
    for branch in sorted({str(node.get("branch") or "unknown") for node in nodes}):
        if branch not in branches:
            branches.append(branch)
    lane_y = {branch: 118 + idx * 182 for idx, branch in enumerate(branches)}
    max_round = max([_as_int(node.get("round")) or 0 for node in nodes], default=0)
    width = max(1100, 260 + (max_round + 1) * 190)
    height = max(420, 190 + len(branches) * 182)
    positions: dict[str, tuple[int, int]] = {}
    for node in nodes:
        round_num = _as_int(node.get("round")) or 0
        branch = str(node.get("branch") or "unknown")
        positions[str(node.get("id"))] = (95 + round_num * 190, lane_y.get(branch, lane_y[branches[-1]]))
    return branches, lane_y, positions, width, height


def build_search_graph_state(task_dir: Path, higher_is_better: bool | None = True) -> dict[str, Any]:
    task_dir = Path(task_dir)
    graph_path = task_dir / V3_GRAPH_DIR
    summary = _safe_load_json(task_dir / "rounds_summary.json")
    records: dict[int, dict[str, Any]] = {}

    for row in _load_jsonl_file(task_dir / "memory_bank" / "rounds.jsonl"):
        _merge_round_record(records, _record_from_memory_round(row))
    for row in _load_jsonl_file(graph_path / "events.jsonl"):
        if row.get("event") == "round_without_commit" or row.get("round") is not None:
            _merge_round_record(records, _record_from_event(row))
    for row in _load_jsonl_file(graph_path / "nodes.jsonl"):
        _merge_round_record(records, _record_from_graph_node(row))
    summary_rounds = summary.get("rounds")
    for row in summary_rounds if isinstance(summary_rounds, list) else []:
        if isinstance(row, dict):
            _merge_round_record(records, _record_from_summary_round(row))
    for row in _load_jsonl_file(task_dir / "memory_bank" / "card_index.jsonl"):
        _merge_round_record(records, _record_from_card_index(row))

    commit_to_round: dict[str, int] = {}
    for round_num, record in records.items():
        commit = str(record.get("commit") or "").strip()
        if commit:
            commit_to_round[commit] = round_num

    nodes: list[dict[str, Any]] = []
    for round_num in sorted(records):
        record = dict(records[round_num])
        parent_round, parent_commit, parent_kind = _resolve_parent(record, commit_to_round)
        record["id"] = f"r{round_num}"
        record["label"] = f"R{round_num}"
        record["parent_round"] = parent_round
        record["parent_commit"] = parent_commit
        record["parent_kind"] = parent_kind
        record["score"] = _as_float(record.get("score"))
        record["raw_score"] = _as_float(record.get("raw_score"))
        record["run_time"] = _as_float(record.get("run_time"))
        record["wall_time"] = _as_float(record.get("wall_time"))
        record["feedback_excerpt"] = _shorten(record.get("feedback_excerpt") or record.get("error_excerpt"), 360)
        record["error_excerpt"] = _shorten(record.get("error_excerpt"), 240)
        record["method_summary"] = _shorten(record.get("method_summary"), 240)
        record["branch_reason"] = _shorten(record.get("branch_reason"), 180)
        nodes.append(record)

    scored_nodes = [node for node in nodes if node.get("score") is not None]
    best_round: int | None = None
    if scored_nodes:
        best = max(scored_nodes, key=lambda item: float(item["score"])) if higher_is_better else min(scored_nodes, key=lambda item: float(item["score"]))
        best_round = int(best["round"])
        for node in nodes:
            node["is_best"] = int(node["round"]) == best_round
    else:
        for node in nodes:
            node["is_best"] = False

    edges: list[dict[str, Any]] = []
    valid_rounds = {int(node["round"]) for node in nodes}
    for node in nodes:
        parent_round = _as_int(node.get("parent_round"))
        if parent_round is None or parent_round not in valid_rounds:
            continue
        edges.append({
            "source": f"r{parent_round}",
            "target": node["id"],
            "source_round": parent_round,
            "target_round": node["round"],
            "kind": node.get("parent_kind") or "parent",
            "parent_commit": node.get("parent_commit") or "",
        })

    branch_counts = Counter(str(node.get("branch") or "unknown") for node in nodes)
    status_counts = Counter(str(node.get("status") or "unknown") for node in nodes)
    stats = {
        "round_count": len(nodes),
        "edge_count": len(edges),
        "scored_count": len(scored_nodes),
        "best_round": best_round,
        "best_score": next((node.get("score") for node in nodes if node.get("is_best")), None),
        "branch_counts": dict(branch_counts),
        "status_counts": dict(status_counts),
        "total_sandbox_run_time": summary.get("total_sandbox_run_time"),
        "spent_wall_time": summary.get("spent_wall_time"),
        "budget_mode": summary.get("budget_mode"),
        "remaining_budget": (summary.get("budget_state") or {}).get("remaining_budget") if isinstance(summary.get("budget_state"), dict) else None,
        "stop_reason": summary.get("stop_reason"),
    }
    return {
        "schema_version": "search_graph_visualization_v1",
        "task": summary.get("rounds", [{}])[0].get("task_name") if isinstance(summary.get("rounds"), list) and summary.get("rounds") else task_dir.name,
        "task_dir": str(task_dir),
        "updated_at": datetime.now().isoformat(),
        "metric_direction": "higher" if higher_is_better else "lower",
        "source_files": {
            "rounds_summary": "rounds_summary.json",
            "graph_nodes": f"{V3_GRAPH_DIR}/nodes.jsonl",
            "graph_events": f"{V3_GRAPH_DIR}/events.jsonl",
            "memory_rounds": "memory_bank/rounds.jsonl",
            "card_index": "memory_bank/card_index.jsonl",
        },
        "stats": stats,
        "nodes": nodes,
        "edges": edges,
    }


def render_search_graph_png(state: dict[str, Any], path: Path) -> None:
    """Render the human-only search graph as task_dir/graphic.png."""
    from PIL import Image, ImageDraw, ImageFont

    nodes = state.get("nodes") if isinstance(state.get("nodes"), list) else []
    edges = state.get("edges") if isinstance(state.get("edges"), list) else []
    stats = state.get("stats") if isinstance(state.get("stats"), dict) else {}
    branches, lane_y, positions, width, height = _graph_layout(state)
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 12)
        small_font = ImageFont.truetype("DejaVuSans.ttf", 10)
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
        label_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 12)
    except Exception:
        font = ImageFont.load_default()
        small_font = font
        title_font = font
        label_font = font

    _draw_text(draw, (24, 20), f"Search Graph: {state.get('task')}", fill="#212529", font=title_font)
    _draw_text(
        draw,
        (24, 48),
        (
            f"updated={state.get('updated_at')} metric={state.get('metric_direction')} "
            f"rounds={stats.get('round_count', len(nodes))} scored={stats.get('scored_count', 0)} "
            f"best=R{stats.get('best_round') if stats.get('best_round') is not None else '-'} "
            f"score={_format_score(stats.get('best_score'))}"
        ),
        fill="#495057",
        font=font,
    )
    _draw_text(
        draw,
        (24, 68),
        (
            f"sandbox={_format_time(stats.get('total_sandbox_run_time'))} "
            f"wall={_format_time(stats.get('spent_wall_time'))} "
            f"remaining={_format_time(stats.get('remaining_budget'))} "
            f"stop={stats.get('stop_reason') or 'none'}"
        ),
        fill="#6c757d",
        font=small_font,
    )

    for branch in branches:
        y = lane_y[branch]
        draw.line((40, y + 60, width - 42, y + 60), fill=_hex_to_rgb("#e9ecef"), width=1)
        _draw_text(draw, (24, y + 10), branch, fill="#495057", font=label_font)

    edge_color = {"anchor": "#1971c2", "debug": "#e03131", "parent": "#495057"}
    for edge in edges:
        source_pos = positions.get(str(edge.get("source")))
        target_pos = positions.get(str(edge.get("target")))
        if not source_pos or not target_pos:
            continue
        sx, sy = source_pos
        tx, ty = target_pos
        color = edge_color.get(str(edge.get("kind")), "#495057")
        start = (sx + 158, sy + 48)
        end = (tx - 8, ty + 48)
        _draw_arrow(draw, start, end, fill=color, width=2)
        _draw_text(
            draw,
            (int((start[0] + end[0]) / 2) - 16, int((start[1] + end[1]) / 2) - 13),
            str(edge.get("kind") or "parent"),
            fill=color,
            font=small_font,
        )

    for node in nodes:
        x, y = positions[str(node.get("id"))]
        fill, stroke = _node_color(node)
        fill_rgb = _hex_to_rgb(fill)
        stroke_rgb = _hex_to_rgb(stroke)
        stroke_width = 4 if node.get("is_best") else 2
        draw.rounded_rectangle(
            (x, y, x + 160, y + 112),
            radius=8,
            fill=fill_rgb,
            outline=stroke_rgb,
            width=stroke_width,
        )
        if node.get("is_best"):
            draw.ellipse((x + 140, y + 8, x + 154, y + 22), fill=_hex_to_rgb("#f08c00"))
        commit = str(node.get("commit") or "no_commit")
        status = str(node.get("status") or "unknown")
        failure = str(node.get("failure_primary") or node.get("error_excerpt") or "")
        lines = [
            f"R{node.get('round')} {node.get('branch') or '-'}",
            f"{commit[:8]} {status[:18]}",
            f"score {_format_score(node.get('score'))}",
            f"run {_format_time(node.get('run_time'))}",
            f"wall {_format_time(node.get('wall_time'))}",
        ]
        if failure:
            lines.append(_shorten(failure, 23))
        for idx, line in enumerate(lines):
            _draw_text(
                draw,
                (x + 10, y + 12 + idx * 16),
                line,
                fill="#212529" if idx < 2 else "#343a40",
                font=label_font if idx == 0 else small_font,
            )

    tmp_path = path.with_name(f".{path.name}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(tmp_path, format="PNG")
    _atomic_replace_file(tmp_path, path)


def render_search_graph_artifacts(
    task_dir: Path,
    *,
    higher_is_better: bool | None = True,
    auto_refresh_seconds: int = 15,
) -> dict[str, Any]:
    _ = auto_refresh_seconds
    task_dir = Path(task_dir)
    state = build_search_graph_state(task_dir, higher_is_better=higher_is_better)
    graphic_path = task_dir / "graphic.png"
    render_search_graph_png(state, graphic_path)
    return {
        "schema_version": "search_graph_artifacts_v1",
        "status": "written",
        "updated_at": state.get("updated_at"),
        "node_count": len(state.get("nodes") or []),
        "edge_count": len(state.get("edges") or []),
        "graphic_path": _rel_path(task_dir, graphic_path),
    }


def search_graph_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render deterministic BSPM search graph monitor artifacts.")
    parser.add_argument("task_dir", type=Path, help="Task output directory containing rounds_summary.json and graph/")
    parser.add_argument("--lower-is-better", action="store_true", help="Treat lower validation scores as better")
    parser.add_argument("--watch", action="store_true", help="Keep refreshing artifacts")
    parser.add_argument("--interval", type=float, default=5.0, help="Watch refresh interval in seconds")
    args = parser.parse_args(argv)
    while True:
        result = render_search_graph_artifacts(
            args.task_dir,
            higher_is_better=not args.lower_is_better,
        )
        print(json.dumps(result, ensure_ascii=False))
        if not args.watch:
            return 0
        time.sleep(max(1.0, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(search_graph_main())
