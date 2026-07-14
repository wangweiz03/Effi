from __future__ import annotations

from .common import *
from .constants import *

def memory_bank_dir(task_dir: Path) -> Path:
    return task_dir / "memory_bank"


def memory_bank_path(task_dir: Path, name: str) -> Path:
    return memory_bank_dir(task_dir) / name


def memory_prompt_file(task_dir: Path) -> Path:
    return memory_bank_path(task_dir, "prompt_context.md")


def load_memory_for_task(task_name: str, task_dir: Path, limit: int = V33_TASK_MEMORY_PROMPT_LIMIT) -> str:
    prompt_context = _safe_read_text(memory_prompt_file(task_dir), limit=limit)
    if prompt_context:
        return prompt_context
    return "No task memory yet."


def _load_memory_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_memory_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_memory_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _tail_memory_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    rows = _load_jsonl(path)
    return rows[-limit:] if limit > 0 else rows


def infer_code_method_families(code: str) -> list[str]:
    """Infer broad modeling families actually covered by the generated code."""
    lower = code.lower()
    families: set[str] = set()
    sed_token = bool(re.search(r"(?<![a-z0-9])(?:sed|timm[-_]?sed)(?![a-z0-9])", lower))
    neural_tokens = (
        "torch", "torchvision", "tensorflow", "keras", "nn.module", "conv2d",
        "bcewithlogits", "adamw", "densenet", "resnet", "efficientnet",
        "convnext", "regnet", "timm",
    )
    audio_markers = (
        "librosa", "soundfile", ".wav", "wave.open", "torchaudio",
        "sample_rate", "sampling_rate", "audio", "melspectrogram",
        "mel spectrogram", "logmel", "log_mel", "stft",
    )
    image_descriptor_markers = (
        "cv2", "pil", "image.open", "thumbnail", "resize", "id_code",
        "train_images", "test_images", "diagnosis", "laplacian", "sobel",
        "perceptual hash", "phash", "retina", "fundus",
    )
    spectrogram_tokens = ("spectrogram", "filtered_spectrogram", "logmel", "log_mel")
    is_sed = (
        sed_token
        or any(token in lower for token in ("temporal pooling", "attention pooling", "noisy-or"))
        or (
            any(token in lower for token in ("logmel", "log_mel", "mel spectrogram", "melspectrogram"))
            and any(token in lower for token in neural_tokens)
        )
    )
    has_audio_marker = any(token in lower for token in audio_markers)
    has_image_descriptor_marker = any(token in lower for token in image_descriptor_markers)
    if any(token in lower for token in ("librosa", "soundfile", ".wav", "wave.open", "torchaudio")):
        families.add("audio_stats")
    if has_audio_marker and any(token in lower for token in spectrogram_tokens):
        if any(token in lower for token in neural_tokens) and not is_sed:
            families.add("audio_spectrogram_cnn")
        else:
            families.add("audio_spectrogram_stats")
    if is_sed:
        families.add("audio_sed")
    transformer_text_patterns = (
        r"^\s*(?:from|import)\s+transformers\b",
        r"\b(?:AutoTokenizer|AutoModel|AutoConfig|BertModel|BertFor|RobertaModel|DebertaModel)\b",
        r"\b(?:bert|roberta|deberta)[-_]?(?:base|large)\b",
    )
    if any(re.search(pattern, code, flags=re.MULTILINE | re.IGNORECASE) for pattern in transformer_text_patterns):
        families.add("transformer_text")

    checks = [
        ("audio_segment_tabular", ("histogram_of_segments", "segment_features", "segment_rectangles")),
        ("descriptor_morphology", ("morphology", "binary_leaf", "contour", "hu moments", "skeleton")),
        ("cnn_image", ("convnext", "efficientnet", "resnet", "densenet", "timm", "torchvision")),
        ("descriptor_neural", ("mlp", "dropout", "label_smoothing")),
        ("neural_text", ("bilstm", "bigru", "embedding", "lstm", "gru")),
        ("sparse_text", ("tfidf", "countvectorizer", "char_wb", "ngram", "nbsvm")),
        ("linear_tabular", ("logisticregression", "ridgeclassifier", "sgdclassifier", "linearsvc")),
        ("descriptor_svc", ("svc(", "svm.svc", "kernel=\"rbf\"", "kernel='rbf'")),
        ("descriptor_discriminant", ("lineardiscriminantanalysis", "quadraticdiscriminantanalysis", "shrinkage")),
        ("descriptor_knn", ("kneighborsclassifier", "nearestneighbors")),
        ("descriptor_tree", ("extratrees", "randomforest")),
        ("tabular_gbdt", ("lightgbm", "lgbm", "xgboost", "xgb", "catboost")),
    ]
    for family, needles in checks:
        if any(needle in lower for needle in needles):
            families.add(family)
    if "sparse_text" in families and "linear_tabular" in families:
        # Logistic/SGD/LinearSVC are usually classifier heads for TF-IDF text
        # pipelines, not an independent tabular modeling family.
        tabular_markers = (
            "select_dtypes", "numeric_cols", "feature_cols", "category_cols",
            "categorical_cols", "onehotencoder", "columntransformer",
            "lightgbm", "xgboost", "catboost", "randomforest", "extratrees",
        )
        if not any(token in lower for token in tabular_markers):
            families.discard("linear_tabular")
    if has_image_descriptor_marker and "linear_tabular" in families:
        tabular_markers = (
            "select_dtypes", "numeric_cols", "feature_cols", "category_cols",
            "categorical_cols", "onehotencoder", "columntransformer",
            "lightgbm", "xgboost", "catboost", "randomforest", "extratrees",
        )
        if not any(token in lower for token in tabular_markers):
            families.discard("linear_tabular")
    return sorted(families)


