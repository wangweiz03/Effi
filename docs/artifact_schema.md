# BSPM Codex v4 Artifact Schema and Authority Map

This document defines the authority and retention boundary of current runtime artifacts. The primary distinction is between mutable current-round control and frozen post-round evidence.

## Authority Classes

- **Control snapshot**: mutable state used to execute the current round.
- **Historical evidence**: round-frozen records used for audit, memory, replay, and final selection.
- **Derived view**: reconstructible convenience output that cannot become an independent authority.
- **Trace**: detailed debugging evidence that is too large or unstable for routine scheduling.

## Current-Round Control

### `index/current_branch_decision.json`

Authority: current-round scheduling and runtime control only.

It contains:

- round, branch, state, and reason;
- runtime profile and strict score-first control;
- one non-recursive `parent_binding`;
- frozen `draft_prior_memory` for draft rounds;
- source policy and score feedback;
- remaining sandbox budget, one external validation timeout, `workload_plan_v1`, and scheduler diagnostics.

The framework computes `validation_timeout_seconds` before coding. It is the sole execution timeout authority and the external sandbox wall. The prompt exposes it read-only. Draft also receives a `3600s` soft workload-planning ceiling; that value is not an enforced timeout, runtime quota, requested budget, or effective budget.

`workload_plan_v1` records policy flags, the draft-only ceiling, and branch-routed historical evidence: reference identity and status, previous validation runtime and timeout, timeout saturation, and structured timeout status. Draft references the latest prior draft with actual runtime; debug and improve reference their bound parent. Non-draft decisions retain the schema with a null draft ceiling.

Later scheduling overwrites this file. It is not append-only history and must not be used to reconstruct earlier rounds.

The raw snapshot is excluded from `[CONTEXT SOURCE MAP]`. `runtime/text_context.py` projects selected fields into one `[ROUND DIRECTIVE]`, branch-exclusive parent or prior memory, compact score/history, and the read-only runtime block.

### Legacy `index/branch_decisions.jsonl`

The runtime no longer writes this file. Existing copies are legacy traces, not required inputs or current authority.

## Run-Level Historical Evidence

### `rounds_summary.json`

Authority: compact run history and final-selection summary.

`rounds_summary_compact_v1` records branch, frozen compact decision, status, score, validation summary, commit and artifact paths, actual sandbox runtime, memory references, and a short method summary. Root fields record task-level actual sandbox usage, branch summary, best round, best commit, and selection policy.

`graphic.png` is a derived search view. It renders validation and final-submit scores as separate fields. When a final-submit score exists, the node and header also show its `gold`, `silver`, `bronze`, or `none` medal classification using the task cutoffs in `frameworks/resources/medal_thres.md` and the configured metric direction. A missing submit score has no inferred medal.

The configured external timeout and actual sandbox runtime are separate facts. Remaining task budget is calculated from actual sandbox runtime, not from timeout caps.

Large code, raw Codex output, and complete sandbox logs remain in commit or trace artifacts.

### Detailed Round Result

Authority: the complete frozen result of the executed round.

The runner copies the decision read at round start into `result["branch_decision"]`. Later changes to the current snapshot cannot alter that lineage. Normal results are archived under `commits/<hash>/result.json`; failed non-commit results are archived under `failed_rounds/` where applicable.

### `config.json`

Authority: evaluator configuration snapshot for one run. Current defaults must still be checked against CLI definitions, runtime constants, and root scripts.

## EDA Artifacts

### `early_eda/round_*/eda_findings.md` and `deep_eda/round_*/eda_findings.md`

Authority: complete human-readable EDA evidence and the required coding handoff. PART 4 routes the freshest existing findings markdown across early and deep EDA rounds. Accepted context deep-EDA updates are appended to the task-local findings record, so the selected file can be newer than the original early-EDA generation time.

### `eda_findings.json`

Authority: structured companion to the findings markdown. It is optional during normal coding and should be read when exact fields or nested EDA records are needed.

### `eda_summary.md`

Authority: generated/archive compatibility view. It is not the normal coding source because it can duplicate the findings markdown and structured JSON. PART 4 does not route it when findings exist. It becomes a required legacy fallback only when an old archive has no `eda_findings.md`.

## Routed Context and Skill Artifacts

### `context_sources/sandbox_model_cache.txt`

Authority: immutable task-local copy of the repository-maintained ready-only model-cache inventory. Its canonical source is `runtime/sandbox_model_cache.txt`; normal evaluator runs copy the source unchanged and never discover or mutate cache state dynamically.

