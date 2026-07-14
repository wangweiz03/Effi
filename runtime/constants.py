from __future__ import annotations

from .common import *

SANDBOX_BASE_URL = os.environ.get("MLEBENCH_SANDBOX_BASE_URL", "http://183.222.230.77:6580")
SUBMIT_DATA_ROOT = Path(os.environ.get("MLEBENCH_SUBMIT_DATA_ROOT", "/mnt/pubdatasets2/automized_std_bench/dojo4mlebench/data/prepared"))
FRAMEWORK_RESOURCES_ROOT = Path("/hpc_data/weizwang@weizwang/frameworks/resources")
DEFAULT_TASK_SKILLS_DIR = FRAMEWORK_RESOURCES_ROOT / "mle-reimagined"
DEFAULT_EDA_SKILL_DIR = FRAMEWORK_RESOURCES_ROOT / "mlebench-skill-eda"
DEFAULT_ERROR_SKILL_FILE = FRAMEWORK_RESOURCES_ROOT / "mle_skill_error2" / "ml_failure_prevention_skill_v4.md"
DEFAULT_LOCAL_EDA_DATA_ROOT = Path("/hpc_data/ktian/superml/inference_codex_cot4/mlebench-lite-val")
DEFAULT_EARLY_EDA_ARCHIVE_ROOT = Path(
    os.environ.get("BSPM_EARLY_EDA_ARCHIVE_ROOT", str(FRAMEWORK_RESOURCES_ROOT / "earlyeda"))
)
DEFAULT_EARLY_EDA_BRANCHES: tuple[str, ...] = ()
SKILL_FILE_SUFFIXES = {".md", ".py", ".json", ".txt", ".yaml", ".yml"}
SKILL_SKIP_DIRS = {"__pycache__", ".git", ".ipynb_checkpoints"}

BACKEND_ID = (
    "codex_cli_bspm_v4_sharp_context_search"
)
BUDGET_MODES = {"sandbox"}
FRAMEWORK_VERSION = "v4"
SUBMIT_SELECTION_POLICY = "validation_best_only"
POST_CODE_MEMORY_SUMMARY_FILENAME = "post_code_memory_summary.md"
HIGH_LEVEL_MEMORY_FILENAME = "high_level_memory.md"
V33_LLM_POLICY = "context_first_pinned_contract"
V33_MAX_PROMPT_CHARS = {
    "coding": 25000,
    "debug": 25000,
    "improve": 25000,
    "draft": 25000,
    "planning": 24000,
    "early_eda": 24000,
    "early_eda_summary": 12000,
    "deep_eda": 30000,
    "deep_eda_summary": 14000,
    "static_gate_repair": 18000,
}
V33_MAX_NO_SOLUTION_RETRIES = 1
V4_MAX_STATIC_GATE_REPAIR_ATTEMPTS = 2
V33_SUPPORT_CALLS_DEFAULT = False
V33_TASK_MEMORY_PROMPT_LIMIT = 3600
V33_REFINEMENT_CONTEXT_LIMIT = 7000
V33_SKILL_CONTEXT_LIMITS = {
    "draft": 14000,
    "improve": 5200,
    "debug": 4200,
}
V34_PINNED_RUNTIME_LIMIT = 8200
V34_PINNED_MEMORY_LIMIT = 2200
V34_PINNED_EDA_LIMIT = 2200
V34_MIN_SKILL_CONTEXT_CHARS = 1800
V34_MIN_USER_TASK_CHARS = 2200
V34_SEMANTIC_PROMPT_TARGET_CHARS = 25000
V35_MAX_PROMPT_TOKENS = {
    "coding": 18000,
    "debug": 18000,
    "improve": 18000,
    "draft": 18000,
    "planning": 16000,
    "early_eda": 18000,
    "early_eda_summary": 12000,
    "deep_eda": 22000,
    "deep_eda_summary": 14000,
    "static_gate_repair": 14000,
}
V35_PINNED_EDA_SCHEMA_LIMIT = 3600
V35_FILTERED_USER_TASK_LIMIT_TOKENS = 6000
V35_SELECTED_SKILL_CARD_LIMIT_TOKENS = 2600
V35_STRUCTURED_MEMORY_FAILURE_EXCERPT_LIMIT = 500

