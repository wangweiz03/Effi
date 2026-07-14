from __future__ import annotations

from .common import *
from .constants import *

def prefill_active_solution_from_incumbent(
    task_dir: Path,
    solution_file: Path,
    branch_decision: dict[str, Any],
) -> dict[str, Any]:
    """Materialize exactly the parent selected by the branch decision."""
    branch = normalize_branch_name(str(branch_decision.get("branch") or ""))
    schema_version = str(branch_decision.get("schema_version") or "")
    info: dict[str, Any] = {
        "enabled": False,
        "branch": branch,
        "parent_role": "none",
        "source_path": "",
        "source_exists": False,
        "reason": "",
    }
    if branch == "draft":
        info["reason"] = "draft_branch_has_no_parent"
        return info

    binding = branch_decision.get("parent_binding")
    if not isinstance(binding, dict):
        if schema_version == "branch_decision_v3":
            info["reason"] = "v3_parent_binding_missing"
            return info
        branch_decision = apply_latest_failed_parent_fallback(task_dir, branch_decision)
        legacy_parent = (
            branch_decision.get("debug_parent_fallback") or branch_decision.get("debug_parent")
            if branch == "debug"
            else branch_decision.get("anchor_parent")
        )
        binding = dict(legacy_parent) if isinstance(legacy_parent, dict) else {}
        binding["role"] = "debug_parent" if branch == "debug" else "validation_best"
        binding["code_path"] = binding.get("code_path") or branch_decision.get("parent_code_path")
        binding["commit"] = binding.get("commit") or branch_decision.get("parent_commit")
        if not binding.get("code_path") and not binding.get("commit") and branch == "improve":
            incumbent = safe_load_json_file(task_dir / "index" / "best_validation_candidate.json")
            binding["code_path"] = incumbent.get("code_path")
            binding["commit"] = incumbent.get("commit_hash") or incumbent.get("commit")

    role = str(binding.get("role") or "none")
    info["parent_role"] = role
    expected_role = "debug_parent" if branch == "debug" else "validation_best"
    if role != expected_role:
        info["reason"] = f"parent_role_mismatch:{role or 'none'}:{expected_role}"
        return info

    raw_code_path = str(binding.get("code_path") or "").strip()
    commit = str(binding.get("commit") or "").strip()
    if raw_code_path:
        candidate = Path(raw_code_path)
        candidate = candidate if candidate.is_absolute() else task_dir / candidate
    elif commit:
        candidate = task_dir / "commits" / commit / "solution.py"
    else:
        info["reason"] = "parent_binding_has_no_code_identity"
        return info

    info["source_path"] = str(candidate)
    info["source_exists"] = candidate.exists()
    if not candidate.exists():
        info["reason"] = "parent_binding_solution_file_not_found"
        return info

    solution_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, solution_file)
    info["enabled"] = True
    info["reason"] = f"prefilled_active_solution_from_{role}"
    return info