def inspect_code_memory_features(code: str) -> dict[str, Any]:
    """Cheap deterministic code anatomy for the memory bank."""
    lower = code.lower()
    imports = sorted(set(re.findall(r"^\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)", code, flags=re.MULTILINE)))[:30]
    model_tokens = [
        token for token in (
            "lightgbm", "lgbm", "xgboost", "xgb", "catboost", "randomforest", "extratrees",
            "logisticregression", "ridge", "svm", "torch", "tensorflow", "keras", "transformers",
            "tfidf", "countvectorizer", "efficientnet", "resnet", "unet", "cnn",
        )
        if token in lower
    ]
    validation_tokens = [
        token for token in ("kfold", "stratifiedkfold", "groupkfold", "timeseriessplit", "train_test_split", "oof")
        if token.lower() in lower
    ]
    diagnostic_tokens = [
        token for token in ("oof", "test_pred", "predictions", "fold", "feature", "blend", "threshold", "calibration")
        if token in lower
    ]
    modality_hints = [
        name for name, keys in {
            "tabular": ("read_csv", "dataframe", "lightgbm", "xgboost", "catboost"),
            "text": ("tfidf", "tokenizer", "transformers", "bert", "text"),
            "image": ("image", "cv2", "pil", "torchvision", "efficientnet", "resnet"),
            "audio": ("librosa", "wav", "spectrogram"),
        }.items()
        if any(key in lower for key in keys)
    ]
    side_output_write_patterns = (
        r"\b(?:joblib|pickle|cloudpickle|dill)\s*\.\s*dump\s*\(",
        r"\bnp\s*\.\s*savez?(?:_compressed)?\s*\(",
        r"\bto_(?:pickle|parquet|feather|hdf)\s*\(",
        r"\b(?:save|write)_(?:oof|test|pred|preds|prediction|predictions|model|models)\b",
        r"\.to_csv\s*\([^)]*(?:oof|pred|preds|prediction|predictions|model|models|fold_dump|folds_dump|blend)",
        r"open\s*\([^)]*(?:oof|pred|preds|prediction|predictions|model|models|fold_dump|folds_dump|blend)[^)]*,\s*['\"][wa+]",
    )
    writes_side_outputs = any(re.search(pattern, lower) for pattern in side_output_write_patterns)
    return {
        "imports": imports,
        "model_tokens": sorted(set(model_tokens)),
        "method_families": infer_code_method_families(code),
        "validation_tokens": sorted(set(validation_tokens)),
        "diagnostic_tokens": sorted(set(diagnostic_tokens)),
        "modality_hints": modality_hints,
        "line_count": len(code.splitlines()),
        "has_fallback": "fallback" in lower or "except" in lower,
        "uses_sample_submission": "sample_submission" in lower,
        "writes_submission_csv": "submission.csv" in lower,
        "writes_side_outputs": writes_side_outputs,
    }