EDA_SKILL_GUIDANCE = (
    "MANDATORY: use this full EDA skill only for the pre-plan local EDA code phase. The script must "
    "respect the read-only data boundary, perform lightweight discovery and bounded sampling only, "
    "avoid training or model iteration, and write eda_findings.md plus eda_findings.json in the current "
    "working directory. Later planning and coding phases receive eda_summary.md-derived pinned schema cards plus compact v4 portfolio context."
)

DRAFT_TASK_SKILL_GUARD = """Draft branch contract:
- Draft is a code-action only: it means build an independent candidate without prefilled incumbent code. It does not imply running EDA.
- Use the full task-specific Kaggle skill as the primary modeling recipe.
- Use EDA/local schema evidence only to verify files, columns, target, metric, resource risks, and submission format.
- Do not spend a draft round on EDA-only output or generic AutoML search.
- Implement the skill's highest-ROI stable baseline directly, with conservative resource bounds and trained downgrade paths.
- A draft seed must be a strong seed: build the task-appropriate main high-value family, but if the selected route is high-cost image/audio/transformer/sparse-text/tree-ensemble work, first execute a trained score-first path before optional heavy tiers. Prefer a sharply bounded supervised version of the selected primary route when it can finish; metadata, thumbnail/descriptors, sparse/frozen features, or shallow models are protection/fusion support, not replacements for a feasible stronger primary route.
- For the first no-score high-cost seed, Tier 1 is a fast evidence envelope, not a disguised full sweep. For sparse text or large tabular routes, use one capped pipeline with at most a small fold count/holdout, capped features/iterations/model count, and no broad sibling table before the first score. For image/audio routes, use metadata/descriptors/frozen features or one low-resolution single-fold primary model with one or two epochs and no TTA before heavier tiers. After Tier 1 has produced OOF/local evidence and test predictions, optional tiers may spend remaining time on the high-value recipe.
- For image/audio/media data discovery, use CSV-first schema inference and common train/test media directory names before any recursive/native directory traversal. Do not scan the whole DATA_DIR with `os.walk`, `os.scandir`, or recursive `rglob` before the first scored path; resolve only needed train/test IDs whenever possible.
- Use a budget ladder rather than all-or-nothing model piling: finish one competitive trained candidate, then optionally add extra views/models/blends as time-safe increments; shrink folds/features/iterations/epochs/model count before abandoning the main family.
- Do not put the only score-first/fallback path after all heavy candidates fail; it must be available before the first optional expensive tier starts.
- After the first trained candidate completes, keep a current-best submission candidate in memory. Before optional heavy tiers, either prove enough internal time remains or write that current-best `submission.csv` and exit normally before the sandbox wall.
- Before writing code, extract the routed skill's named recipe items into a coverage table. Implement the primary route plus enough cheap complementary items to make a real seed; defer only items that are expensive, unavailable, risky, or clearly reserved for later rounds.
- Preserve composite recipes when turning that table into code. If the skill presents compatible features, views, model heads, calibration, or blending pieces as one high-value route, at least one primary trained candidate must keep those pieces together in a single estimator/pipeline or OOF-selected composite. Do not replace a strong joint recipe with only isolated submodels.
- Preserve recipe fidelity before adding generic diversity. Implement the selected route's named primary model family, feature composition, validation pattern, and cheap blend/stack/calibration pieces before spending budget on substitute learner families not present in the routed skill.
- If the selected route is rich but cheap enough for multiple candidates, produce several faithful joint variants of the route's primary family before adding substitute learners from generic prior.
- Keep optional auxiliary feature blocks out of at least one pure core candidate. Add optional/support blocks as a separate validated variant or support model rather than forcing them into every primary candidate.
- When OOF predictions for several routed candidates already exist, blend/stack/calibrator is a cheap core step. With three or more base OOF candidates, compare both weighted blend and regularized stack/calibrator unless there is a hard implementation failure.
- If the first candidate table collapses to one useful model and cheap recipe items remain, the code should add the next bounded variant when time permits rather than declaring the seed complete.
- Make the seed reproducible: fixed seeds, deterministic folds/candidate order, and stdout diagnostics that record seeds, candidates, selected route, scores, and fallback activation.
- Do not mask data, label, target, or submission-unit parsing failures with untrained constant submissions."""

