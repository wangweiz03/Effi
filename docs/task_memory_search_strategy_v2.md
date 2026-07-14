# Task Memory and Search Strategy v2

## Scope

This document defines the active within-task search and memory contract. The scheduler chooses a bounded control branch, Codex chooses the concrete modeling method from local evidence, sandbox validation supplies the optimization signal, and post-round memory preserves reusable evidence.

The runtime does not use vector retrieval, MCTS, beam search, or scheduler-selected modeling operators.

## Branch-Only Search

`choose_branch_state_for_round()` consumes the completed-round prefix, eligible portfolio, metric direction, and remaining sandbox budget. It selects one branch:

- `draft`: create an independent strong seed;
- `debug`: repair one concrete failed implementation;
- `improve`: advance the scored frontier from an eligible anchor.

Active states are:

- `initial_seed`;
- `required_seed`;
- `repair_failure`;
- `timeout_recovery`;
- `frontier_improve`;
- `plateau_new_seed`;
- `final_audit`.

The scheduler controls state, parent identity, source policy, score response, runtime profile, and the external validation timeout. It does not select a model, feature family, or preprocessing recipe.

## Parent Semantics

### Draft

Draft has no implementation parent. It produces a self-contained solution without historical code prefill. Frozen summaries may prevent repetition, but no historical implementation becomes its baseline.

### Debug

Debug binds the latest failed generated implementation and exposes its card, code, and feedback. A successful repair inherits the failed seed's effective lineage and does not create a new independent seed.

### Improve

Improve binds the highest-scoring eligible validation candidate at round start. Its card, code, and feedback must agree with the prefilled implementation. Final audit uses the same validation-best binding with a lower-risk objective.

### Single Binding

Current v3 decisions use one `parent_binding` as score anchor, implementation base, and default diff parent. Prompt-facing parent memory is one level deep and contains only round, score, and complete `Method Portrait.method_summary`. Artifact paths are routed separately through PART 4.

## Plateau Behavior

Plateau exploration is bounded:

1. four scored non-debug rounds without a material new best trigger a new seed;
2. the response is `draft / plateau_new_seed`, not an incumbent patch;
3. a scored plateau draft resets the stagnation window;
4. at least five rounds must pass before another plateau draft;
5. one run may create at most two plateau drafts;
6. generated-code repair and final-audit rules retain higher priority.

An unscored plateau draft does not reset stagnation. Its concrete failure is handled by the normal debug rule.

## Control and Evidence Planes

`index/current_branch_decision.json` is the mutable current-round control snapshot. The runner freezes a copy into the round result before generation and validation. Later scheduling may overwrite the current snapshot but cannot alter historical lineage.

Historical authority lives in:

- `commits/<hash>/result.json` and failed-round results;
- compact records in `rounds_summary.json`;
- `memory_bank/card_index.jsonl`;
- `memory_bank/cards/*.md` and `memory_bank/diffs/*.md`;
- graph nodes and the eligible portfolio.

The runtime no longer writes `index/branch_decisions.jsonl`. Existing files are legacy evidence only.

## PART 3 Projection

The prompt-facing projection is bounded and contains:

- `[ROUND DIRECTIVE]`;
- exactly one of `[PARENT MEMORY CARD]` and `[PRIOR DRAFT MEMORY]`;
- optional `[SCORE CONTEXT]`;
- `[ROUND HISTORY]`;
- `[EXTERNAL VALIDATION TIMEOUT]` with one read-only external validation cap.

Full validation-best objects, recursive ancestry, full portfolio state, neutral compatibility operators, and repeated previous-best records do not enter PART 3. Static rules belong to PART 1 and local paths belong to PART 4.

## Memory Cards and Diffs

Each completed round produces at most one authoritative memory card. A card records identity, branch state, status, score, metric direction, sandbox runtime, risk, artifacts, implemented method, observed validation behavior, and reuse or avoidance signals.

Successful cards keep their result signal compact. Failed cards retain diagnostics needed for repair. `post_code_memory_summary.md` describes the implementation that actually exists; `context_readiness.md` remains pre-code planning evidence.

`memory_bank/card_index.jsonl` is the compact machine index. Parent-linked rounds may produce a parent diff. A scored new draft may produce a `draft_method_diff_v1` against the previous validation-best draft.

