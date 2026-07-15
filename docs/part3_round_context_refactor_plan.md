# PART 3 Current-Round Context Refactor

## Status

The compact PART 3 design is implemented as `part3_compact_v3`. It replaces the former recursive round state, duplicated best-candidate objects, compatibility operator placeholders, and repeated runtime directives.

The refactor changes only the prompt-facing current-round projection and the parent contract. Historical run directories remain readable and are not rewritten.

## Audit Baseline

The original audit covered 22 packed coding prompts under `test-lite/*/context_sources/coding_prompt_after_pack.md`:

- PART 3 used 74,938 tokens, or 33.18% of the complete prompts;
- the median task used 3,188 PART 3 tokens;
- the old pinned runtime block used 74.7% of PART 3 tokens;
- recursive improve parents and draft portfolio objects used 42.5%;
- most prompts duplicated previous-best and validation-best identities;
- neutral `agent_selected_after_context` and compatibility fields added no modeling information;
- final-audit examples could disagree about directive parent, validation best, and actual prefill.

The core problem was not length alone. Current-round authority was obscured by repeated, recursive, and compatibility-only data.

## Four-Part Authority Boundary

The coding prompt has four fixed responsibilities:

1. PART 1 defines static execution, sandbox, readiness, and output rules.
2. PART 2 contains the task description and fixed task constraints.
3. PART 3 projects already-decided current-round metadata and bounded memory.
4. PART 4 is the only list of local must-read and optional paths.

PART 3 does not repeat static runtime policy or expose raw scheduler JSON. `[ROUND DIRECTIVE]` is the sole prompt-facing authority for current branch behavior and its branch-specific execution guard. PART 1 contains no branch guard or routed skill body; PART 4 exposes the branch-routed source paths.

## Current Structure

```text
# PART 3 - CURRENT ROUND ITERATION STATE

## [ROUND DIRECTIVE]
round_index, branch, state, reason, runtime_profile,
strict_score_first_required, metric_direction, action,

## [PARENT MEMORY CARD]          # debug/improve only
round, score, complete Method Portrait.method_summary

## [PRIOR DRAFT MEMORY]          # draft only
up to four frozen round/score/complete method_summary records

## [SCORE CONTEXT]               # only when feedback exists
latest, incumbent, deltas, material issues, required response

## [ROUND HISTORY]
bounded round/branch/state/status/score/runtime/saturation/family/commit overview

## [DRAFT WORKLOAD CEILING]      # draft only
soft ceiling, prior-draft runtime evidence, non-quota policy

## [OBSERVED RUNTIME EVIDENCE]   # non-draft when parent evidence exists
bound-parent runtime, timeout, saturation, evidence limits

## [EXTERNAL VALIDATION TIMEOUT]
remaining sandbox runtime and one read-only external validation cap
```

`runtime/prompt_pack.py` records the `v54_draft_workload_ceiling` packing schema, section token counts, and critical marker coverage. `critical_marker_failures` must be empty.

## Parent Rules

Every current decision has one non-recursive `parent_binding`:

- `draft`: role `none`; no prefill and no parent card;
- `debug`: the latest concrete failed implementation as `debug_parent`;
- `improve`: the current validation-best eligible implementation;
- `final_audit`: the same validation-best rule as other improve states.

The binding may persist role, round, commit, status, score, method family, and artifact paths. Debug may also retain failure and seed identity. The prompt body shows only round, score, and the complete memory-card `method_summary`; paths appear only in PART 4.

Prefill must resolve from the same binding. A v3 decision never falls back to a different best-vault or legacy anchor identity.

## Draft Prior Memory

Draft prior memory transfers experience without transferring code. The scheduler builds and freezes `draft_prior_memory_v2` from the completed-round prefix and card index.

The projection contains:

- an evidence cutoff round;
- at most four deterministic representative draft cards;
- each card's round, score, and complete `Method Portrait.method_summary`;
- an omitted count.

Selection covers validation-best draft, recent draft, failed draft, and method-signature diversity before filling remaining slots. Selected summaries are never character-truncated. Size is controlled only by the four-card limit.

Draft prior memory is not a parent, does not expose code, does not prescribe a method, and does not create another long-term card category.

## Score and History

`[SCORE CONTEXT]` includes only the latest result, incumbent, necessary aligned deltas, material tolerance, concrete issues, and required response. Debug prioritizes failure repair; final audit prioritizes reliability.