IMPROVE_BEST_GUARD = """Improve/frontier contract:
- Treat best_local_cv as the score anchor, but do not let a weak incumbent constrain the implementation.
- Follow the portfolio action: seed/expand must produce a materially distinct strong candidate; strengthen may tune the best candidate; blend must compare and combine existing candidates.
- Prefer high-ROI changes with visible validation evidence: feature family, model family, folds/seeds, calibration, postprocessing, TTA, or candidate selection.
- If score is stable and recent attempts do not improve, add diversity or a selector/blend before spending another round on narrow local tuning."""

V37_HARD_DIVERSITY_GUARD = """V4 search contract:
- A selected portfolio-expansion or strategy-replacement round must create a new primary method family unless the scheduler explicitly says every bounded family is exhausted.
- Initial search first collects two successful draft-origin seed families by default. A debug repair that makes a failed draft seed runnable inherits that draft seed identity and counts. Only after this breadth pool is ready should the scheduler optimize the best scored code; later independent drafts are used after real plateau or dead-route signals.
- Failed draft seeds do not count as successful breadth. A debug round must uniquely repair the latest failed seed; if it succeeds, it inherits that seed's effective method identity.
- Each failed seed has a small debug budget. When that budget is exhausted, replace the dead seed with a new draft rather than looping on repair.
- After the seed pool is ready, optimize the best frontier. If four scored non-debug validation rounds fail to beat the current best, open a new independent draft seed.
- Draft and EDA are decoupled: draft writes an independent code candidate; EDA runs only when the scheduler selects a separate information action.
- Parameter knobs such as min_df, C/gamma, pos_weight, folds, seeds, thresholds, and calibration are not method families by themselves; they must be attached to a concrete representation/model family.
- Blend, stacking, calibration, pseudo-labeling, transductive vocabulary, and EDA/model-prior diagnostics do not by themselves satisfy frontload structural diversity.
- If the recent frontier repeats a family or operator, the next non-debug round must replace that family or run a model-prior/EDA-prior route that is materially distinct.
- Blend/selector actions must be self-contained in the current round or based on inspected prior code and validation feedback; do not depend on reusable prediction files from earlier rounds.
- A timeout round must first ensure a trained score-first path exists or can finish under the current validation cap; only then retry the same high-value family as a smaller bounded tier. If repeated timeout produced no score, replace the timed-out family/operator with a cheap trained recovery seed rather than looping on the same expensive route.
- Runtime caps are quality constraints, not instructions to write weak probes. A bounded seed or repair should keep the strongest plausible task-appropriate family and reduce unsafe width/order before falling back to a low-upside route.
- For high-cost image/audio/transformer work, the score-first path must execute before optional heavy tiers. When a bounded supervised primary route can finish, use it as the score-first path; metadata, thumbnail/descriptors, sparse/frozen features, or shallow models are valid support paths when they train on labels, but should not displace a feasible stronger primary route.
- Timeout control is an anytime submission protocol: keep the best completed trained candidate submission-ready, run only statically bounded optional tiers, and exit normally before the external validation wall.
- Strong draft stability matters more than superficial diversity: a new draft may share a broad task modality with earlier seeds, but its concrete representation/model route, budget ladder, or candidate composition must be materially different and logged."""

ALTERNATIVE_GUARD = """Explore-alternative contract:
- The alternative must still be a high-priority candidate from the task-specific Kaggle skill.
- best_local_cv is a comparison anchor, not the implementation template.
- Avoid only the explicitly listed avoid method family; do not ban the best family globally for future improve-best rounds.
- Keep the implementation bounded and include a trained fallback or simpler model path when resources/dependencies fail."""