def init_git_structure(task_dir: Path, branch_specs: tuple[BranchSpec, ...] = BRANCH_SPECS) -> None:
    """Initialize git-style directory structure."""
    (task_dir / "commits").mkdir(exist_ok=True)
    (task_dir / "index").mkdir(exist_ok=True)
    (task_dir / V3_GRAPH_DIR).mkdir(exist_ok=True)
    (task_dir / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (task_dir / "refs" / "tags").mkdir(parents=True, exist_ok=True)
    (task_dir / "traces").mkdir(exist_ok=True)
    memory_bank_dir(task_dir).mkdir(exist_ok=True)

    for spec in branch_specs:
        head_file = task_dir / "refs" / "heads" / spec.name
        if not head_file.exists():
            head_file.write_text("", encoding="utf-8")
    main_head = task_dir / "refs" / "heads" / "main"
    if not main_head.exists():
        main_head.write_text("", encoding="utf-8")
    (task_dir / "index" / "commit_log.jsonl").touch()
    branch_summary = {}
    for spec in branch_specs:
        branch_summary[spec.name] = {
            "title": spec.title,
            "goal": spec.goal,
            "head": "",
            "score": None,
            "best_score": None,
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "total_time": 0.0,
            "last_status": None,
            "last_round": None,
            "updated_at": None,
        }
    branch_summary_file = task_dir / "index" / "branch_summary.json"
    if not branch_summary_file.exists():
        branch_summary_file.write_text(json.dumps(branch_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    tag_registry_file = task_dir / "index" / "tag_registry.json"
    if not tag_registry_file.exists():
        tag_registry_file.write_text("{}", encoding="utf-8")
def create_commit_hash(round_num: int, timestamp: str) -> str:
    """Generate a short commit hash."""
    return hashlib.sha1(f"{round_num}_{timestamp}".encode("utf-8")).hexdigest()[:8]


def normalize_solution_for_fingerprint(code: str) -> str:
    """Normalize formatting noise before checking whether a generated solution is identical."""
    normalized = code.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def solution_fingerprint(code: str) -> str:
    return hashlib.sha256(normalize_solution_for_fingerprint(code).encode("utf-8")).hexdigest()


def find_duplicate_solution(task_dir: Path, code: str) -> dict[str, Any] | None:
    """Return the prior commit with the same normalized solution.py, if any."""
    fingerprint = solution_fingerprint(code)
    commits_dir = task_dir / "commits"
    if not commits_dir.exists():
        return None
    candidates: list[tuple[int, str, Path, dict[str, Any]]] = []
    for solution_path in commits_dir.glob("*/solution.py"):
        try:
            prior_code = solution_path.read_text(encoding="utf-8")
        except Exception:
            continue
        if solution_fingerprint(prior_code) != fingerprint:
            continue
        commit = solution_path.parent.name
        result_path = solution_path.parent / "result.json"
        prior_result = safe_load_json_file(result_path)
        try:
            prior_round = int(prior_result.get("round"))
        except Exception:
            prior_round = 10**9
        candidates.append((prior_round, commit, solution_path, prior_result))
    if candidates:
        _, commit, solution_path, prior_result = sorted(candidates, key=lambda item: (item[0], item[1]))[0]
        result_path = solution_path.parent / "result.json"
        return {
            "commit": commit,
            "code_path": f"commits/{commit}/solution.py",
            "result_path": f"commits/{commit}/result.json" if result_path.exists() else None,
            "round": prior_result.get("round"),
            "score": (prior_result.get("validation") or {}).get("score"),
            "status": (prior_result.get("validation") or {}).get("status"),
            "fingerprint": fingerprint,
        }
    return None


def clear_active_scratch_workspace(task_dir: Path) -> None:
    """Remove stale auxiliary output directories before each generated-code round."""
    for name in ("planning.md", "context_readiness.md", POST_CODE_MEMORY_SUMMARY_FILENAME, "submission.csv"):
        path = task_dir / name
        if path.exists() and not path.is_dir():
            path.unlink()
    for name in ("diagnostics", "outputs"):
        path = task_dir / name
        if not path.exists():
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def validation_experiment_signature(
    feedback: str,
    score: float | None,
    operator: SearchOperator | None,
) -> dict[str, Any]:
    """Create a compact signature for repeated-prediction/repeated-selection detection."""
    interesting: list[str] = []
    for line in str(feedback or "").splitlines():
        lower = line.lower()
        if any(token in lower for token in (
            "selected final candidate",
            "selected candidate",
            "final candidate",
            "blend_weights",
            "selection policy",
            "oof auc",
            "oof logloss",
            "oof log loss",
        )):
            interesting.append(re.sub(r"\s+", " ", line.strip())[:240])
        if len(interesting) >= 20:
            break
    rounded_score = None if score is None else round(float(score), 10)
    payload = {
        "operator": operator.name if operator else None,
        "family": operator.family if operator else None,
        "score": rounded_score,
        "evidence": interesting,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "hash": digest,
        "score": rounded_score,
        "evidence_lines": interesting,
    }


def save_commit(
    task_dir: Path,
    commit_hash: str,
    planning_text: str,
    solution_code: str,
    feedback: str,
    result: dict[str, Any],
    round_summary: dict[str, str] | None = None,
) -> None:
    """Save commit payload."""
    commit_dir = task_dir / "commits" / commit_hash
    commit_dir.mkdir(parents=True, exist_ok=True)

    (commit_dir / "solution.py").write_text(solution_code, encoding="utf-8")
    (commit_dir / "validation_feedback.txt").write_text(feedback, encoding="utf-8")
    context_readiness = task_dir / "context_readiness.md"
    if context_readiness.exists():
        shutil.copyfile(context_readiness, commit_dir / "context_readiness.md")
    post_code_memory_summary = task_dir / POST_CODE_MEMORY_SUMMARY_FILENAME
    if post_code_memory_summary.exists():
        shutil.copyfile(post_code_memory_summary, commit_dir / POST_CODE_MEMORY_SUMMARY_FILENAME)
    if round_summary:
        (commit_dir / "round_summary.json").write_text(
            json.dumps(round_summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        summary_md = (
            f"Method: {round_summary.get('method_summary', '')}\n"
            f"Family: {round_summary.get('method_family', '')}\n"
            f"Components: {round_summary.get('core_components', [])}\n"
            f"Novelty: {round_summary.get('novelty_vs_best', '')}\n"
            f"Reflection: {round_summary.get('result_reflection', '')}\n"
        )
        (commit_dir / "round_summary.md").write_text(summary_md, encoding="utf-8")
    (commit_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