`memory_bank/high_level_memory.md` is deterministically rebuilt from diffs and has three sections:

- `Positive Experiences`: improved parent patches and the advantage of a better-scoring draft over a worse draft;
- `Negative Experiences`: scored parent patches that regressed;
- `Debug Experiences`: failed-parent to scored-success repair transitions.

Experience text must describe observed association, not unsupported causality. In particular, a zero-output external timeout cannot prove that a specific method change caused the timeout.

## Draft Prior Memory

The scheduler freezes at most four representative draft cards into `draft_prior_memory_v2`. Selection covers validation-best, recent, failed, and method-diverse drafts.

Each prompt record contains only:

- round;
- score;
- the complete memory-card `method_summary`.

The summary is not character-truncated. The four-card limit bounds total size. Prior memory contains no code path, candidate object, recursive ancestry, or framework-selected modeling advice. It transfers experience without creating code inheritance.

## Source Policy

- Draft requires task skill, failure-prevention skill, and EDA summary. High-level memory becomes required once the derived file exists. Historical code remains unavailable as a baseline.
- Improve requires the anchor card, code, feedback, task skill, EDA summary, and existing high-level memory. Other differentiated evidence may be optional.
- Debug requires the failed parent card, code, feedback, failure-prevention skill, and EDA summary. Broader history is optional and subordinate to the concrete repair.

Static-gate repair suppresses high-level memory for every branch. Draft static repair also suppresses prior and round history and operates only on the current root `solution.py`, readiness, post-code summary, and current blockers.

## EDA Evidence

Round zero normally receives early EDA. Later deep EDA is allowed only when a concrete ambiguity can change the implementation. It must be bounded and read-only and must record accepted facts in the readiness deep-EDA JSON contract.

Deep EDA does not train models, run validation, decode an unbounded media tree, or create reusable prediction artifacts.

## Score and Selection Semantics

Scores are compared according to `higher_is_better`. Prompt score context includes only latest, incumbent, aligned deltas, material tolerance, concrete issues, and required response.

Final selection uses validation score and submission eligibility. It does not use newest branch head, newest memory card, or nominal method family.

## External Validation Timeout

All task budget accounting uses actual sandbox runtime. Before coding, the framework takes the smaller of remaining sandbox runtime and a generous workload cap. Method-neutral branch scheduling uses `10800s`; concrete low-cost and sparse callers may use `3600s` and `7200s` respectively. Historical runtimes and branch state do not shrink the wall.

PART 3 displays the timeout as read-only context. Readiness supplies evidence and implementation intent without changing the framework decision.

The solution must remain statically bounded. It should complete a competitive trained path, retain the best complete predictions, skip doubtful optional work, write `submission.csv` atomically, and exit normally before the external sandbox wall whenever possible.

## Failure Routing

`timeout_recovery` requires an exact sandbox timeout or an explicit runtime exhaustion event. Timeout configuration identifiers and incidental log words are not evidence. Ordinary code failures route to `repair_failure`.

Failure evidence must preserve whether a timeout was observed by solution code or only by the external sandbox. Method memory must not infer a specific cause from a zero-output timeout.

## Invariants

1. Current control and historical evidence use different files and lifecycles.
2. Every executed round retains its frozen decision.
3. The scheduler selects control actions, not concrete models.
4. Memory describes implemented work and observed outcomes.
5. Plateau exploration has reset, cooldown, and run-level caps.
6. Debug always binds a concrete failed result.
7. Final selection follows metric direction and eligibility.
8. Parent, implementation base, prefill source, and baseline path share one commit identity.
9. Draft prior memory transfers experience without code inheritance.
10. Static rules, dynamic control, and source paths each have one prompt authority.
11. High-level memory is reconstructible from diffs and is not a parent selector.
12. Runtime execution has one framework-owned external timeout and is charged by actual sandbox runtime.

## Known Limits

- Memory retrieval is deterministic path-based selection rather than semantic retrieval.
- Improve remains centered on validation best.
- Neutral lineage compatibility fields still add schema surface.
- Legacy unreachable operator-selection code and ignored branch-strategy CLI options remain for compatibility.
- Runtime bootstrap namespace injection obscures module dependency isolation.
- Trace and detailed result artifacts still duplicate large payloads.
- Full evaluator smoke tests require external sandbox and inference services.