DEBUG_ERROR_GUARD = """Debug branch contract:
- Repair only the uniquely linked latest concrete failure unless the feedback proves the approach cannot run.
- Debug is not a new modeling route. If it succeeds, the runtime credits the repaired parent round's effective method identity.
- Classify and fix schema, dependency, timeout, OOM, submission, metric, data parsing, or output-format errors first.
- For timeout/OOM, first create or preserve a fast trained score-first path, then retry the same high-value route only as a smaller bounded tier; do not collapse to an unrelated weak probe unless the parent family cannot run at all.
- A timeout/OOM repair should preserve medal-oriented modeling whenever possible: downscale folds/features/epochs/resolution/model count and reorder work before abandoning the high-upside parent family.
- Do not delay the only trained fallback until after repeated heavy failures; the score-first path must run before any optional expensive retry tier.
- Once a repaired trained path completes, keep it submission-ready and prefer a normal exit over risking the external validation wall inside optional heavy retry work.
- If a timeout/OOM produced no score, especially with no useful run log, do not perform unbounded full-data decoding, hashing, embedding, or heavy pre-scans before the score-first path has already completed.
- If a media/data discovery failure occurs before schema inference, repair toward CSV-first and known train/test media directory lookup; avoid replacing one full DATA_DIR traversal with another `os.walk`, `os.scandir`, or recursive `rglob` scanner.
- If repeated timeout/OOM occurs before any scored validation, switch to score-first recovery: produce a small trained, schema-safe submission under tight caps; avoid full-resolution/full-data training, large ensembles, and TTA until a valid score exists, but keep a bounded version of the high-ROI supervised family when it can plausibly finish.
- For schema/data-parsing/output-format failures, repair the whole local failure class across sibling parsers, readers, and validators; do not only patch the single stack-frame line when the same pattern can recur immediately.
- When the failed parent route is high-cost/high-risk but failed quickly from code, schema, fold, dependency, or format errors, keep the high-upside route but first finish exactly one repaired bounded trained primary candidate. Do not run a broad candidate table, wide ensemble, stack, TTA, or several full-cost sibling variants before the repaired seed has at least one validation score.
- Do not use debug rounds to introduce a new model family or broad ensemble."""


@dataclass(frozen=True)
class BranchSpec:
    name: str
    title: str
    goal: str
    instructions: str


BRANCH_SPECS: tuple[BranchSpec, ...] = (
    BranchSpec(
        name="draft",
        title="Kaggle-Skill Draft",
        goal="Implement the task-specific Kaggle skill's highest-ROI stable recipe with correct schema, resources, and submission format.",
        instructions=(
            "Use the compact task-skill packet as the modeling anchor from the first round. Prioritize robust data loading, "
            "schema inference, metric alignment, bounded training, and trained downgrade paths rather than untrained emergency submissions."
        ),
    ),
    BranchSpec(
        name="debug",
        title="Debug Repair",
        goal="Fix the latest concrete failure with the smallest necessary code change.",
        instructions=(
            "Read the latest failed commit feedback first. Do not redesign the whole solution unless the failure proves "
            "the approach is impossible. Focus on schema, dependencies, timeout/OOM, submission, metric, data parsing, and output-format fixes. "
            "For parser/schema failures, apply the minimal generalized fix to sibling readers that share the same failure class. For repeated timeout/no-score before any validation score, prioritize a fast scored baseline over preserving the failed heavy route."
        ),
    ),
    BranchSpec(
        name="improve",
        title="Improve Score",
        goal="Improve the task portfolio with a high-density candidate, strengthening or diversifying the best known search frontier.",
        instructions=(
            "Use task skill, memory, failure ledger, EDA, and prior code as evidence. Default to a competitive in-round mini-portfolio "
            "with OOF/local validation and candidate comparison. Patch an incumbent only when the portfolio action "
            "is repair, audit, or bounded strengthening."
        ),
    ),
)

