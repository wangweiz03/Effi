from __future__ import annotations

from .common import *
from .constants import *

def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def graph_dir(task_dir: Path) -> Path:
    path = task_dir / V3_GRAPH_DIR
    path.mkdir(exist_ok=True)
    return path


def canonical_method_family(method_family: str | None, operator: SearchOperator | None = None) -> str:
    text = (method_family or "").strip().lower()
    inferred = ""
    if operator:
        infer_fn = globals().get("_operator_family")
        if callable(infer_fn):
            try:
                inferred = str(infer_fn(operator.name or operator.family or "", operator.description or "") or "").strip().lower()
            except Exception:
                inferred = ""
        if not text:
            text = inferred
    text = re.sub(r"[^a-z0-9_+\-]+", "_", text).strip("_").replace("-", "_")
    if "byt5" in text and ("textnorm" in text or "text_normalization" in text):
        text = "seq2seq_textnorm"
    elif ("seq2seq" in text or re.search(r"(^|_)t5($|_)", text)) and ("textnorm" in text or "text_normalization" in text):
        text = "seq2seq_textnorm"
    prefix_aliases = (
        ("byt5_residual_textnorm", "seq2seq_textnorm"),
        ("seq2seq_textnorm", "seq2seq_textnorm"),
        ("seq2seq_text", "seq2seq_text"),
        ("google_byt5", "seq2seq_textnorm"),
        ("byt5", "seq2seq_textnorm"),
        ("sparse_text", "sparse_text"),
        ("audio_spectrogram", "audio_spectrogram_cnn"),
        ("audio_waveform", "audio_waveform_cnn"),
        ("audio_segment_mil", "audio_segment_mil"),
        ("audio_segment", "audio_segment_tabular"),
        ("descriptor_svc", "descriptor_svc"),
        ("descriptor_tabular", "descriptor_svc"),
        ("tabular_gbdt", "tabular_gbdt"),
        ("tf_efficientnet", "cnn_image"),
        ("efficientnet", "cnn_image"),
        ("effnet", "cnn_image"),
        ("effv2", "cnn_image"),
        ("cnn_efficientnet", "cnn_image"),
        ("rule_router", "rule_router"),
    )
    for prefix, canonical_prefix in prefix_aliases:
        if text == prefix or text.startswith(f"{prefix}_"):
            text = canonical_prefix
            break
    aliases = {
        "rule_router_memory": "rule_router",
        "memory_rule_router": "rule_router",
        "hybrid_rule_router": "rule_router_hybrid",
        "lightgbm": "lgbm",
        "lightgbm_tabular": "lgbm_tabular",
        "xgboost": "xgb",
        "rankblend": "blend",
        "oof_blend": "blend",
        "min": "sparse_text",
        "c": "descriptor_svc",
        "pos": "imbalance_loss",
        "gbdt": "tabular_gbdt",
        "sparse": "sparse_text",
        "sparse_text_logreg": "sparse_text",
        "sparse_text_logreg_nbsvm": "sparse_text",
        "nbsvm": "sparse_text",
        "nb_svm": "sparse_text",
        "tfidf_logreg": "sparse_text",
        "text_tfidf_logreg": "sparse_text",
        "word_char_tfidf": "sparse_text",
        "google": "seq2seq_textnorm",
        "t5": "seq2seq_text",
        "byt5": "seq2seq_textnorm",
        "byt5_residual": "seq2seq_textnorm",
        "calibration": "calibration_postprocess",
        "oof": "stack_ensemble",
        "ensemble": "blend_ensemble",
        "blend": "blend_ensemble",
        "cnn": "cnn_image",
        "cnn_efficientnet": "cnn_image",
        "cnn_resnet": "cnn_image",
        "cnn_convnext": "cnn_image",
        "cnn_densenet": "cnn_image",
        "cnn_regnet": "cnn_image",
        "efficientnet": "cnn_image",
        "tf_efficientnet": "cnn_image",
        "tf_efficientnetv2_s": "cnn_image",
        "effnet": "cnn_image",
        "effv2": "cnn_image",
        "retina": "image_preprocessing",
        "retina_crop_norm": "image_preprocessing",
        "crop_norm": "image_preprocessing",
        "balanced_loss": "loss_reweighting",
        "ordinal_coral": "ordinal_head",
        "resnet": "cnn_image",
        "convnext": "cnn_image",
        "densenet": "cnn_image",
        "regnet": "cnn_image",
        "segment": "audio_segment_tabular",
        "sed": "audio_sed",
    }
    canonical = aliases.get(text, text or "unknown")
    # Preserve modality/representation-specific families when an operator's
    # description proves that a generic backbone alias is actually being used
    # for another modality, e.g. EfficientNet over whale spectrograms.
    inferred_canonical = aliases.get(
        re.sub(r"[^a-z0-9_+\-]+", "_", inferred).strip("_"),
        re.sub(r"[^a-z0-9_+\-]+", "_", inferred).strip("_") or "",
    )
    if (
        operator
        and (
            canonical in {"cnn_image", "cnn_embedding"}
            or text.startswith(("tf_efficientnet", "efficientnet", "effnet", "effv2", "cnn_"))
        )
        and inferred_canonical.startswith("audio_")
    ):
        return inferred_canonical
    if operator and canonical in {"google", "explore", "alternative", "skill_alternative", "seq2seq_text"} and inferred_canonical.startswith("seq2seq_"):
        return inferred_canonical
    return canonical