The file contains 539 Hugging Face repositories with configuration and complete weights and 109 complete Torch checkpoints. Missing, incomplete, snapshotless, weights-only, configuration-only, and `.partial` entries are omitted, so every published line is ready by inventory contract. PART 4 requires this path for draft and exposes it as optional for debug/improve. Codex must query relevant names or families with targeted `grep -i` or `grep -iE` commands and must not read the complete file into context. The file contains neither package inventory nor live GPU capability data and consumes no sandbox runtime.

### `context_sources/task_skill_source_*.md`

Authority: prompt-safe branch view of the configured external task skill. Standardized skills contain exactly six phase headings and are persisted with only the four sections routed to the current branch. The header records original path, SHA-256, branch, and whether phase scoping succeeded. Legacy schemas remain full-text and are explicitly marked unscoped.

### `context_sources/failure_prevention_skill_source_*.md`

Authority: prompt-safe copy of the general failure-prevention skill when the branch source policy requires it. It is not phase-trimmed by the task-skill router.

## Static Gate Artifacts

The static gate runs before sandbox validation. A hard block receives at most two in-place `static_gate_repair` attempts in the same round.

Each attempt:

- edits the current root `solution.py` directly;
- recomputes the complete contract from the new file;
- creates no new round, parent, commit, or branch decision;
- consumes no sandbox runtime, while wall time and tokens remain audit data.

Traces are:

- `traces/round_<n>_static_gate_repair_trace.json`;
- `traces/round_<n>_static_gate_repair_retry_1_trace.json`.

If either recheck becomes `pass` or `warn`, the same round enters sandbox validation. If both attempts remain blocked, the round ends as `static_gate_blocked`, with no score or commit, and is archived at `failed_rounds/round_<NNN>_static_gate_blocked/`.

The failed directory preserves the final code, contract feedback, readiness, post-code summary, round summary, and result. It enters round history, failure ledger, and memory, but never the graph portfolio or validation-best vault. The next round may bind it as `debug_parent` and enter `debug / repair_failure`.

`hard_format_safety_only` restricts blockers to concrete safety and submission violations such as missing `DATA_DIR` or `submission.csv`, known hardcoded paths, unsafe downloads, side-output files, untrained constant submissions, structurally detected hardcoded data cardinality, invalid constant regex contracts, and definite same-block use after deletion. Runtime style and boundedness remain warnings unless they prove a hard safety violation.

The static contract may warn about unbounded work, missing score-first structure, or unsafe submission finalization. Timeout allocation remains owned by the framework.

## Validation and Candidate Authority

### `index/best_validation_candidate.json`

Authority: validation-best eligible candidate according to metric direction.

It records commit, score, branch, lineage, code path, and timing. It is final-selection evidence, not a second declaration of current implementation base.

### `graph/nodes.jsonl`

Authority: append-only candidate ledger containing round and commit identity, validation and gate outcomes, effective lineage, artifact paths, compatibility fields, and memory references.

### `graph/portfolio.json`

Authority: scored, submission-eligible frontier used for best-candidate lookup and scheduling.

Eligible candidates must have a validation score and pass static and quality gates. Failed, blocked, unscored, or fallback-dominated candidates do not enter the submit frontier.

### Branch Summaries, Refs, and Tags

Authority: lightweight navigation and branch accounting only. They cannot replace frozen results or validation-best selection.

## Post-Round Memory

### `memory_bank/cards/round_<n>_<commit>.md`

Authority: human-readable method and result record for one completed round.

Hard fields include round, branch state, commit, status, score, metric direction, actual sandbox runtime, risk tags, and artifact paths. Soft fields describe the implemented method, observed behavior, reuse signal, and risk.

Successful scored cards keep `Result Signal` compact and omit verbose diagnostics. Failed cards retain diagnostics useful for repair. Cards are post-round evidence and never control the round that produced them.

### `memory_bank/card_index.jsonl`

Authority: compact machine-readable index of memory cards and routing evidence.

Rows include branch state and reason, status, score, metric-aligned deltas, method family, risk and cost, parent references, and artifact paths. Draft comparison fields do not replace parent-delta semantics.

### `memory_bank/diffs/*.md`

Authority: method change plus metric-aligned result comparison.

`method_diff_v2` compares a parent and current round. `draft_method_diff_v1` compares a newly scored draft with the previous validation-best draft and preserves both identities, scores, complete method summaries, and component differences. A first or unscored draft has no draft diff. Equal-score diffs remain evidence but do not create directional high-level experience.