DEFAULT_WARMUP_BRANCHES = ("draft", "improve")
BRANCH_SPEC_BY_NAME = {spec.name: spec for spec in BRANCH_SPECS}
BRANCH_ALIASES = {
    "baseline": "draft",
    "repair": "debug",
    "feature": "improve",
    "model": "improve",
    "exploit": "improve",
}

INTENT_IMPROVE_BEST = "improve_best"
INTENT_EXPLORE_ALTERNATIVE = "explore_alternative"
INTENT_ABLATE_BEST = "ablate_best"
INTENT_REPAIR_FAILURE = "repair_failure"
INTENT_RESET_BASELINE = "reset_baseline"
INTENT_ENSEMBLE = "ensemble_portfolio"
INTENT_SUBMISSION_AUDIT = "submission_audit"
INTENT_TIMEOUT_SAFE = "timeout_safe_downgrade"
INTENT_STRATEGY_REPLACE = "strategy_replace"
INTENT_STAGNATION_BREAK = "stagnation_break"
INTENT_DEEP_EDA = "deep_eda_bottleneck"
INTENT_FRONTLOAD_DRAFT = "frontload_draft_distinct_seed"
INTENT_FRESH_DRAFT = "fresh_draft_distinct_seed"
INTENT_PORTFOLIO_SEED = "portfolio_seed_strong"
INTENT_PORTFOLIO_EXPAND = "portfolio_expand_diverse"
INTENT_PORTFOLIO_STRENGTHEN = "portfolio_strengthen_best"
INTENT_PORTFOLIO_BLEND = "portfolio_blend_select"
INTENT_SCORE_GAP_AUDIT = "score_gap_audit"
INTENT_PORTFOLIO_DIAGNOSE = "portfolio_diagnose"

STATE_BOOTSTRAP = "bootstrap"
STATE_DEBUG_REPAIR = "debug_repair"
STATE_TIMEOUT_TRAP = "timeout_trap"
STATE_FINAL_AUDIT = "final_audit"
STATE_STRATEGY_REPLACE = "strategy_replace"
STATE_LOCAL_PLATEAU = "local_plateau"
STATE_PORTFOLIO_CHECKPOINT = "portfolio_checkpoint"
STATE_EARLY_DIVERSIFY = "early_diversify"
STATE_EXPLOIT_BEST = "exploit_best"
STATE_DEEP_EDA = "deep_eda"
STATE_FRONTLOAD_DRAFT = "frontload_draft"
STATE_FRESH_DRAFT = "fresh_draft"
STATE_PORTFOLIO_SEED = "portfolio_seed"
STATE_PORTFOLIO_EXPAND = "portfolio_expand"
STATE_PORTFOLIO_STRENGTHEN = "portfolio_strengthen"
STATE_PORTFOLIO_BLEND = "portfolio_blend"
STATE_PORTFOLIO_DIAGNOSE = "portfolio_diagnose"
BRANCH_STATE_INITIAL_SEED = "initial_seed"
BRANCH_STATE_REQUIRED_SEED = "required_seed"
BRANCH_STATE_REPAIR_FAILURE = "repair_failure"
BRANCH_STATE_TIMEOUT_RECOVERY = "timeout_recovery"
BRANCH_STATE_FRONTIER_IMPROVE = "frontier_improve"
BRANCH_STATE_PLATEAU_NEW_SEED = "plateau_new_seed"
BRANCH_STATE_FINAL_AUDIT = "final_audit"

RUNTIME_PROFILE_STANDARD = "standard"
RUNTIME_PROFILE_NEW_SEED_SCORE_FIRST = "new_seed_score_first"
RUNTIME_PROFILE_DEBUG_REPAIR = "debug_repair"
RUNTIME_PROFILE_TIMEOUT_RECOVERY = "timeout_recovery"
RUNTIME_PROFILE_HIGH_RISK_PARENT = "high_risk_parent"
RUNTIME_PROFILE_FINAL_AUDIT = "final_audit"