def is_structural_portfolio_family(method_family: str | None) -> bool:
    """Return whether a family is a real modeling/representation route for frontload diversity."""
    family = canonical_method_family(method_family)
    return (
        family not in V37_CONTROL_METHOD_FAMILIES
        and family not in V37_NONSTRUCTURAL_METHOD_FAMILIES
        and family != "unknown"
    )


def round_structural_family_components(row: dict[str, Any]) -> list[str]:
    """Return unique structural families materially covered by one scored round."""
    values: list[Any] = [
        row.get("method_family"),
        row.get("effective_method_family"),
    ]
    lineage = row.get("effective_lineage") if isinstance(row.get("effective_lineage"), dict) else {}
    values.append(lineage.get("effective_method_family"))
    components = row.get("method_family_components")
    if isinstance(components, list):
        values.extend(components)

    families: list[str] = []
    for item in values:
        family = canonical_method_family(str(item or ""))
        if is_structural_portfolio_family(family) and family not in families:
            families.append(family)
    return families


def extract_context_readiness_method_family(task_dir: Path | None) -> str:
    """Read the concrete code route declared by the coding agent's final pre-code plan."""
    if task_dir is None:
        return ""
    context_readiness = task_dir / "context_readiness.md"
    if not context_readiness.exists():
        return ""
    try:
        text = context_readiness.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    patterns = [
        r"(?im)concrete\s+(?:new\s+)?method\s+family(?:\s+for\s+this\s+round)?\s*[:：]\s*`([^`]+)`",
        r"(?im)concrete\s+(?:new\s+)?method\s+family(?:\s+for\s+this\s+round)?\s*[:：]\s*([^\n\r.;。；]+)",
        r"(?im)\bmethod_family\s*[:=]\s*`?([a-zA-Z0-9_+\-/ .]{2,80})`?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate = str(match.group(1) or "").strip().strip("`'\"* ")
        candidate = re.split(r"[\n\r,，;；.。)\]}]", candidate, maxsplit=1)[0].strip()
        raw_lower = candidate.lower()
        if (
            not candidate
            or "<" in candidate
            or ">" in candidate
            or any(token in raw_lower for token in (
                "stable concrete",
                "modeling family",
                "e.g",
                "never use",
                "control label",
                "draft/improve",
            ))
        ):
            continue
        family = canonical_method_family(candidate)
        if is_structural_portfolio_family(family):
            return family
    return ""


def resolve_round_method_family(
    search_operator: SearchOperator,
    round_summary: dict[str, Any] | None = None,
    task_dir: Path | None = None,
) -> str:
    """Prefer the concrete implementation family over scheduler/control families."""
    declared_family = extract_context_readiness_method_family(task_dir)
    if declared_family:
        return declared_family
    summary_family = canonical_method_family((round_summary or {}).get("method_family"), search_operator)
    if is_structural_portfolio_family(summary_family):
        return summary_family
    operator_family = canonical_method_family(search_operator.family, search_operator)
    if operator_family != "unknown":
        return operator_family
    return summary_family


def normalize_round_summary_method_family(
    round_summary: dict[str, Any],
    search_operator: SearchOperator,
    task_dir: Path | None,
) -> dict[str, Any]:
    """Ensure search statistics see the actual modeling family, not only the control action."""
    normalized = dict(round_summary or {})
    method_family = resolve_round_method_family(search_operator, normalized, task_dir)
    if method_family:
        normalized["method_family"] = method_family
    components = normalized.get("core_components")
    if not isinstance(components, list):
        components = [str(components)] if components else []
    if method_family and method_family not in [str(item) for item in components]:
        components = [method_family, *components]
    normalized["core_components"] = components[:8]
    return normalized


def load_graph_nodes(task_dir: Path) -> list[dict[str, Any]]:
    return _load_jsonl(graph_dir(task_dir) / "nodes.jsonl")


def score_sort_key(score: float | None, higher_is_better: bool) -> float:
    if score is None:
        return float("-inf")
    return float(score) if higher_is_better else -float(score)


def validation_score(row: dict[str, Any]) -> float | None:
    validation = row.get("validation") if isinstance(row.get("validation"), dict) else {}
    value = validation.get("score")
    if value is None:
        value = row.get("score")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_submission_eligible_round(row: dict[str, Any]) -> bool:
    contract = row.get("solution_contract", {}) or {}
    if contract and not contract.get("submission_eligible", True):
        return False
    quality = (row.get("validation", {}) or {}).get("quality", {}) or {}
    if quality and not bool(quality.get("submit_eligible", True)):
        return False
    return validation_score(row) is not None and bool(row.get("code"))


def round_sort_key(row: dict[str, Any], higher_is_better: bool) -> tuple[float, int]:
    score = validation_score(row)
    round_num = int(row.get("round") or 0)
    # Earlier equal-score candidates are easier to audit and less likely to include late fragile churn.
    return score_sort_key(score, higher_is_better), -round_num


def candidate_better(
    candidate_score: float | None,
    incumbent_score: float | None,
    higher_is_better: bool,
) -> bool:
    if candidate_score is None:
        return False
    if incumbent_score is None:
        return True
    return score_better(float(candidate_score), float(incumbent_score), higher_is_better)


def best_vault_path(task_dir: Path) -> Path:
    return task_dir / "index" / "best_validation_candidate.json"


def update_best_validation_vault(task_dir: Path, result: dict[str, Any], higher_is_better: bool) -> None:
    """Persist the raw validation-best eligible candidate independently of HEAD/portfolio state."""
    if not is_submission_eligible_round(result):
        return
    path = best_vault_path(task_dir)
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        current = {}
    new_score = validation_score(result)
    old_score = current.get("validation_score")
    if not candidate_better(new_score, old_score, higher_is_better):
        return
    commit_hash = result.get("commit_hash")
    payload = {
        "selection_policy": SUBMIT_SELECTION_POLICY,
        "task_name": result.get("task_name"),
        "round": result.get("round"),
        "commit_hash": commit_hash,
        "validation_score": new_score,
        "validation_status": result.get("validation", {}).get("status"),
        "branch": result.get("branch"),
        "effective_branch": result.get("effective_branch") or result.get("branch"),
        "operator": result.get("effective_operator") or result.get("search_operator"),
        "execution_operator": result.get("search_operator"),
        "method_family": result.get("effective_method_family"),
        "effective_lineage": result.get("effective_lineage") or {},
        "code_path": f"commits/{commit_hash}/solution.py" if commit_hash else None,
        "code_fingerprint": result.get("code_fingerprint"),
        "run_time": result.get("validation", {}).get("run_time"),
        "wall_time": result.get("round_wall_time"),
        "updated_at": datetime.now().isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def compact_operator_ref(operator: dict[str, Any] | None) -> dict[str, Any]:
    """Keep portfolio state small and non-recursive."""
    op = operator if isinstance(operator, dict) else {}
    return {
        "name": op.get("name"),
        "intent": op.get("intent"),
        "family": op.get("family"),
        "source": op.get("source"),
        "risk": op.get("risk"),
        "cost": op.get("cost"),
    }


def compact_parent_ref(parent: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep lineage links useful without recursively embedding older parents."""
    if not isinstance(parent, dict) or not parent:
        return None
    return {
        "role": parent.get("role"),
        "round": parent.get("round"),
        "commit": parent.get("commit"),
        "score": parent.get("score"),
        "branch": parent.get("branch"),
        "effective_branch": parent.get("effective_branch") or parent.get("branch"),
        "method_family": parent.get("method_family"),
        "run_time": parent.get("run_time"),
        "wall_time": parent.get("wall_time"),
        "card_path": parent.get("card_path") or parent.get("memory_card_path"),
        "diff_path": parent.get("diff_path") or parent.get("memory_diff_path"),
        "code_path": parent.get("code_path"),
        "feedback_path": parent.get("feedback_path"),
        "status": parent.get("status"),
    }


def compact_candidate_ref(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact candidate reference safe to embed in prompts and future slots."""
    if not isinstance(candidate, dict):
        return None
    op = candidate.get("operator") if isinstance(candidate.get("operator"), dict) else {}
    parent = candidate.get("parent_binding")
    if not isinstance(parent, dict):
        parent = candidate.get("debug_parent") or candidate.get("anchor_parent")
    return {
        "commit": candidate.get("commit"),
        "round": candidate.get("round"),
        "score": candidate.get("score"),
        "branch": candidate.get("branch"),
        "effective_branch": candidate.get("effective_branch") or candidate.get("branch"),
        "operator": compact_operator_ref(op),
        "execution_operator": compact_operator_ref(candidate.get("execution_operator")),
        "seed_id": (candidate.get("effective_lineage") or {}).get("seed_id"),
        "method_family": candidate.get("method_family") or op.get("family"),
        "method_family_components": candidate.get("method_family_components") or [],
        "portfolio_action": candidate.get("portfolio_action"),
        "run_time": candidate.get("run_time"),
        "wall_time": candidate.get("wall_time"),
        "commit_paths": candidate.get("commit_paths") or {},
        "memory_card_path": candidate.get("memory_card_path"),
        "memory_diff_path": candidate.get("memory_diff_path"),
        "parent_binding": compact_parent_ref(parent),
        "submit_eligible": bool(candidate.get("submit_eligible", True)),
    }


def compact_portfolio_slot(slot: dict[str, Any] | None) -> dict[str, Any]:
    """Store only current slot metadata; never nest historical portfolio snapshots."""
    slot = slot if isinstance(slot, dict) else {}
    return {
        "target": slot.get("target"),
        "best_candidate": compact_candidate_ref(slot.get("best_candidate")),
        "candidate_count": slot.get("candidate_count", 0),
        "family_counts": slot.get("family_counts") or {},
        "successful_draft_origin_seed_count": slot.get("successful_draft_origin_seed_count", 0),
        "successful_draft_origin_seed_total": slot.get("successful_draft_origin_seed_total", 0),
        "required_draft_origin_seeds": slot.get("required_draft_origin_seeds"),
        "successful_draft_origin_seed_families": slot.get("successful_draft_origin_seed_families") or [],
        "diversity_gap": bool(slot.get("diversity_gap")),
        "weak_start": bool(slot.get("weak_start")),
    }


def update_portfolio(task_dir: Path, node: dict[str, Any], higher_is_better: bool) -> None:
    portfolio_file = graph_dir(task_dir) / "portfolio.json"
    try:
        portfolio = json.loads(portfolio_file.read_text(encoding="utf-8")) if portfolio_file.exists() else {"candidates": []}
    except Exception:
        portfolio = {"candidates": []}
    candidates = [
        compact
        for compact in (compact_candidate_ref(c) for c in portfolio.get("candidates", []))
        if compact is not None
    ]
    validation_quality = (node.get("validation", {}) or {}).get("quality") or {}
    if (
        node.get("validation", {}).get("score") is not None
        and node.get("static_gate", {}).get("submission_eligible", True)
        and bool(validation_quality.get("submit_eligible", True))
    ):
        candidates = [c for c in candidates if c.get("commit") != node.get("commit")]
        candidates.append({
            "commit": node.get("commit"),
            "round": node.get("round"),
            "score": node.get("validation", {}).get("score"),
            "branch": node.get("branch"),
            "effective_branch": node.get("effective_branch") or node.get("branch"),
            "operator": node.get("operator"),
            "execution_operator": node.get("execution_operator"),
            "effective_lineage": node.get("effective_lineage") or {},
            "method_family": node.get("method", {}).get("family_canonical"),
            "method_family_components": node.get("method", {}).get("family_components") or [],
            "run_time": node.get("validation", {}).get("run_time"),
            "wall_time": node.get("wall_time"),
            "risk": node.get("operator", {}).get("risk"),
            "selection_notes": node.get("selection_notes", []),
            "portfolio_action": (node.get("decision") or {}).get("portfolio_action"),
            "portfolio_slot": compact_portfolio_slot((node.get("decision") or {}).get("portfolio_slot")),
            "commit_paths": (node.get("commit_paths") or {}),
            "memory_card_path": node.get("memory_card_path"),
            "memory_diff_path": node.get("memory_diff_path"),
            "parent_binding": compact_parent_ref(node.get("parent_binding")),
            "submit_eligible": bool(node.get("static_gate", {}).get("submission_eligible", True)),
        })
    candidates.sort(key=lambda c: score_sort_key(c.get("score"), higher_is_better), reverse=True)
    portfolio["candidates"] = candidates[:V3_TOP_K_PORTFOLIO]
    portfolio["updated_at"] = datetime.now().isoformat()
    portfolio_file.write_text(json.dumps(portfolio, indent=2, ensure_ascii=False), encoding="utf-8")


def load_portfolio_snapshot(task_dir: Path, all_rounds: list[dict[str, Any]], higher_is_better: bool) -> dict[str, Any]:
    """Summarize the search frontier before selecting the next v4 action."""
    portfolio_file = graph_dir(task_dir) / "portfolio.json"
    try:
        portfolio = json.loads(portfolio_file.read_text(encoding="utf-8")) if portfolio_file.exists() else {"candidates": []}
    except Exception:
        portfolio = {"candidates": []}
    raw_candidates = [row for row in portfolio.get("candidates", []) if isinstance(row, dict)]
    candidates = [
        row for row in raw_candidates
        if row.get("score") is not None and bool(row.get("submit_eligible", True))
    ]
    candidates.sort(key=lambda row: score_sort_key(row.get("score"), higher_is_better), reverse=True)
    family_counts: Counter[str] = Counter()
    covered_family_counts: Counter[str] = Counter()
    operator_counts: Counter[str] = Counter()
    for row in candidates:
        op_payload = row.get("operator") if isinstance(row.get("operator"), dict) else {}
        op = search_operator_from_dict(op_payload) if op_payload else None
        family = canonical_method_family(
            str(row.get("method_family") or (op_payload.get("family") if op_payload else "") or "unknown"),
            op,
        )
        family_counts[family] += 1
        operator_counts[str(op_payload.get("name") or "unknown")] += 1

    for row in all_rounds:
        if validation_score(row) is None:
            continue
        for covered in round_structural_family_components(row):
            covered_family_counts[covered] += 1

    scored_rounds = [row for row in all_rounds if validation_score(row) is not None]
    first_score = validation_score(scored_rounds[0]) if scored_rounds else None
    best_score = float(candidates[0]["score"]) if candidates else None
    first_score_tol = max(
        V4_MATERIAL_SCORE_ABS_DELTA,
        abs(float(best_score or 0.0)) * V4_MATERIAL_SCORE_REL_DELTA,
    )
    first_score_still_best = (
        first_score is not None
        and best_score is not None
        and abs(first_score - best_score) <= first_score_tol
    )
    weak_start = len(scored_rounds) >= V36_WEAK_START_SUCCESS_LIMIT and first_score_still_best
    top_family = family_counts.most_common(1)[0][0] if family_counts else None
    structural_family_counts = Counter({
        family: count
        for family, count in family_counts.items()
        if is_structural_portfolio_family(family)
    })
    real_family_count = len(structural_family_counts)
    diversity_gap = (
        len(candidates) >= 2
        and real_family_count < min(V37_MIN_DIVERSE_PORTFOLIO_FAMILIES, len(candidates))
    )
    compact_candidates = [row for row in (compact_candidate_ref(candidate) for candidate in candidates) if row]
    all_seed_rows = successful_draft_origin_seed_rows(all_rounds)
    seed_rows = successful_draft_origin_diverse_seed_rows(all_rounds)
    compact_seeds = []
    for row in seed_rows:
        op = round_effective_operator_payload(row)
        compact_seeds.append({
            "seed_id": round_seed_id(row),
            "round": _round_value(row),
            "commit": _round_commit(row),
            "score": validation_score(row),
            "family": round_effective_method_family(row),
            "operator": compact_operator_ref(op),
            "origin_round": round_effective_lineage(row).get("origin_round"),
            "origin_commit": round_effective_lineage(row).get("origin_commit"),
            "debug_repaired": bool(round_effective_lineage(row).get("is_debug_repair")),
        })
    snapshot = {
        "candidate_count": len(candidates),
        "top_candidates": compact_candidates[:V3_TOP_K_PORTFOLIO],
        "best_candidate": compact_candidates[0] if compact_candidates else None,
        "best_score": best_score,
        "family_counts": dict(family_counts),
        "covered_family_counts": dict(covered_family_counts),
        "structural_family_counts": dict(structural_family_counts),
        "structural_family_count": real_family_count,
        "operator_counts": dict(operator_counts),
        "top_family": top_family,
        "diversity_gap": diversity_gap,
        "weak_start": weak_start,
        "scored_round_count": len(scored_rounds),
        "required_draft_origin_seeds": V38_REQUIRED_DRAFT_ORIGIN_SEEDS,
        "successful_draft_origin_seed_total": len(all_seed_rows),
        "successful_draft_origin_seed_count": len(seed_rows),
        "successful_draft_origin_seed_families": successful_draft_origin_seed_families(all_rounds),
        "successful_draft_origin_seeds": compact_seeds[:V38_REQUIRED_DRAFT_ORIGIN_SEEDS],
        "portfolio_file": str(portfolio_file),
        "updated_at": portfolio.get("updated_at"),
    }
    return snapshot


def compact_portfolio_card(portfolio_state: dict[str, Any] | None, limit: int = 2600) -> str:
    """Prompt-safe frontier card for v4 portfolio-first decisions."""
    state = portfolio_state or {}
    rows = []
    for row in state.get("top_candidates") or []:
        op = row.get("operator") if isinstance(row.get("operator"), dict) else {}
        rows.append({
            "round": row.get("round"),
            "commit": row.get("commit"),
            "score": row.get("score"),
            "family": row.get("method_family") or op.get("family"),
            "operator": op.get("name"),
            "action": row.get("portfolio_action"),
            "run_time": row.get("run_time"),
            "commit_paths": row.get("commit_paths"),
        })
    card = "\n".join([
        "[PINNED PORTFOLIO STATE]",
        "v4 treats the portfolio as the search frontier. Improve the frontier, not just the latest file.",
        f"candidate_count: {state.get('candidate_count', 0)}",
        f"best_score: {state.get('best_score')}",
        f"family_counts: {json.dumps(state.get('family_counts') or {}, ensure_ascii=False)}",
        f"covered_family_counts: {json.dumps(state.get('covered_family_counts') or {}, ensure_ascii=False)}",
        f"diversity_gap: {state.get('diversity_gap')}",
        f"weak_start: {state.get('weak_start')}",
        f"successful_draft_origin_seed_count: {state.get('successful_draft_origin_seed_count', 0)}/{state.get('required_draft_origin_seeds', V38_REQUIRED_DRAFT_ORIGIN_SEEDS)} distinct structural families",
        f"successful_draft_origin_seed_total: {state.get('successful_draft_origin_seed_total', 0)}",
        f"successful_draft_origin_seed_families: {json.dumps(state.get('successful_draft_origin_seed_families') or [], ensure_ascii=False)}",
        "successful_draft_origin_seeds:",
        json.dumps(state.get("successful_draft_origin_seeds") or [], ensure_ascii=False, indent=2),
        "top_candidates:",
        json.dumps(rows, ensure_ascii=False, indent=2),
    ])
    return shrink_text_middle(card, limit)


def record_graph_node(task_dir: Path, result: dict[str, Any], higher_is_better: bool) -> dict[str, Any]:
    execution_operator_payload = result.get("search_operator") or {}
    operator_payload = result.get("effective_operator") or execution_operator_payload
    operator = search_operator_from_dict(operator_payload) if isinstance(operator_payload, dict) else None
    effective_lineage = result.get("effective_lineage") if isinstance(result.get("effective_lineage"), dict) else {}
    round_summary = result.get("round_summary", {}) or {}
    validation = result.get("validation", {}) or {}
    method_family = canonical_method_family(
        result.get("effective_method_family") or round_summary.get("method_family"),
        operator,
    )
    code_features = result.get("code_features") if isinstance(result.get("code_features"), dict) else {}
    summary_components = round_summary.get("core_components") if isinstance(round_summary.get("core_components"), list) else []
    family_components: list[str] = []
    for item in [method_family, *summary_components]:
        family = canonical_method_family(str(item or ""), operator)
        if is_structural_portfolio_family(family) and family not in family_components:
            family_components.append(family)
    branch_decision = result.get("branch_decision") if isinstance(result.get("branch_decision"), dict) else {}
    parent_binding = branch_decision.get("parent_binding") if isinstance(branch_decision.get("parent_binding"), dict) else {}
    if not parent_binding:
        parent_binding = branch_decision.get("debug_parent") or branch_decision.get("anchor_parent") or {}
    node = {
        "node_id": result.get("commit_hash") or f"round_{result.get('round')}",
        "task_name": result.get("task_name"),
        "round": result.get("round"),
        "commit": result.get("commit_hash"),
        "branch": result.get("branch"),
        "effective_branch": result.get("effective_branch") or result.get("branch"),
        "parent_commit": parent_binding.get("commit"),
        "parent_binding": compact_parent_ref(parent_binding),
        "memory_card_path": result.get("memory_card_path"),
        "memory_diff_path": result.get("memory_diff_path"),
        "operator": operator_payload,
        "execution_operator": execution_operator_payload,
        "effective_lineage": effective_lineage,
        "decision": {
            "reason": branch_decision.get("reason"),
            "portfolio_action": branch_decision.get("portfolio_action"),
            "portfolio_slot": branch_decision.get("portfolio_slot"),
        },
        "method": {
            "family": round_summary.get("method_family", ""),
            "family_canonical": method_family,
            "components": round_summary.get("core_components", []),
            "family_components": family_components,
            "summary": round_summary.get("method_summary", ""),
            "novelty_vs_best": round_summary.get("novelty_vs_best", ""),
        },
        "code_features": code_features,
        "validation": {
            "status": validation.get("status"),
            "score": validation.get("score"),
            "reward": validation.get("reward"),
            "run_time": validation.get("run_time"),
            "queue_time": validation.get("queue_time"),
            "failure_primary": (validation.get("failure_taxonomy") or {}).get("primary"),
            "quality": validation.get("quality") or {},
        },
        "static_gate": result.get("solution_contract", {}),
        "wall_time": result.get("round_wall_time"),
        "usage": {
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
        },
        "commit_paths": {
            "commit_dir": f"commits/{result.get('commit_hash')}" if result.get("commit_hash") else None,
            "solution_path": f"commits/{result.get('commit_hash')}/solution.py" if result.get("commit_hash") else None,
            "trace_path": f"traces/round_{result.get('round')}_trace.json",
            "code_fingerprint": result.get("code_fingerprint"),
        },
        "selection_notes": [],
        "timestamp": datetime.now().isoformat(),
    }
    _append_jsonl(graph_dir(task_dir) / "nodes.jsonl", node)
    update_portfolio(task_dir, node, higher_is_better)
    return node


def update_commit_log(
    task_dir: Path,
    commit_hash: str,
    branch: str,
    message: str,
    score: float | None,
    wall_time: float,
    status: str,
    round_summary: dict[str, str] | None = None,
    search_operator: SearchOperator | None = None,
) -> None:
    """Append one record to the lightweight commit log."""
    log_entry = {
        "hash": commit_hash,
        "branch": branch,
        "msg": message[:80],
        "score": score,
        "time": round(wall_time, 1),
        "status": status,
        "timestamp": datetime.now().isoformat(),
    }
    if round_summary:
        log_entry["method_summary"] = round_summary.get("method_summary", "")
        log_entry["result_reflection"] = round_summary.get("result_reflection", "")
        log_entry["method_family"] = round_summary.get("method_family", "")
        log_entry["method_family_canonical"] = canonical_method_family(round_summary.get("method_family"), search_operator)
        log_entry["core_components"] = round_summary.get("core_components", [])
        log_entry["novelty_vs_best"] = round_summary.get("novelty_vs_best", "")
    if search_operator:
        log_entry["search_operator"] = search_operator_to_dict(search_operator)

    log_file = task_dir / "index" / "commit_log.jsonl"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def update_branch_ref(
    task_dir: Path,
    branch: str,
    commit_hash: str,
    score: float | None,
    status: str,
    wall_time: float,
    round_num: int,
    higher_is_better: bool,
) -> None:
    """Update branch pointer and branch summary with simple branch statistics."""
    branch = normalize_branch_name(branch)
    (task_dir / "refs" / "heads" / branch).write_text(commit_hash, encoding="utf-8")

    summary_file = task_dir / "index" / "branch_summary.json"
    summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.exists() else {}
    spec = BRANCH_SPEC_BY_NAME.get(branch)
    current = summary.get(branch, {})
    best_score = current.get("best_score")
    if score is not None:
        if best_score is None:
            best_score = score
        elif score_better(float(score), float(best_score), higher_is_better):
            best_score = score

    attempts = int(current.get("attempts", 0)) + 1
    successes = int(current.get("successes", 0)) + (1 if score is not None else 0)
    failures = int(current.get("failures", 0)) + (0 if score is not None else 1)
    total_time = float(current.get("total_time", 0.0)) + float(wall_time or 0.0)
    summary[branch] = {
        "title": current.get("title") or (spec.title if spec else branch),
        "goal": current.get("goal") or (spec.goal if spec else ""),
        "head": commit_hash,
        "score": score,
        "best_score": best_score,
        "attempts": attempts,
        "successes": successes,
        "failures": failures,
        "success_rate": successes / attempts if attempts else 0.0,
        "total_time": round(total_time, 2),
        "last_status": status,
        "last_round": round_num,
        "updated_at": datetime.now().isoformat(),
    }
    summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def record_branch_attempt_without_commit(
    task_dir: Path,
    branch: str,
    status: str,
    wall_time: float,
    round_num: int,
) -> None:
    """Record a branch attempt that did not produce an archived commit."""
    branch = normalize_branch_name(branch)
    summary_file = task_dir / "index" / "branch_summary.json"
    summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.exists() else {}
    spec = BRANCH_SPEC_BY_NAME.get(branch)
    current = summary.get(branch, {})
    attempts = int(current.get("attempts", 0)) + 1
    successes = int(current.get("successes", 0))
    failures = int(current.get("failures", 0)) + 1
    total_time = float(current.get("total_time", 0.0)) + float(wall_time or 0.0)
    summary[branch] = {
        "title": current.get("title") or (spec.title if spec else branch),
        "goal": current.get("goal") or (spec.goal if spec else ""),
        "head": current.get("head", ""),
        "score": current.get("score"),
        "best_score": current.get("best_score"),
        "attempts": attempts,
        "successes": successes,
        "failures": failures,
        "success_rate": successes / attempts if attempts else 0.0,
        "total_time": round(total_time, 2),
        "last_status": status,
        "last_round": round_num,
        "updated_at": datetime.now().isoformat(),
    }
    summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def get_current_branch(task_dir: Path) -> str:
    """Get current branch name."""
    head_file = task_dir / "HEAD"
    if head_file.exists():
        branch = head_file.read_text(encoding="utf-8").strip()
        if branch:
            return normalize_branch_name(branch)
    return "main"


def set_current_branch(task_dir: Path, branch: str) -> None:
    """Set current branch name."""
    (task_dir / "HEAD").write_text(normalize_branch_name(branch), encoding="utf-8")


def create_tag(
    task_dir: Path,
    tag_name: str,
    commit_hash: str,
    reason: str,
    score: float | None,
    branch: str,
) -> None:
    """Create a tag pointing to a commit."""
    branch = normalize_branch_name(branch)
    (task_dir / "refs" / "tags" / tag_name).write_text(commit_hash, encoding="utf-8")

    registry_file = task_dir / "index" / "tag_registry.json"
    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    registry[tag_name] = {
        "commit": commit_hash,
        "score": score,
        "branch": branch,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }
    registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def get_commit_log_summary(task_dir: Path, limit: int = 10) -> str:
    """Build a compact commit log summary for the model."""
    log_file = task_dir / "index" / "commit_log.jsonl"
    if not log_file.exists():
        return "No commits yet."

    lines = [line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return "No commits yet."

    recent = lines[-limit:] if len(lines) > limit else lines
    summary_parts = ["Recent commits:"]
    for line in reversed(recent):
        entry = json.loads(line)
        status_icon = "OK" if entry["status"] == "success" else "FAIL"
        score_str = f"{entry['score']:.4f}" if entry["score"] is not None else "N/A"
        summary_parts.append(
            f"{entry['hash']}  {entry['branch']:16s}  {entry['msg'][:36]:36s}  {score_str:8s}  {entry['time']:6.1f}s  {status_icon}"
        )
        method_summary = entry.get("method_summary")
        result_reflection = entry.get("result_reflection")
        if method_summary:
            summary_parts.append(f"  method: {method_summary}")
        method_family = entry.get("method_family")
        core_components = entry.get("core_components")
        novelty_vs_best = entry.get("novelty_vs_best")
        if method_family:
            summary_parts.append(f"  family: {method_family} components={core_components or []}")
        if novelty_vs_best:
            summary_parts.append(f"  novelty: {novelty_vs_best}")
        if result_reflection:
            summary_parts.append(f"  reflection: {result_reflection}")

    return "\n".join(summary_parts)


def get_tag_summary(task_dir: Path) -> str:
    """Build a compact tag summary for the model."""
    registry_file = task_dir / "index" / "tag_registry.json"
    if not registry_file.exists():
        return "No tags yet."

    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    if not registry:
        return "No tags yet."

    summary_parts = ["Tags:"]
    for tag_name, info in registry.items():
        score_str = f"{info['score']:.4f}" if info["score"] is not None else "N/A"
        summary_parts.append(
            f"- {tag_name:16s} -> {info['commit']}  branch={info.get('branch', 'main')}  ({score_str})  {info['reason']}"
        )

    return "\n".join(summary_parts)


def get_latest_failure_context(task_dir: Path, limit: int = 8000) -> str:
    """Return compact details for the latest failed validation attempt."""
    summary_file = task_dir / "rounds_summary.json"
    if not summary_file.exists():
        return "No validation failure context yet."
    try:
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
    except Exception:
        return "No readable validation failure context yet."
    rounds = summary.get("rounds", [])
    for round_result in reversed(rounds):
        validation = round_result.get("validation") or {}
        if validation.get("score") is not None:
            continue
        taxonomy = validation.get("failure_taxonomy") or {}
        feedback = validation.get("feedback") or validation.get("clear_run_log") or validation.get("feedback_excerpt") or ""
        payload = [
            "[LATEST FAILED VALIDATION]",
            f"round: {round_result.get('round')}",
            f"branch: {round_result.get('branch')}",
            f"status: {validation.get('status')}",
            f"taxonomy: {json.dumps(taxonomy, ensure_ascii=False)}",
            "",
            _truncate_text(str(feedback), limit),
        ]
        return "\n".join(payload)
    return "No failed validation attempts recorded."


def load_branch_summary(task_dir: Path) -> dict[str, Any]:
    """Load branch scoreboard."""
    summary_file = task_dir / "index" / "branch_summary.json"
    if not summary_file.exists():
        return {}
    return json.loads(summary_file.read_text(encoding="utf-8"))


def score_better(score: float | None, baseline: float | None, higher_is_better: bool) -> bool:
    """Return whether score is materially better than baseline."""
    if score is None:
        return False
    if baseline is None:
        return True
    delta = max(V4_MATERIAL_SCORE_ABS_DELTA, abs(float(baseline)) * V4_MATERIAL_SCORE_REL_DELTA)
    return score > baseline + delta if higher_is_better else score < baseline - delta


def get_branch_scoreboard(task_dir: Path, higher_is_better: bool) -> str:
    """Build a concise branch scoreboard for prompts."""
    summary = load_branch_summary(task_dir)
    if not summary:
        return "No branch scoreboard yet."

    rows = []
    for spec in BRANCH_SPECS:
        info = summary.get(spec.name, {})
        best_score = info.get("best_score")
        best_text = f"{best_score:.4f}" if isinstance(best_score, (float, int)) else "N/A"
        rows.append(
            (
                spec.name,
                best_score,
                f"- {spec.name:10s} attempts={int(info.get('attempts', 0)):2d} "
                f"success={int(info.get('successes', 0)):2d} fail={int(info.get('failures', 0)):2d} "
                f"best={best_text:8s} last={info.get('last_status') or 'none'} "
                f"head={info.get('head') or '-'}"
            )
        )

    def sort_key(row: tuple[str, Any, str]) -> tuple[int, float]:
        score = row[1]
        if not isinstance(score, (float, int)):
            return (0, 0.0)
        return (1, float(score) if higher_is_better else -float(score))

    sorted_rows = sorted(rows, key=sort_key, reverse=True)
    return "Branch scoreboard:\n" + "\n".join(row[2] for row in sorted_rows)


def get_best_branch(summary: dict[str, Any], higher_is_better: bool) -> str | None:
    """Find branch with best validation score."""
    best_name = None
    best_score = None
    for branch, info in summary.items():
        branch = normalize_branch_name(branch)
        if branch not in BRANCH_SPEC_BY_NAME:
            continue
        score = info.get("best_score")
        if not isinstance(score, (float, int)):
            continue
        if best_name is None or score_better(float(score), best_score, higher_is_better):
            best_name = branch
            best_score = float(score)
    return best_name