### `memory_bank/high_level_memory.md`

Authority: derived task-level experience rebuilt deterministically from diffs; schema `high_level_memory_v2`.

It contains:

- positive parent improvements and better-draft advantages;
- negative parent regressions;
- scored debug recoveries from explicit failed parents.

It describes observed associations only. A timeout with no stage evidence cannot justify a claim that a particular method change caused the failure.

### Other Memory Files

- `memory_bank/rounds.jsonl`: derived compatibility view.
- `memory_bank/failure_ledger.jsonl`: compact failure navigation, not a replacement for feedback.
- `memory_bank/eda_insights.jsonl`: accepted early and bounded deep-EDA facts.
- `memory_bank/operator_outcomes.json`: deprecated derived aggregation; no longer written.
- `memory_bank/prompt_context.md`: deprecated aggregate; no longer generated or routed into PART 4.

## Commit Artifacts

### `commits/<hash>/solution.py`

Authority: code generated and validated for the committed round.

### `commits/<hash>/validation_feedback.txt`

Authority: sandbox validation feedback for that commit.

### `commits/<hash>/submit_feedback.txt`

Authority: final submission-attempt feedback when present.

### `commits/<hash>/result.json`

Authority: detailed frozen round result and actual branch decision.

### `commits/<hash>/round_summary.json` and `.md`

Authority: commit-local method and outcome summary. Cross-round selection uses run-level `rounds_summary.json`.

### `commits/<hash>/context_readiness.md`

Authority: pre-code evidence-reading record and implementation plan.

It records inspected PART 4 paths, branch/state, actual implementation base and prefill status, score response, data contract, route, validation design, fallback, and failure traps. It does not participate in external timeout selection. The generic readiness schema belongs only to PART 1, while source paths belong only to PART 4.

Draft readiness additionally contains these ordinary planning fields derived from the decision and the agent's route estimate:

```text
draft_workload_ceiling_seconds: 3600
expected_complete_path_seconds: <positive estimate>
runtime_estimate_basis: <work-unit estimate and any valid history>
dominant_cost_units: <bounded expensive units>
complete_workload_product: <full multiplicative workload>
within_ceiling: yes
why_no_further_expansion: <why more work is not justified>
```

`expected_complete_path_seconds` is an expected runtime, not a target; a route expected to finish in a few minutes must not expand to consume the hour. `complete_workload_product` covers the entire route, including preprocessing, candidates, folds, epochs or iterations, validation, test inference, TTA, and optional stages as applicable.

Historical runtime evidence inside `runtime_estimate_basis` must identify completed same-task rounds and use actual sandbox runtime. Comparable successful routes are preferred. A timeout is a lower bound only. A failure before the dominant stage is not an end-to-end runtime estimate. When history is not comparable or absent, the basis must say so and reason from explicit work units. Debug and improve do not emit the draft readiness fields; their PART 3 evidence remains parent-relative.

### `commits/<hash>/post_code_memory_summary.md`

Authority: Codex description of the implementation that was actually generated. Memory writers use it for method portrait, core components, reuse/risk, and diff action/reason.

### `failed_rounds/<name>/`

Authority: evidence for rounds that did not enter normal commits. These artifacts are excluded from the eligible portfolio.

## Prompt and Trace Artifacts

### `traces/round_<n>_trace.json`

Authority: detailed Codex invocation trace, including prompt, response, stderr, command, duration, and usage estimate. It supports audit, not routine scheduling.

### `context_sources/coding_prompt_after_pack.json`

Authority: packed prompt composition and critical marker coverage. `critical_marker_failures` must be empty.

### `context_sources/coding_prompt_after_pack.md`

Derived human-readable packed prompt. Machine checks should prefer the JSON artifact.

### PART 1 Contract

The `v54_draft_workload_ceiling` pack contains one compact PART 1 with system instructions, deterministic sandbox facts, the context-first readiness and post-code-memory schema, and the output contract. It contains no branch guard body, routed task-skill body, or duplicate runtime-hardening block. Branch actions are projected only in PART 3 and routed skill paths only in PART 4.

When PART 4 marks the failure-prevention skill as required, the context-first protocol tells Codex to select a concrete route, review the complete skill against that route, and record only applicable risks and code actions in `context_readiness.md`. The framework does not project selected failure-skill chapters. There is no separate sandbox preflight artifact, runtime state, or solution-local timer; the static gate continues directly to full validation.