V3_GRAPH_DIR = "graph"
V3_TOP_K_PORTFOLIO = 8
V3_STATIC_GATE_RETRIES = 1
V3_MIN_ROUND_TIMEOUT_SECONDS = 900
V4_HIGH_COST_DEEP_MEDIA_SCORE_FIRST_TIMEOUT_SECONDS = 10800
V4_HIGH_COST_SPARSE_TEXT_TIMEOUT_SECONDS = 7200
V4_EXTERNAL_TIMEOUT_POLICY = "profile_cap_with_remaining_sandbox"
V4_EXTERNAL_TIMEOUT_CAP_SECONDS = {
    "low": 3600,
    "general": 10800,
    "deep": V4_HIGH_COST_DEEP_MEDIA_SCORE_FIRST_TIMEOUT_SECONDS,
    "sparse": V4_HIGH_COST_SPARSE_TEXT_TIMEOUT_SECONDS,
}
V4_MATERIAL_SCORE_ABS_DELTA = 1e-6
V4_MATERIAL_SCORE_REL_DELTA = 1e-5
V4_SCORE_DIAGNOSIS_MATERIAL_ABS_DELTA = 1e-3
V4_SCORE_DIAGNOSIS_MATERIAL_REL_DELTA = 1e-3
V4_SCORE_DIAGNOSIS_LOCAL_GAP_ABS = 0.03
V3_FINAL_AUDIT_FRACTION = 0.15
V3_EXPLORATION_FRACTION = 0.30
V3_ENABLE_AFTER_BEST_EARLY_STOP = False
V31_TIMEOUT_TRAP_RECENT_LIMIT = 5
V31_TIMEOUT_TRAP_RECENT_THRESHOLD = 2
V31_STRATEGY_REPLACE_AFTER_BEST = 5
V31_LOCAL_PLATEAU_AFTER_BEST = 3
V31_STAGNATION_RECENT_LIMIT = 4
try:
    V4_SUBMIT_TIMEOUT_SECONDS = int(os.environ.get("BSPM_SUBMIT_TIMEOUT_SECONDS", "86400"))
except ValueError:
    V4_SUBMIT_TIMEOUT_SECONDS = 86400