def normalize_branch_sequence(branches: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Normalize and de-duplicate branch names while preserving order."""
    seen: set[str] = set()
    normalized: list[str] = []
    for branch in branches:
        clean = normalize_branch_name(branch)
        if clean in seen:
            continue
        seen.add(clean)
        normalized.append(clean)
    return tuple(normalized)


@dataclass(frozen=True)
class EvalContext:
    phase: str
    data_dir: str


@dataclass(frozen=True)
class SkillRoute:
    branch: str
    reason: str
    sources: list[str]
    content: str


def resolve_submit_data_dir(val_data_dir: str) -> str:
    """Resolve submit data directory from validation data directory."""
    data_path = Path(val_data_dir)
    task_name = data_path.name
    return str(SUBMIT_DATA_ROOT / task_name)


def resolve_local_eda_data_dir(task_name: str, local_eda_data_root: Path) -> Path:
    """Resolve the read-only public validation data directory used for local pre-plan EDA."""
    task_root = local_eda_data_root / task_name
    public_dir = task_root / "data" / "public"
    if public_dir.is_dir():
        return public_dir
    data_dir = task_root / "data"
    if data_dir.is_dir():
        return data_dir
    return task_root


def build_metadata_prompt(metadata: dict[str, Any]) -> str:
    """Format parquet metadata into the prompt."""
    lines = [
        "[METADATA]",
        f"Task: {metadata.get('task_name', 'unknown')}",
        f"Resource Type: {metadata.get('cpu_gpu', 'unknown')}",
        f"Data Directory: {metadata.get('data_dir', 'unknown')}",
        (
            "Evaluation Metric Range: "
            f"[{metadata.get('theoretical_min', 'unknown')}, {metadata.get('theoretical_max', 'unknown')}]"
        ),
        f"Higher is Better: {metadata.get('higher_is_better', 'unknown')}",
    ]

    data_description = metadata.get("data_description")
    if data_description:
        lines.extend(["", "[DATA DESCRIPTION]", str(data_description)])

    task_description = metadata.get("task_description")
    if task_description:
        lines.extend(["", "[TASK DESCRIPTION]", str(task_description)])

    return "\n".join(lines)


def _fence_lang(path: Path) -> str:
    return {
        ".md": "markdown",
        ".py": "python",
        ".json": "json",
        ".txt": "text",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(path.suffix.lower(), "text")


def _safe_read_text(path: Path, limit: int | None = None) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None
    return _truncate_text(text, limit) if limit else text


def load_task_skill(task_name: str, skills_dir: Path) -> tuple[str | None, str | None]:
    skill_file = skills_dir / f"SKILL_{task_name}.md"
    content = _safe_read_text(skill_file)
    if content is None:
        logger.warning("Task skill not found: %s", skill_file)
        return None, None
    return str(skill_file), content


def _iter_skill_package_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKILL_SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SKILL_FILE_SUFFIXES:
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(skill_dir).as_posix())


def load_skill_package(skill_path: Path, limit: int = 60000) -> tuple[str | None, str | None]:
    if not skill_path.exists():
        logger.warning("Skill package not found: %s", skill_path)
        return None, None
    if skill_path.is_file():
        return str(skill_path), _safe_read_text(skill_path, limit=limit)
    if not skill_path.is_dir():
        return None, None

    sections = [f"Package path: {skill_path}"]
    loaded = 0
    for file_path in _iter_skill_package_files(skill_path):
        rel = file_path.relative_to(skill_path).as_posix()
        content = _safe_read_text(file_path, limit=30000)
        if content is None:
            continue
        sections.extend([
            "",
            f"## File: {rel}",
            f"```{_fence_lang(file_path)}",
            content.rstrip(),
            "```",
        ])
        loaded += 1
    if loaded == 0:
        return None, None
    return str(skill_path), _truncate_text("\n".join(sections), limit)


def extract_markdown_sections(text: str, wanted_titles: list[str]) -> str:
    """Extract selected level-2 markdown sections by fuzzy title match."""
    if not text:
        return ""
    lines = text.splitlines()
    wanted = [title.lower() for title in wanted_titles]
    selected: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith("## "):
            title = line[3:].strip().lower()
            in_section = any(key in title for key in wanted)
        elif line.startswith("# ") and selected:
            in_section = False
        if in_section:
            selected.append(line)
    return "\n".join(selected).strip()


def extract_skill_schema(skill_text: str) -> dict[str, str]:
    """Turn the seven-section reimagined skill into phase-specific text fields."""
    return {
        "task_contract": extract_markdown_sections(skill_text, ["task-specific reading"]),
        "strategy": extract_markdown_sections(skill_text, ["highest-expected-score strategy"]),
        "first_run": extract_markdown_sections(skill_text, ["strong first implementation plan"]),
        "upgrade_menu": extract_markdown_sections(skill_text, ["high-roi upgrades across rounds"]),
        "validation_contract": extract_markdown_sections(skill_text, ["validation and metric optimization"]),
        "priorities": extract_markdown_sections(skill_text, ["model, feature, and preprocessing priorities"]),
        "avoid_rules": extract_markdown_sections(skill_text, ["avoid or delay"]),
    }


PARAMETER_FRAGMENT_NAMES = {
    "alpha", "batch_size", "c", "c_gamma", "clip", "fold", "folds", "gamma",
    "k", "max_depth", "max_features", "min_df", "n_estimators", "num_leaves",
    "pos_weight", "seed", "seeds", "temperature", "threshold", "tta",
    "sweep", "sweep_and",
}


SCHEMA_OR_LABEL_FRAGMENT_NAMES = {
    "id", "image_name", "patient_id", "target", "label", "class", "species",
    "sex", "age", "age_approx", "diagnosis", "benign_malignant",
    "anatom_site_general_challenge", "eap", "hpl", "mws",
    "toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate",
    "request_title", "request_text", "title_request_title", "body_request_text",
    "before", "after", "prev", "next", "sep", "shape", "token", "token_id",
    "sentence", "sentence_id", "text",
}


METHOD_HINT_TOKENS = (
    "model", "train", "fit", "cv", "fold", "oof", "auc", "logloss", "log_loss",
    "rmse", "rmsle", "qwk", "accuracy", "loss", "score", "blend", "stack",
    "ensemble", "rank average", "rank-average", "rank_blend", "selector",
    "cnn", "gbdt", "lightgbm", "lgbm", "xgboost", "xgb", "catboost",
    "tfidf", "countvectorizer", "transformer", "bert", "deberta", "roberta",
    "logistic", "ridge", "svc", "svm", "lda", "qda", "knn", "extratrees",
    "randomforest", "spectrogram", "segment", "sed", "embedding", "pseudo",
    "calibration", "calibrated", "temperature", "descriptor", "morphology",
    "efficientnet", "convnext", "regnet", "resnet", "densenet", "metadata_gbdt",
)


def _is_parameter_fragment(name: str) -> bool:
    clean = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    if clean in PARAMETER_FRAGMENT_NAMES:
        return True
    if re.fullmatch(r"(c|k|alpha|gamma|lambda|lr|eta)_[a-z0-9_]*", clean):
        return True
    if re.search(
        r"(min_df|max_df|ngram|pos_weight|batch|epoch|fold|seed|threshold|temperature|"
        r"min_child|num_leaves|max_depth|learning_rate|n_estimators|iterations|"
        r"subsample|colsample|lambda_l1|lambda_l2|reg_alpha|reg_lambda)",
        clean,
    ):
        return True
    return False


def _looks_like_schema_or_label_fragment(name: str) -> bool:
    clean = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    if clean in SCHEMA_OR_LABEL_FRAGMENT_NAMES:
        return True
    parts = [part for part in clean.split("_") if part]
    if parts and all(part in SCHEMA_OR_LABEL_FRAGMENT_NAMES for part in parts):
        return True
    if clean.startswith(("title_request_", "body_request_", "request_title_", "request_text_")):
        return True
    if re.fullmatch(r"(eap|hpl|mws)(?:_(eap|hpl|mws))*", clean):
        return True
    return False


def _operator_family(name: str, description: str = "") -> str:
    """Map an operator to a real method family, not a tiny parameter knob."""
    clean = name.lower()
    text = f"{clean} {description.lower()}"
    sed_token = bool(re.search(r"(?<![a-z0-9])(?:sed|timm[-_]?sed)(?![a-z0-9])", clean))
    audio_cnn_token = any(token in text for token in (
        "spectrogram", "log-mel", "log_mel", "stft", "mel-spectrogram", "mel spectrogram",
    )) and any(token in text for token in (
        "cnn", "conv1d", "efficientnet", "resnet", "regnet", "convnext",
    ))
    waveform_cnn_token = "waveform" in text and any(token in text for token in ("cnn", "conv1d", "filterbank"))

    # Representation semantics must beat backbone names. An EfficientNet used on
    # an audio spectrogram is an audio-spectrogram route, not a generic image
    # CNN route; otherwise novelty/anti-repetition compares the wrong family.
    if audio_cnn_token or "spectrogram" in clean:
        return "audio_spectrogram_cnn"
    if waveform_cnn_token:
        return "audio_waveform_cnn"
    if any(token in clean for token in ("effv2", "effnet", "efficientnet", "tf_efficientnet")):
        return "cnn_efficientnet"
    if any(token in clean for token in ("crop_norm", "crop_normal", "illumination", "black_border", "preprocess")):
        return "image_preprocessing"
    if any(token in clean for token in (
        "balanced_loss",
        "class_weight",
        "focal_loss",
        "sample_weight",
        "loss_reweight",
        "reweight",
    )):
        return "loss_reweighting"
    if any(token in clean for token in ("ordinal", "coral")):
        return "ordinal_head"
    if any(token in clean for token in ("oof_rank_blend", "rank_blend", "portfolio_blend", "blend")):
        return "blend_ensemble"
    if "stack" in clean:
        return "stack_ensemble"
    if "calibration" in clean or "temperature" in clean:
        return "calibration_postprocess"
    if "pseudo" in clean:
        return "pseudo_label"
    if "segment_hist" in clean or "segment_feature" in clean:
        return "audio_segment_tabular"
    if "segment_mil" in clean:
        return "audio_segment_mil"
    if sed_token:
        return "audio_sed"
    if "regnet" in clean:
        return "cnn_regnet"
    if "convnext" in clean:
        return "cnn_convnext"
    if "densenet" in clean:
        return "cnn_densenet"
    if "efficientnet" in clean:
        return "cnn_efficientnet"
    if "resnet" in clean:
        return "cnn_resnet"
    if "cnn_embedding" in clean:
        return "cnn_embedding"
    if "dermoscopy_cnn" in clean or "highres_dermoscopy" in clean:
        return "cnn_image"
    if "leaf_descriptor_svc" in clean or "descriptor_svc" in clean or "svc_rbf" in clean:
        return "descriptor_svc"
    if "shrinkage" in clean or "discriminant" in clean:
        return "descriptor_discriminant"
    if "neighbor" in clean or "knn" in clean:
        return "descriptor_knn"
    if "tree_descriptor" in clean:
        return "descriptor_tree"
    if "morphology" in clean or "binary_leaf" in clean:
        return "descriptor_morphology"
    if "descriptor_mlp" in clean:
        return "descriptor_neural"
    if (
        "tabular_embedding" in clean
        or (
            "embedding_mlp" in clean
            and any(token in text for token in ("categorical", "tabular", "numeric", "continuous", "count", "f_27"))
        )
    ):
        return "tabular_embedding_mlp"
    if "embedding_rnn" in clean or "bilstm" in clean or "bigru" in clean or re.search(r"(^|_)rnn($|_)", clean):
        return "neural_text"
    seq2seq_token = (
        "byt5" in text
        or re.search(r"(?<![a-z0-9])t5(?:[_\-/ ]?(?:small|base|large))?(?![a-z0-9])", text)
        or "seq2seq" in text
        or "sequence-to-sequence" in text
        or "sequence to sequence" in text
    )
    if seq2seq_token and any(token in text for token in (
        "textnorm", "text-normalization", "text normalization", "normalization residual",
        "normalization challenge", "before", "after",
    )):
        return "seq2seq_textnorm"
    if seq2seq_token:
        return "seq2seq_text"
    if "deberta" in clean or "roberta" in clean or "bert" in clean or "transformer" in clean:
        return "transformer_text"
    if any(token in clean for token in ("residual_slice", "slice_report", "report", "diagnostic")):
        return "eda_diagnostics"
    if "before" in clean and "after" in clean and ("most_frequent" in clean or "frequent" in clean):
        return "seen_context_mapping_textnorm"
    textnorm_token = "textnorm" in clean or "text-normalization" in text or "text normalization" in text
    if textnorm_token and not any(token in clean for token in ("byt5", "t5", "seq2seq", "neural_residual", "residual_neural")):
        if any(token in clean for token in ("candidate_rank", "ranker", "selector", "ml_router", "class_router", "lgbm")):
            return "candidate_ranked_context_maps_textnorm"
        if any(token in clean for token in ("seen", "mapping", "map", "dictionary", "direct", "context", "exact", "most_frequent")):
            return "seen_context_mapping_textnorm"
        if any(token in clean for token in ("rule", "grammar", "router", "specialist")):
            return "rule_router_textnorm"
        return "rule_router_textnorm"
    if "tabular_linear" in clean or "logistic" in clean or re.search(r"(^|_)linear($|_)", clean):
        return "linear_tabular"
    if clean.startswith("metadata_") or "meta_textstats" in clean:
        return "metadata_tabular"
    if "catboost" in clean:
        return "tabular_catboost"
    if any(token in clean for token in ("gbdt", "lgbm", "lightgbm", "xgb", "xgboost")):
        return "tabular_gbdt"
    family_rules: list[tuple[str, tuple[str, ...]]] = [
        ("seq2seq_textnorm", ("byt5", "textnorm", "text-normalization", "normalization residual")),
        ("seq2seq_text", ("t5", "seq2seq", "sequence-to-sequence", "sequence to sequence")),
        ("transformer_text", ("deberta", "roberta", "bert", "transformer", "microsoft_deberta")),
        ("neural_text", ("bilstm", "bigru", "rnn", "embedding_rnn", "sentence_embedding", "frozen_embedding")),
        ("sparse_text", ("tfidf", "countvectorizer", "word", "char", "char_wb", "ngram", "nb-svm", "sparse", "stylometry", "min_df", "vocab")),
        ("stack_ensemble", ("stack", "level-2", "oof_author_stack", "ridge stack")),
        ("descriptor_svc", ("leaf_descriptor_svc", "rbf svc", "gamma")),
        ("descriptor_discriminant", ("shrinkage", "lda", "qda", "discriminant")),
        ("descriptor_knn", ("neighbor", "knn", "metric")),
        ("descriptor_tree", ("tree_descriptor", "randomforest", "extratrees")),
        ("descriptor_morphology", ("morphology", "binary_leaf")),
        ("descriptor_neural", ("descriptor_mlp", "mlp_labelsmooth")),
        ("calibration_postprocess", ("calibration", "calibrated", "temperature", "threshold", "clip", "postprocess")),
        ("tabular_catboost", ("catboost",)),
        ("tabular_gbdt", ("lightgbm", "lgbm", "xgboost", "xgb", "gbdt", "extra trees", "extratrees", "tree")),
        ("linear_tabular", ("linear", "logistic", "ridge", "sgd", "svm", "svc", "c_gamma")),
        ("audio_sed", ("timm-sed", "timm_sed", "sed_logmel", "logmel_sed")),
        ("audio_spectrogram_cnn", ("spectrogram", "log-mel", "bmp")),
        ("audio_segment_tabular", ("segment_hist", "segment_feature", "histogram", "rectangle")),
        ("audio_segment_mil", ("segment_mil",)),
        ("cnn_embedding", ("cnn_embedding", "embedding_gbdt")),
        ("cnn_convnext", ("convnext",)),
        ("cnn_densenet", ("densenet",)),
        ("cnn_regnet", ("regnet",)),
        ("cnn_efficientnet", ("efficientnet", "tf_efficientnet")),
        ("cnn_resnet", ("resnet", "resnetrs")),
        ("cnn_image", ("dermoscopy", "image", "jpeg", "highres", "dicom", "vit")),
        ("metadata_patient_context", ("ugly_duckling", "patient", "metadata_gbdt", "patient-context")),
        ("metadata_tabular", ("metadata", "meta", "textstats", "svd", "subreddit")),
        ("blend_ensemble", ("blend", "rank", "selector", "ensemble", "oof_rank", "probability average", "logit average")),
        ("pseudo_label", ("pseudo", "soft_pseudo")),
        ("transductive_vocab", ("train_test_vocab", "train+test", "transductive")),
    ]
    for family, needles in family_rules:
        if any(needle in text for needle in needles):
            return family

    if _is_parameter_fragment(clean):
        return "parameter_tuning"
    return clean.split("_", 1)[0] if "_" in clean else clean[:40]


def _operator_cost_and_risk(name: str, description: str) -> tuple[str, str]:
    text = f"{name} {description}".lower()
    high_cost = (
        "full", "all-data", "large", "many-fold", "neural", "deep", "gpu",
        "cnn", "convnext", "efficientnet", "efficientnetv2", "effv2",
        "resnet", "densenet", "vit", "swin", "timm", "torch", "pytorch",
        "pretrained", "backbone", "highres", "high-resolution", "dicom",
        "spectrogram_cnn", "wav2vec",
        "deberta", "transformer", "bert", "roberta",
    )
    medium_cost = (
        "lightgbm", "catboost", "xgboost", "gbdt", "randomforest",
        "svd", "tfidf", "ngram", "logistic", "ridge", "metadata",
    )
    low_cost = ("postprocess", "calibration", "threshold", "clip", "blend", "regularization")
    high_risk = ("pseudo", "external", "deberta", "transformer", "alternative", "xgb_gpu")
    cost = (
        "high" if any(token in text for token in high_cost)
        else "medium" if any(token in text for token in medium_cost)
        else "low" if any(token in text for token in low_cost)
        else "medium"
    )
    risk = "high" if any(token in text for token in high_risk) else ("medium" if cost == "high" else "low" if cost == "low" else "medium")
    return cost, risk


def _sanitize_operator_description(description: str) -> str:
    """Remove cross-round file-saving instructions from task-skill operator text."""
    return sanitize_legacy_prediction_file_language(description)


def _valid_skill_operator_name(name: str) -> bool:
    """Reject parameter fragments that are often backticked inside operator descriptions."""
    if not name:
        return False
    if not re.search(r"[A-Za-z]", name):
        return False
    if re.fullmatch(r"\d+(?:[_-]\d+)*", name):
        return False
    if len(name) < 5:
        return False
    return True


def _operator_intent_from_line(line: str, section: str) -> str:
    lower = line.lower()
    if "improve_best" in lower:
        return INTENT_IMPROVE_BEST
    if "explore_alternative" in lower or "alternative" in lower or "late round" in lower:
        return INTENT_EXPLORE_ALTERNATIVE
    if "ablate" in lower:
        return INTENT_ABLATE_BEST
    if (
        "blend" in lower
        or "ensemble" in lower
        or "stack" in lower
        or "selector" in lower
        or "rank average" in lower
        or "rank-average" in lower
        or "rank_blend" in lower
        or "oof_rank" in lower
    ):
        return INTENT_ENSEMBLE
    if section in {"strategy", "first_run"}:
        return INTENT_IMPROVE_BEST
    return INTENT_IMPROVE_BEST


def _normalize_skill_operator_label(label: str, line: str, section: str) -> str | None:
    """Convert a skill label or parameter fragment into a schedulable operator name."""
    original = label.strip()
    if "/" in original:
        # Usually a model checkpoint reference inside an operator description.
        return None
    if re.search(r"\[[A-Za-z0-9_-]+\]", original):
        # Prompt/input templates such as `prev [SEP] before [SEP] next` are not operators.
        return None
    raw = re.sub(r"[^A-Za-z0-9_\-]+", "_", label.strip()).strip("_")
    if raw in {
        INTENT_IMPROVE_BEST,
        INTENT_EXPLORE_ALTERNATIVE,
        INTENT_ABLATE_BEST,
        INTENT_REPAIR_FAILURE,
        INTENT_RESET_BASELINE,
        INTENT_ENSEMBLE,
        INTENT_SUBMISSION_AUDIT,
    }:
        return None
    if not _valid_skill_operator_name(raw):
        return None

    lower = raw.lower()
    text = line.lower()
    if _looks_like_schema_or_label_fragment(raw):
        return None
    if not any(token in lower or token in text for token in METHOD_HINT_TOKENS):
        return None
    if _is_parameter_fragment(lower):
        if "tfidf" in text or "text" in text or "word" in text or "char" in text:
            return "sparse_text_regularized_tfidf"
        if "svc" in text or "svm" in text or "descriptor" in text or "leaf" in text:
            return "descriptor_svc_rbf_tuning"
        if "pos_weight" in lower or "imbalance" in text or "bce" in text:
            return "imbalance_loss_image_cnn"
        if "calibration" in text or "temperature" in text or "clip" in text:
            return "calibration_postprocess_tuning"
        return None

    if "/" in raw or raw.count("-") >= 2:
        # Usually a model checkpoint string rather than a distinct route.
        return None
    return raw[:80]


def _iter_operator_candidate_lines(schema: dict[str, str]) -> list[tuple[str, str]]:
    """Return candidate-bearing lines from all modeling sections of the skill."""
    ordered_sections = ["priorities", "strategy", "upgrade_menu"]
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for section in ordered_sections:
        for raw_line in (schema.get(section) or "").splitlines():
            line = raw_line.strip()
            is_list_item = line.startswith("-") or bool(re.match(r"^\d+[\.\)]\s+", line))
            if not is_list_item:
                continue
            lower = line.lower()
            if not any(token in lower for token in (
                "`", "model", "train", "blend", "stack", "cnn", "gbdt", "tfidf", "transformer",
                "lightgbm", "catboost", "xgboost", "logistic", "svc", "svm", "rank", "metadata",
                "spectrogram", "embedding", "pseudo", "calibration", "descriptor",
            )):
                continue
            key = (section, line)
            if key in seen:
                continue
            seen.add(key)
            rows.append(key)
    return rows


def _generic_prior_operators(existing_families: set[str]) -> list[SearchOperator]:
    """Add model-prior routes so task skills guide but do not exhaust search."""
    generic = [
        SearchOperator(
            V37_MODEL_PRIOR_OPERATOR_NAME,
            INTENT_EXPLORE_ALTERNATIVE,
            "model_prior_freeform",
            (
                "Use task contract, EDA, memory, and general Kaggle/ML knowledge to propose one bounded "
                "method family not already represented in the portfolio. This is explicitly allowed when "
                "task-skill operators are too narrow or repeated."
            ),
            "v4_model_prior_controller",
            "medium",
            "medium",
        ),
        SearchOperator(
            V37_EDA_PRIOR_OPERATOR_NAME,
            INTENT_EXPLORE_ALTERNATIVE,
            "eda_prior",
            (
                "Use EDA/schema/residual evidence to create a data-driven route that is distinct from the "
                "dominant family, with strict runtime caps and a trained fallback."
            ),
            "v4_eda_prior_controller",
            "low",
            "medium",
        ),
        SearchOperator(
            V37_STACK_OPERATOR_NAME,
            INTENT_ENSEMBLE,
            "blend_ensemble",
            (
                "Create a small in-round cross-family stack/rank blend from cheap comparable candidates, "
                "or reproduce prior candidates from inspected code when that is cheaper."
            ),
            "v4_portfolio_controller",
            "low",
            "low",
        ),
    ]
    return [op for op in generic if op.family not in existing_families or op.name == V37_STACK_OPERATOR_NAME]


def extract_skill_operators(task_name: str, task_skills_dir: Path) -> list[SearchOperator]:
    """Extract rich operator candidates from the reimagined skill."""
    fallback = [
        SearchOperator("strong_first_run", INTENT_RESET_BASELINE, "baseline", "Execute the skill's strong first implementation plan with strict runtime fallbacks.", "v3_fallback", "medium", "low"),
        SearchOperator("safe_portfolio_tune", INTENT_IMPROVE_BEST, "portfolio_tune", "Strengthen a proven portfolio candidate with folds, features, regularization, calibration, clipping, or postprocessing.", "v3_fallback", "low", "low"),
        SearchOperator("skill_alternative", INTENT_EXPLORE_ALTERNATIVE, "alternative", "Try one bounded alternative explicitly allowed by the task skill.", "v3_fallback", "medium", "medium"),
        SearchOperator("portfolio_blend", INTENT_ENSEMBLE, "blend_ensemble", "Build a simple robust blend or selector from top diverse local-CV candidates.", "v3_fallback", "low", "low"),
    ]
    _, skill_text = load_task_skill(task_name, task_skills_dir)
    if not skill_text:
        return fallback
    schema = extract_skill_schema(skill_text)
    candidates: list[SearchOperator] = []
    seen: set[str] = set()
    for section, line in _iter_operator_candidate_lines(schema):
        labels = re.findall(r"`([^`]{3,80})`", line)
        if not labels:
            # Reimagined skills sometimes write the action as plain text after a colon.
            matches = re.findall(r"(?:improve_best|explore_alternative|safe|true)\s+([a-zA-Z][a-zA-Z0-9_\-]{4,80})", line)
            labels = matches
        for label in labels:
            name = _normalize_skill_operator_label(label, line, section)
            if not name or name in seen:
                continue
            seen.add(name)
            intent = _operator_intent_from_line(line, section)
            cost, risk = _operator_cost_and_risk(name, line)
            candidates.append(SearchOperator(
                name=name[:80],
                intent=intent,
                family=_operator_family(name, line),
                description=_sanitize_operator_description(line)[:700],
                source=f"skill_{section}",
                cost=cost,
                risk=risk,
            ))

    if not candidates:
        candidates = fallback
    elif not any(op.intent == INTENT_ENSEMBLE for op in candidates):
        candidates.append(fallback[-1])
    existing_families = {op.family for op in candidates}
    candidates.extend(op for op in _generic_prior_operators(existing_families) if op.name not in seen)
    return candidates[:32]


def search_operator_to_dict(op: SearchOperator) -> dict[str, Any]:
    return {
        "name": op.name,
        "intent": op.intent,
        "family": op.family,
        "description": op.description,
        "source": op.source,
        "cost": op.cost,
        "risk": op.risk,
    }


def search_operator_from_dict(payload: dict[str, Any]) -> SearchOperator:
    return SearchOperator(
        name=str(payload.get("name") or "safe_portfolio_tune"),
        intent=str(payload.get("intent") or INTENT_IMPROVE_BEST),
        family=str(payload.get("family") or "unknown"),
        description=str(payload.get("description") or ""),
        source=str(payload.get("source") or "unknown"),
        cost=str(payload.get("cost") or "medium"),
        risk=str(payload.get("risk") or "medium"),
    )


def build_skill_schema_context(skill_text: str | None) -> str:
    if not skill_text:
        return ""
    schema = extract_skill_schema(skill_text)
    compact = {key: _truncate_text(value, 2500) for key, value in schema.items() if value}
    if not compact:
        return ""
    return json.dumps(compact, indent=2, ensure_ascii=False)


def build_v33_skill_packet(
    task_skill: str | None,
    branch: str,
    branch_decision: dict[str, Any] | None = None,
) -> str:
    """Return a compact phase-specific task-skill packet instead of the full skill."""
    if not task_skill:
        return ""
    task_skill = _sanitize_operator_description(task_skill)
    branch = normalize_branch_name(branch)
    decision = branch_decision or {}
    operator = decision.get("search_operator") or {}
    intent = str(decision.get("search_intent") or operator.get("intent") or "")
    schema = extract_skill_schema(task_skill)

    if intent in {INTENT_FRONTLOAD_DRAFT, INTENT_FRESH_DRAFT}:
        keys = ["task_contract", "strategy", "upgrade_menu", "priorities", "validation_contract", "avoid_rules"]
        per_key_limit = 1700
        total_limit = V33_SKILL_CONTEXT_LIMITS["draft"]
    elif branch == "draft" or intent == INTENT_PORTFOLIO_SEED:
        keys = ["task_contract", "strategy", "priorities", "first_run", "validation_contract", "avoid_rules"]
        per_key_limit = 2300
        total_limit = V33_SKILL_CONTEXT_LIMITS["draft"]
    elif branch == "debug":
        keys = ["task_contract", "validation_contract", "avoid_rules"]
        per_key_limit = 1200
        total_limit = V33_SKILL_CONTEXT_LIMITS["debug"]
    elif intent in {INTENT_EXPLORE_ALTERNATIVE, INTENT_STRATEGY_REPLACE, INTENT_PORTFOLIO_EXPAND}:
        keys = ["task_contract", "upgrade_menu", "priorities", "validation_contract", "avoid_rules"]
        per_key_limit = 1400
        total_limit = V33_SKILL_CONTEXT_LIMITS["improve"]
    elif intent in {INTENT_PORTFOLIO_STRENGTHEN, INTENT_PORTFOLIO_BLEND}:
        keys = ["task_contract", "strategy", "upgrade_menu", "validation_contract", "avoid_rules"]
        per_key_limit = 1400
        total_limit = V33_SKILL_CONTEXT_LIMITS["improve"]
    elif intent == INTENT_TIMEOUT_SAFE:
        keys = ["task_contract", "validation_contract", "avoid_rules"]
        per_key_limit = 1200
        total_limit = V33_SKILL_CONTEXT_LIMITS["debug"]
    else:
        keys = ["task_contract", "upgrade_menu", "validation_contract", "avoid_rules"]
        per_key_limit = 1300
        total_limit = V33_SKILL_CONTEXT_LIMITS["improve"]

    payload: dict[str, Any] = {}
    for key in keys:
        value = schema.get(key)
        if value:
            selected, record = text_or_retrieval_note(key, value, per_key_limit)
            payload[key] = selected
            if record.get("omitted_lines"):
                payload[f"{key}_retrieval"] = "Full section is available in the routed task skill source listed in [CONTEXT SOURCE MAP]."
    if operator:
        payload["selected_operator"] = json.loads(compact_operator_card(operator))
    packet = json.dumps(payload, indent=2, ensure_ascii=False)
    if len(packet) <= total_limit:
        return packet

    # Reduce complete-line section budgets without emitting broken prose or invalid JSON.
    reduced_payload = dict(payload)
    for key in reversed(keys):
        value = reduced_payload.get(key)
        if not isinstance(value, str) or len(json.dumps(reduced_payload, indent=2, ensure_ascii=False)) <= total_limit:
            continue
        target = max(500, len(value) - (len(json.dumps(reduced_payload, indent=2, ensure_ascii=False)) - total_limit) - 200)
        reduced_payload[key] = compact_text_field(value, target)
        reduced_payload[f"{key}_retrieval"] = "Full section is available in the routed task skill source listed in [CONTEXT SOURCE MAP]."
    packet = json.dumps(reduced_payload, indent=2, ensure_ascii=False)
    if len(packet) <= total_limit:
        return packet

    # Last semantic fallback: keep the task contract and compact route metadata; rely on the source map for the full skill.
    minimal_payload = {
        "task_contract": reduced_payload.get("task_contract", ""),
        "selected_operator": reduced_payload.get("selected_operator"),
        "full_skill_retrieval": "The complete task skill source is listed in [CONTEXT SOURCE MAP]; read it if the compact packet is insufficient.",
    }
    return json.dumps({k: v for k, v in minimal_payload.items() if v}, indent=2, ensure_ascii=False)


def build_v33_failure_skill_packet(error_skill: str | None) -> str:
    """Keep failure-prevention guidance compact and only for debug/timeout repair."""
    if not error_skill:
        return ""
    selected = extract_markdown_sections(
        error_skill,
        ["runtime", "submission", "schema", "timeout", "oom", "dependency", "debug", "failure"],
    )
    return compact_text_field(selected or error_skill, 2600)


def route_skills_for_branch(
    task_name: str,
    branch: str,
    task_skills_dir: Path,
    eda_skill_dir: Path,
    error_skill_file: Path,
    branch_decision: dict[str, Any] | None = None,
) -> SkillRoute:
    """Route branch source paths; large skill bodies are inspected by path."""
    branch = normalize_branch_name(branch)
    sources: list[str] = []
    sections: list[str] = []

    def add_source(title: str, path: str | None, content: str | None = None) -> None:
        if path:
            sources.append(path)
        if content:
            sections.extend([f"## {title}", content.strip()])

    if branch == "draft":
        task_skill_path, task_skill = load_task_skill(task_name, task_skills_dir)
        error_path, _error_skill = load_skill_package(error_skill_file, limit=1)
        add_source("Task Skill Source", task_skill_path)
        add_source("Failure Prevention Skill Source", error_path)
        add_source("Draft Guard", None, DRAFT_TASK_SKILL_GUARD)
        add_source("Runtime Hardening Guard", None, RUNTIME_HARDENING_CONTEXT)
        reason = "draft must inspect task skill and failure-prevention skill paths; only compact branch guards are inlined"
    elif branch == "debug":
        error_path, _error_skill = load_skill_package(error_skill_file, limit=1)
        task_skill_path, _task_skill = load_task_skill(task_name, task_skills_dir)
        add_source("Failure Prevention Skill Source", error_path)
        add_source("Task Skill Source", task_skill_path)
        add_source("Debug Error Taxonomy Guard", None, DEBUG_ERROR_GUARD)
        add_source("Runtime Hardening Guard", None, RUNTIME_HARDENING_CONTEXT)
        reason = "debug must inspect failure-prevention skill plus linked parent code and feedback; task skill is available as optional task-specific modeling prior"
    elif branch == "improve":
        task_skill_path, task_skill = load_task_skill(task_name, task_skills_dir)
        add_source("Task Skill Source", task_skill_path)
        add_source("Improve Best Guard", None, IMPROVE_BEST_GUARD)
        add_source("Runtime Hardening Guard", None, RUNTIME_HARDENING_CONTEXT)
        reason = "improve must inspect task skill and anchor parent paths, then may inspect extra cards/code"
    else:
        task_skill_path, task_skill = load_task_skill(task_name, task_skills_dir)
        add_source("Task-Specific Knowledge", task_skill_path, build_v33_skill_packet(task_skill, branch, branch_decision))
        reason = "fallback route"

    content = "\n\n".join(sections).strip()
    if not content:
        content = "No large skill text is inlined. Inspect required skill source paths from the context source map."
    return SkillRoute(branch=branch, reason=reason, sources=sources, content=content)