`coding_prompt_after_pack.json` records `branch_context_routing.inlined=false`. It no longer emits `selected_skill_filter` or `section_chars/section_tokens.branch_inline_guards`. Representative prompt regression tests cap the complete PART 1 at 2,200 tokens while checking the four benchmark API compatibility facts and the static safety contract. See `docs/coding_prompt_part1_contract.md`.

### PART 3 Contract

`part3_compact_v3` contains:

- one `[ROUND DIRECTIVE]`;
- branch-exclusive `[PARENT MEMORY CARD]` or `[PRIOR DRAFT MEMORY]`;
- bounded `[SCORE CONTEXT]` and `[ROUND HISTORY]`;
- draft-only `[DRAFT WORKLOAD CEILING]` or parent-relative `[OBSERVED RUNTIME EVIDENCE]` when available;
- one `[EXTERNAL VALIDATION TIMEOUT]` block with remaining sandbox runtime and the read-only external validation timeout;
- no raw current-decision path, recursive parent, full best candidate, complete portfolio, or neutral operator placeholder.

PART 4 is the sole path list. `context_sources/sandbox_model_cache.txt` is mandatory for draft and optional for debug/improve; its prompt instruction requires targeted case-insensitive `grep` lookup without full-file reading. Existing required skill paths are bold; missing required skills remain explicit. High-level memory is required for normal draft/improve only after its derived file exists, optional for debug, and suppressed for static repair.

Parent and prior summaries preserve the complete card `method_summary`. Draft prior volume is bounded by selecting at most four representative cards, not by truncating their text.

For draft only, `[DRAFT WORKLOAD CEILING]` supplies `draft_workload_ceiling_seconds: 3600` and the context-first protocol requires the readiness planning fields. The external block remains the hard execution wall. `3600s` is a planning ceiling rather than a quota; the `test-lite` calibration reports `92.6%` of audited completed draft validations within that envelope. Non-draft directives retain parent-relative runtime evidence without inheriting the draft ceiling.

## Failure Taxonomy

Failure taxonomy persists `primary`, `all`, `evidence`, and `source`. Timeout routing prefers structured external timeout status and explicit runtime events. Configuration identifiers such as `validation_timeout_seconds` and heartbeat names are not evidence.

Explicit solution events should cover common forms including `TimeoutError`, `timed out`, `deadline_guard`, and `BudgetExhausted`. Generic tokens such as `inf`, `dtype`, `csv`, or `json` must not classify a failure without terminal-exception context. A zero-output sandbox timeout remains externally observed timeout evidence but must not create unsupported method-level causality.

## Lineage

Raw branch state explains why a round was scheduled:

- branch;
- branch state and reason;
- runtime profile;
- parent binding.

Effective lineage explains how a result is categorized after debug inheritance:

- effective branch and intent;
- effective method family;
- effective lineage seed identity.

Reports must state which perspective they use.

## Minimum Consistency Checks

Artifact checks should verify:

1. every completed round retains its frozen decision in detailed and compact results;
2. no checker depends on legacy `branch_decisions.jsonl`;
3. the current decision is treated only as a mutable snapshot;
4. rounds summary, best vault, and portfolio agree with metric direction and eligibility;
5. every card-index row resolves to its card and referenced round artifacts;
6. blocked and quality-gated rounds do not enter the eligible frontier;
7. the packed prompt has one directive and one read-only external timeout block;
8. wall time, sandbox runtime, timeout cap, and token estimate remain distinct;
9. debug/improve parent, implementation base, prefill source, and PART 4 baseline share one identity;
10. draft has no implementation parent and only bounded frozen prior memory;
11. readiness remains evidence-only for external-timeout purposes, while the frozen decision records `workload_plan_v1` and draft readiness records its planning fields;
12. the frozen external timeout remains authoritative after code generation;
13. every task-local model-cache inventory matches the repository source and follows draft-required, debug/improve-optional PART 4 routing;
14. solution output is a schema-valid atomically written `submission.csv`;
15. timeout taxonomy preserves evidence without inferring unsupported method causality;
16. the draft `3600s` planning ceiling remains distinct from the external hard cap and creates no internal timer or preflight.

### `graphic.png`

Derived human-only search visualization rebuilt from persistent evidence. It never participates in scheduling or prompt construction. Each round node shows validation and final-submit scores separately; the header reports the number of scored submissions and the best submit score in the task metric direction. When append-only graph or memory rows disagree with the atomically rewritten `rounds_summary.json`, the compact summary is the final visualization source so recovered validation or submit results appear on the next render.