V4_SUBMIT_TIMEOUT_SECONDS = max(60, V4_SUBMIT_TIMEOUT_SECONDS)
V33_DEEP_EDA_AFTER_BEST = 5
V33_DEEP_EDA_MIN_VALID_SUCCESSES = 3
V33_DEEP_EDA_COOLDOWN_ROUNDS = 4
V33_MAX_DEEP_EDA_RUNS = 1
V34_MEMORY_BANK_RECENT_ROUNDS = 12
V34_MEMORY_BANK_MAX_FAILURES = 24
V34_MEMORY_BANK_MAX_EDA_INSIGHTS = 12
LLM_TRANSIENT_INFRA_STOP_THRESHOLD = 3
CODEX_PHASE_TIMEOUT_SECONDS = {
    "early_eda": 1800,
    "deep_eda": 1800,
    "early_eda_summary": 600,
    "deep_eda_summary": 900,
    "coding": 3600,
    "debug": 3600,
    "improve": 3600,
    "draft": 3600,
    "static_gate_repair": 1800,
}
LLM_INFRA_FAILURE_STATUSES = {
    "llm_transient_infra",
    "llm_quota_exhausted",
    "llm_context_limit",
    "llm_cli_timeout",
    "llm_cli_error",
    "llm_unknown_error",
}
DUPLICATE_SOLUTION_STATUS = "duplicate_solution"
NON_DEBUG_NO_SCORE_STATUSES = {
    DUPLICATE_SOLUTION_STATUS,
    "uninformative_fallback",
    "constant_prediction_success",
    "no_solution",
    "static_gate_blocked",
    "agent_error",
}
PARENTLESS_NON_DEBUG_STATUSES = {
    "no_solution",
    "static_gate_blocked",
    "agent_error",
}
V35_NOVELTY_RECENT_LIMIT = 5
V35_NOVELTY_OPERATOR_REPEAT_THRESHOLD = 2
V35_NOVELTY_FAMILY_REPEAT_THRESHOLD = 3
V36_WEAK_START_SUCCESS_LIMIT = 2
V36_MIN_DIVERSE_PORTFOLIO_FAMILIES = 3
V36_STRONG_CANDIDATE_COUNT = 3
V36_EARLY_RISK_GATE_SUCCESS_LIMIT = 4
V37_MIN_DIVERSE_PORTFOLIO_FAMILIES = 3
V37_FRONTLOAD_DIVERSE_SUCCESS_LIMIT = 3
V37_FRONTLOAD_MAX_ATTEMPTS = 5
V37_FORCE_UNUSED_FAMILY_CANDIDATE_LIMIT = 6
V37_OPERATOR_REPEAT_HARD_LIMIT = 2
V37_FAMILY_REPEAT_HARD_LIMIT = 2
V37_MAX_STRENGTHEN_BEFORE_REPLACE = 2
V37_FRESH_DRAFT_AFTER_BEST = 5
V37_FRESH_DRAFT_MIN_VALID_SUCCESSES = V37_FRONTLOAD_DIVERSE_SUCCESS_LIMIT
V37_FRESH_DRAFT_COOLDOWN_ROUNDS = 5
V37_MAX_FRESH_DRAFT_RUNS = 2
V37_FRESH_DRAFT_MIN_REMAINING_BUDGET = 5400
V37_MODEL_PRIOR_OPERATOR_NAME = "model_prior_distinct_route"
V37_EDA_PRIOR_OPERATOR_NAME = "eda_prior_data_driven_route"
V37_STACK_OPERATOR_NAME = "cross_family_stack_or_rank_blend"
V38_REQUIRED_DRAFT_ORIGIN_SEEDS = 2
V4_FRONTLOAD_MIN_SEEDS_BEFORE_QUALITY_EXIT = 2
V4_FRONTLOAD_QUALITY_EXIT_REL_GAP = 0.003
V4_FRONTLOAD_QUALITY_EXIT_ABS_GAP = 0.005
V38_PLATEAU_SCORED_ROUNDS_BEFORE_NEW_DRAFT = 4
V38_MAX_DEBUG_REPAIRS_PER_SEED = 2
V38_MAX_FRESH_DRAFT_RUNS = V37_MAX_FRESH_DRAFT_RUNS
V37_CONTROL_METHOD_FAMILIES = frozenset({
    "portfolio_seed",
    "portfolio_strengthen",
    "portfolio_expand",
    "runtime_safety",
    "debug",
    "audit",
    "eda_diagnostics",
    "parameter_tuning",
})
V37_NONSTRUCTURAL_METHOD_FAMILIES = frozenset({
    "calibration_postprocess",
    "blend_ensemble",
    "stack_ensemble",
    "ensemble",
    "blend",
    "pseudo_label",
    "transductive_vocab",
    "image_preprocessing",
    "loss_reweighting",
    "ordinal_head",
    "model_prior_freeform",
    "eda_prior",
})
V37_FRONTLOAD_ATTEMPT_INTENTS = frozenset({
    INTENT_PORTFOLIO_SEED,
    INTENT_PORTFOLIO_EXPAND,
    INTENT_FRONTLOAD_DRAFT,
    INTENT_STRATEGY_REPLACE,
    INTENT_EXPLORE_ALTERNATIVE,
})
@dataclass(frozen=True)
class SearchOperator:
    """A concrete search action extracted from task skill or generated by policy."""

    name: str
    intent: str
    family: str
    description: str
    source: str
    cost: str = "medium"
    risk: str = "medium"


@dataclass(frozen=True)
class NoveltyPolicy:
    """Runtime search memory converted into operator-selection constraints."""

    avoid_operators: tuple[str, ...] = ()
    avoid_families: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    exhausted: bool = False


class CodexCliError(RuntimeError):
    """Structured Codex CLI infrastructure failure, never an ML/debug failure."""

    def __init__(
        self,
        message: str,
        *,
        failure_type: str,
        return_code: int | None,
        stderr: str,
        usage: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.return_code = return_code
        self.stderr = stderr
        self.usage = usage