`[ROUND HISTORY]` is a bounded navigation table over prior rounds. It prioritizes the first round, recent rounds, parent, best transitions, failures, and branch/state transitions. It does not replace cards, feedback, or source code.

## External Validation Timeout

The framework takes the smaller of remaining sandbox runtime and a generous workload hard cap before coding. Method-neutral branch scheduling uses `10800s`; concrete low-cost and sparse callers may use `3600s` and `7200s`. Historical runtimes and branch state do not shrink the wall. `[EXTERNAL VALIDATION TIMEOUT]` displays only the resulting cap and remaining sandbox runtime as read-only execution context.

The frozen branch decision carries `workload_plan_v1`; `[DRAFT WORKLOAD CEILING]` separately supplies `draft_workload_ceiling_seconds: 3600` and requires ordinary readiness planning fields. This is a soft ceiling on the planned complete workload, not an execution timeout or quota. Expected runtime can be only a few minutes and must not be expanded to fill the hour. The old `test-lite` calibration reports `92.6%` of audited completed draft validations within this envelope.

The required draft plan fields are `draft_workload_ceiling_seconds`, `expected_complete_path_seconds`, `runtime_estimate_basis`, `dominant_cost_units`, `complete_workload_product`, `within_ceiling: yes`, and `why_no_further_expansion`. Historical basis uses completed same-task actual sandbox runtime: comparable successes are strongest, timeouts are lower bounds, and failures before dominant work are not end-to-end estimates.

Debug and improve keep `workload_plan_v1` with a null draft ceiling and bound-parent runtime evidence. They do not emit the draft-only prompt or readiness fields. Debug reduces timeout/OOM work relative to the failed parent; improve bounds its change from validation-best parent evidence.

Only actual sandbox runtime is charged against the task budget. The solution remains responsible for bounded work, a competitive score-first route, and an atomic `submission.csv` before optional heavy work risks the external wall.

The design does not restore solution-local timers, remaining-time polls, budget exceptions, or a separate sandbox preflight.

## Source Routing

PART 4 receives persisted skill sources through pinned retrieval paths and then applies branch-specific `must` and `optional` policy. Existing required task-skill and failure-prevention paths are bold. Missing required sources remain explicit.

Normal draft and improve rounds read `memory_bank/high_level_memory.md` once that derived file exists. Debug may read it optionally. Static-gate repair suppresses high-level history so a safety repair cannot drift into route reselection. Draft static repair additionally suppresses prior memory and round history and uses only the current solution, readiness, and post-code summary as its implementation evidence.

## Implementation Map

- `runtime/branch_policy.py`: branch-only scheduling, parent binding, validation-best selection, frozen draft prior, and external timeout allocation.
- `runtime/skills.py`: binding-based prefill and persisted skill routing.
- `runtime/text_context.py`: compact PART 3 projection and branch-exclusive parent/prior routing.
- `runtime/prompt_pack.py`: four-part assembly, marker checks, and token accounting.
- `runtime/runner.py`: frozen decision use, validation execution, and artifact persistence.
- `runtime/validation.py`: static contract, sandbox feedback, taxonomy, and quality checks.
- `runtime/memory_cards.py` and `runtime/portfolio.py`: one-level parent evidence and compatibility reads.

## Acceptance Criteria

The implementation is complete when:

1. branch, state, reason, and action have one prompt authority;
2. draft has no parent or prefill but can see bounded frozen draft summaries;
3. debug binds failed code and improve/final-audit bind validation-best eligible code;
4. parent text is non-recursive and all paths are exclusive to PART 4;
5. PART 3 distinguishes one read-only external hard timeout from the draft-only `3600s` soft workload ceiling;
6. the frozen decision contains `workload_plan_v1`, while draft readiness contains ordinary implementation-planning fields rather than budget negotiation;
7. new prompts contain no legacy round-state, full best-candidate, recursive portfolio, or neutral operator block;
8. historical artifacts remain readable without extending deprecated schema;
9. debug and improve retain parent-relative bounded-work behavior without inheriting a draft quota;
10. no internal timer or separate sandbox preflight is introduced.

The historical projection replay reduced median PART 3 size to 924 tokens and total size to 21,780 tokens, approximately 70.9% below the audited baseline. External sandbox and inference services are still required for full evaluator smoke runs.
