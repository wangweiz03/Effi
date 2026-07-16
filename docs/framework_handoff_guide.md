# BSPM Codex v4 Framework Handoff Guide

## Purpose

This repository implements a multi-round Codex runtime for MLE-Bench and Kaggle-style tasks. Each task is a compact experiment loop: select a control branch, assemble local evidence, generate `solution.py`, validate it in a sandbox, and persist round evidence for later search and final submission.

The runtime has three cooperating planes:

```text
control: runtime/branch_policy.py
prompt:  runtime/skills.py, runtime/eda.py, runtime/text_context.py, runtime/prompt_pack.py
evidence: runtime/runner.py, runtime/validation.py, runtime/memory_cards.py, runtime/portfolio.py
```

`evaluate_codex.py` is the CLI entrypoint and `runtime/runner.py` owns the execution loop. `docs/` describes the active design; `docs/deprecated/` is historical reference only.

## Repository Map

- `evaluate_codex.py`: thin CLI entrypoint and compatibility exports.
- `run_selected_tasks.sh`: task selection and evaluator launcher.
- `run_subset_priority_9.sh`: fixed priority subset launcher.
- `prompts.py`: shared execution and modeling instructions.
- `runtime/constants.py`: states, runtime configuration, thresholds, and default paths.
- `runtime/runner.py`: concurrency, rounds, validation, summaries, and final submit.
- `runtime/branch_policy.py`: branch-only scheduling, parent choice, score response, and timeout allocation.
- `runtime/skills.py`: task-skill and failure-prevention source routing.
- `runtime/eda.py`: early EDA generation or archive reuse and EDA evidence.
- `runtime/text_context.py`, `runtime/prompt_pack.py`: source map, compact PART 3, assembly, and packing.
- `runtime/codex_cli.py`: Codex subprocess execution and traces.
- `runtime/validation.py`: static contract, sandbox feedback, taxonomy, and quality checks.
- `runtime/memory_cards.py`: cards, method diffs, card index, and high-level memory.
- `runtime/memory_store.py`, `runtime/portfolio.py`: repository state and candidate frontier.
- `runtime/search_graph.py`: human-only visualization from persistent evidence.
- `runtime/sandbox_model_cache.txt`: fixed ready-only model-cache inventory copied into each task context.
- `real_run_examples/`: reference outputs, not runtime source.

Full runs require external skill directories, datasets, inference services, and sandbox infrastructure.

## Round Lifecycle

A typical run is:

```bash
./run_selected_tasks.sh leaf-classification
```

`run_selected_tasks.sh` defaults to
`/hpc_data/weizwang@weizwang/frameworks/resources/automl_parquet_test_all_0406/eval.parquet`.
`DATA_FILE` or `--data-file` may override it explicitly. The script writes only the selected task rows to a temporary Parquet and records that temporary path in the run's `config.json`; the source path remains visible in the launcher output.

The default Parquet includes two post-generation task-description corrections. For
`ranzcr-clip-catheter-line-classification`, the submission contract exposes only the
nine columns present in `sample_submission.csv`; `CVC - Normal` and
`Swan Ganz Catheter Present` are identified only as train-side auxiliary labels. For
`siim-isic-melanoma-classification`, the non-operational `Timeline`, `Prizes`,
`Acknowledgements`, and `SIIM AI Conference` sections are removed while the problem,
metric, submission, citation, and dataset sections remain intact. The adjacent
`generation_audit.*` and `read_parquet.txt` files are original generation snapshots,
not runtime inputs; inspect `eval.parquet` itself when auditing these corrections.

The task Parquet's `metadata.task_description` is the source of PART 2 `[TASK DESCRIPTION]`. During coding prompt packing, the framework removes the duplicated `[METADATA]` block, bulky `[DATA DESCRIPTION]`, embedded benchmark system block, legacy chat-output user block, and obsolete refinement-routing text. It retains one complete `[TASK DESCRIPTION]`; operational metadata needed by the runtime remains in the in-memory task record and selected facts are projected into pinned runtime sections.

For each task, the runner repeats:

1. calculate wall-time audit data and remaining actual sandbox budget;
2. choose a branch from the completed-round prefix;
3. write `index/current_branch_decision.json`;
4. read and freeze that snapshot at round start;
5. assemble task rules, current-round context, and routed sources;
6. run or reuse early EDA when selected;
7. ask Codex for `context_readiness.md`, `solution.py`, and `post_code_memory_summary.md`;
8. inspect the static contract and perform bounded in-place repair if required;
9. run sandbox validation under the framework-owned external timeout;
10. persist the frozen result, commit or failed-round artifacts, memory, graph, portfolio, and compact summary;
11. select the final candidate by metric direction and eligibility.

The result retains the decision actually used to generate and validate the round. A later scheduler update cannot rewrite historical lineage.

## Branch-Only Scheduler

The scheduler selects a control state rather than a modeling recipe. Normal priority is:

1. round zero: `draft / initial_seed`;
2. latest generated-code timeout: `debug / timeout_recovery`;
3. latest other generated-code failure: `debug / repair_failure`;
4. incomplete independent seed pool: `draft / required_seed`;
5. final budget window: `improve / final_audit`;
6. bounded stagnation response: `draft / plateau_new_seed`;
7. otherwise: `improve / frontier_improve` from validation best.

Timeout must be supported by structured status or an explicit runtime event. Ordinary exceptions are repair failures even if their logs mention timeout configuration.

### Draft Strategy

Draft creates an independent search origin. It does not patch validation best and the scheduler does not preselect a model family.

All draft states share these invariants:

- `parent_binding.role` is `none`;
- incumbent prefill is forbidden;
- historical code is not a required or optional implementation baseline;
- the runtime profile is score-first;
- the first completed trained route must be competitive and submission-ready;
- optional heavy tiers follow only after a strong complete candidate exists;
- experience may be inherited through summaries, but code may not be inherited.

Draft also receives a `3600s` soft workload-planning ceiling through the frozen `workload_plan_v1` decision field. This is not the external timeout and is not an hour-long quota: an expected five-minute route should remain a five-minute route. Before coding, draft records the required complete-route estimate and multiplicative work units in readiness. The old `test-lite` audit calibrates this envelope at `92.6%` of completed draft validations within one hour.

`draft / initial_seed` is round zero. It triggers early EDA and establishes schema, submission contract, resource risk, and a strong first route. It is not permission to emit a weak probe.

`draft / required_seed` builds the minimum independent seed pool. A repaired draft retains its original seed identity, so debug success can provide a scored representative without creating a second seed. Seed counting deduplicates structural method family; blends and control-state labels are not independent structural families.

`draft / plateau_new_seed` breaks an incumbent-centered local loop after four scored non-debug rounds without a material new best. A scored plateau draft resets the window. Plateau drafts have a five-round cooldown and a run-level maximum of two attempts.

Draft failure with concrete generated code is repaired in the next debug round. Every failed debug attempt retains the original seed ID, origin round and commit, effective branch, and draft-origin flag; a repair chain never becomes a new seed merely because its immediate parent is another debug round. LLM infrastructure failures, duplicate solutions, and missing solutions do not create a normal model-debug parent.

### Debug and Improve

Debug binds one concrete failed implementation. It should repair the observed failure while preserving the promising method family when feasible. The active hard scheduler permits at most two debug rounds for one effective seed. After two failed repairs it abandons that repair chain: an incomplete independent seed pool routes to `draft / required_seed`; a complete pool uses `draft / plateau_new_seed` while fresh-draft capacity remains, then falls back to `improve / frontier_improve` from validation best after that capacity is exhausted.

Improve binds the highest-scoring submission-eligible validation candidate at round start. Final audit uses the same binding and emphasizes low-risk reliability or bounded evidence-backed improvement.

## Parent, Prefill, and Frozen Evidence

`parent_binding` is the single identity contract:

- draft: none;
- debug: failed implementation;
- improve/final audit: validation-best eligible implementation.

A debug binding also carries the failed parent's frozen, non-recursive `effective_lineage`. This is control metadata for lineage inheritance and repair-count enforcement; it is not additional prompt-facing parent memory.

Parent memory in PART 3 contains only round, score, and complete `Method Portrait.method_summary`. Code, card, and feedback paths appear only in PART 4. Prefill, implementation base, parent identity, and baseline paths must resolve to the same commit or failed-round artifact.

`index/current_branch_decision.json` is mutable. Historical authority comes from frozen round results, compact summary rows, memory cards, and graph nodes. The runtime no longer writes `index/branch_decisions.jsonl`.

## Prompt and Source Routing

The coding prompt has four parts:

1. compact static execution, sandbox, readiness, and output rules;
2. task description and fixed constraints;
3. current round, parent or draft prior, score/history, and read-only external timeout;
4. must-read and optional local paths.

The active packer is `v54_draft_workload_ceiling`. PART 1 contains `[SYSTEM INSTRUCTIONS]`, `[PINNED SANDBOX ENVIRONMENT]`, `[CONTEXT-FIRST PROTOCOL]`, and `[OUTPUT CONTRACT]`; it does not inline branch guards or routed skill bodies. Its representative complete form is regression-tested below 2,200 tokens. The detailed static contract, removed accumulation, compatibility facts, and audit boundary are documented in `docs/coding_prompt_part1_contract.md`.

PART 3 `part3_compact_v3` contains:

- one `[ROUND DIRECTIVE]`;
- one branch-exclusive parent or prior-memory block;
- bounded score context and round history;
- draft-only `[DRAFT WORKLOAD CEILING]` or parent-relative `[OBSERVED RUNTIME EVIDENCE]` when available;
- one `[EXTERNAL VALIDATION TIMEOUT]` block with remaining sandbox runtime and the read-only validation cap.

Its content boundary is limited to the directive, routed memory, bounded score history, and the framework-selected external timeout.

The directive also owns the branch-specific execution guard. Draft requires an independent phase-scoped seed and one complete trained route before optional work. Debug binds the failed parent and failure class and shrinks cumulative work for timeout or OOM repair. Improve makes one material evidence-backed change while preserving a submission-ready validation-best incumbent.

For draft, a separate workload block supplies `draft_workload_ceiling_seconds: 3600` and the context-first protocol requires ordinary readiness planning fields. The value is a soft planning ceiling; `[EXTERNAL VALIDATION TIMEOUT]` remains the only hard execution wall.

Branch source policy is:

- draft: task skill, failure-prevention skill, latest EDA findings, existing high-level memory, and frozen summary-only draft prior;
- improve: anchor card/code/feedback, task skill, latest EDA findings, existing high-level memory, plus optional differentiated evidence;
- debug: failed parent card/code/feedback, failure-prevention skill, latest EDA findings, and optional broader history.

The required EDA source is the freshest `eda_findings.md` across `early_eda/round_*` and `deep_eda/round_*`. This file is the complete human-readable coding handoff and also receives accepted context deep-EDA updates. `eda_findings.json` remains an optional structured complement. `eda_summary.md` is retained for EDA generation/archive compatibility but is not routed when findings exist; it becomes a required fallback only for a legacy archive that has no findings markdown.

Existing required task-skill and failure-prevention paths are bold in PART 4. Missing required sources remain explicit. The task-local `context_sources/sandbox_model_cache.txt` is required for draft and optional for debug/improve. Codex must query it with a targeted case-insensitive command such as `grep -iE 'deberta|roberta' context_sources/sandbox_model_cache.txt`; it must not read the complete inventory into prompt context. `memory_bank/high_level_memory.md` is omitted until it exists. `memory_bank/prompt_context.md` is no longer generated or routed.

For a branch where the failure-prevention skill is required, Codex selects its concrete route first, reviews the complete routed skill against that plan, and records only applicable risks and concrete code actions in `context_readiness.md`. The framework neither selects numbered skill sections nor inlines a fixed excerpt. No separate sandbox preflight stage is implemented: the existing static gate is followed directly by full validation.

Five high-cost task skills currently use the standardized six-section schema: SIIM, APTOS, Jigsaw, TPS May 2022, and RANZCR. The runtime persists a branch-scoped view instead of the full skill:

- draft: `Task Contract And Traps`, `Seed Route`, `Validation Contract`, and `Avoid Or Delay`;
- debug: `Task Contract And Traps`, `Debug And Fallback`, `Validation Contract`, and `Avoid Or Delay`;
- improve: `Task Contract And Traps`, `Improve Library`, `Validation Contract`, and `Avoid Or Delay`.

The persisted source records the original path and SHA-256. A skill that does not contain all six exact headings remains full-text for compatibility and is marked `Phase scoped: false`; the runtime never guesses a partial mapping. The five installed reorganizations are verified against `tests/task_skill_reorganization_manifest.json` by `tests/task_skill_reorganization_audit.py`.

Draft prompt policy asks for one coherent primary score-first route. It does not impose a global sparse/tabular candidate count and does not require training extra models solely to create a stack. Selection, calibration, blending, or stacking belongs in the current phase only when the routed skill and available predictions justify it.

Static-gate repair suppresses high-level history. Draft static repair additionally suppresses draft prior and round history so a safety correction cannot become route reselection.

## Readiness and Post-Code Summary

Before coding, Codex writes `context_readiness.md` as evidence and implementation planning. It records inspected PART 4 paths, branch/state, implementation base and prefill status, score response, data contract, route, validation, fallback, and failure traps. When failure-prevention guidance is required, readiness also records the plan-specific risks and code actions selected by Codex without reproducing the complete skill.

Draft readiness adds ordinary fields for `draft_workload_ceiling_seconds`, `expected_complete_path_seconds`, `runtime_estimate_basis`, `dominant_cost_units`, `complete_workload_product`, `within_ceiling: yes`, and `why_no_further_expansion`. The expected time can be only a few minutes; it is not stretched to the ceiling. Historical basis uses completed same-task actual sandbox runtime, prefers comparable successful routes, treats timeouts only as lower bounds, and rejects pre-dominant-stage failures as end-to-end estimates.

Readiness records evidence and implementation intent only. The framework fixes the external timeout before coding and shows it read-only in PART 3.

After generating `solution.py`, Codex writes `post_code_memory_summary.md` to describe the implementation that actually exists. Pre-code plans must not be treated as post-code method facts.

## External Validation Timeout

Runtime enforcement has one layer. Before coding, the framework takes the smaller of remaining task-level sandbox runtime and a workload-profile hard ceiling: low-cost `3600s`, sparse text `7200s`, and general or deep media `10800s`. Method-neutral branch scheduling uses the general cap because the concrete method is selected only after context inspection. Historical runtimes, branch state, recovery state, and final-window state do not shrink this wall.

The value is the external sandbox wall and the sole framework execution limit. It is prompt-visible but read-only. Readiness and generated solution constants do not alter it.

Only actual sandbox runtime is charged. A process that exits after 300 seconds consumes 300 seconds even if its external cap is much larger.

Draft separately uses `3600s` as a soft complete-workload ceiling. It changes plan shape, not execution authority. Debug does not inherit that ceiling: timeout/OOM recovery must reduce cumulative work relative to the failed parent. Improve estimates its bounded change from validation-best parent runtime evidence and keeps a complete incumbent path ahead of optional work.

`solution.py` must still be statically bounded. It should cap expensive dimensions, complete a competitive trained score-first route, retain the best complete predictions, skip doubtful optional work, write `submission.csv` atomically, and exit normally. A partially written file is not assumed to survive an external kill.

No branch restores solution-local deadlines, remaining-time polling, budget exceptions, or a separate sandbox preflight. Static workload sizing and the existing static gate remain the only pre-validation controls.

## Fixed Ready-Only Model Cache Inventory

The evaluator performs no run-start sandbox capability probe. Model-cache availability is a repository-maintained static contract, so cache discovery consumes no task sandbox runtime and creates no probe status, timing, package, or accelerator artifact.

`runtime/sandbox_model_cache.txt` is the canonical ready-only source. The runtime copies it unchanged to `context_sources/sandbox_model_cache.txt` for every task, routing it as required PART 4 context for draft and optional context for debug/improve. The published inventory contains 539 Hugging Face repositories verified to have a configuration and complete weights, plus 109 complete Torch checkpoints. Entries with missing configuration, missing or incomplete weights, no snapshot, or a `.partial` suffix are not published. Every listed entry is therefore ready by inventory contract and needs no per-line status label.

The inventory is intentionally lookup-oriented rather than prompt-expanded. Codex must search only relevant names or model families with `grep -i` or a targeted `grep -iE` expression and must not read the full file. It must use an entry only when task evidence supports that model family and must retain a no-download execution path. Updating the inventory requires a new explicit cache audit and a repository change; normal evaluator runs never mutate it. The 2026-07-14 survey evidence and publication boundary are recorded in `docs/static_sandbox_model_cache_audit.md`.

Prompt integration is limited to the lookup instruction in the sandbox card and the branch-routed PART 4 path. The inventory contents are not injected into PART 1 or PART 3.

## EDA

Round zero normally runs early EDA or reuses an archive. Later deep EDA is allowed only when a concrete ambiguity changes implementation. It is bounded, read-only, and recorded through the readiness deep-EDA JSON contract.

Coding reads the latest complete `eda_findings.md`, not the generated `eda_summary.md` wrapper. The resolver compares valid findings across early and deep EDA round directories by modification time. A legacy summary fallback preserves compatibility with old archives, but it must not displace an available findings file.

Deep EDA does not train models, run validation, decode an unbounded media tree, or create reusable prediction artifacts.

## Static Gate and In-Place Repair

The static gate protects hard format and safety contracts before sandbox validation. Hard blockers include missing `DATA_DIR` or `submission.csv`, known hardcoded paths, unsafe downloads, side outputs, untrained constant submissions, structurally proven hardcoded data cardinality, invalid statically known regular expressions/replacement templates, and definite same-block reads after `del name` without rebinding.

The two semantic checks are intentionally narrow. Regex validation covers only literal or unambiguous module-level constant patterns used by Python `re`, pandas string regex methods, and vectorizer `token_pattern`. Use-after-delete detection requires ordered AST evidence in the same statement block and clears the finding on rebinding or uncertain conditional binding. Dynamic values and ambiguous control flow do not become hard blockers.

Runtime boundedness, score-first structure, dependency fallback, and atomic finalization may produce warnings. The gate does not enforce a second execution limit inside the solution.

Repair flow is:

```text
round N code -> inspect
  pass/warn -> sandbox
  block -> in-place repair 1 -> inspect
             pass/warn -> sandbox
             block -> in-place repair 2 -> inspect
                        pass/warn -> sandbox
                        block -> archive static_gate_blocked
                                   -> round N+1 debug / repair_failure
```

Each repair reads the latest complete root `solution.py`, applies the smallest relevant correction, and recomputes the whole contract. It creates no new round or commit. A valid file written before a Codex repair timeout may be salvaged; invalid or deleted output is restored from the pre-call file.

After two failed attempts, the final code and evidence are archived under `failed_rounds/round_<NNN>_static_gate_blocked/`. The round enters history and memory but not the eligible portfolio.

## Validation, Taxonomy, and Selection

Sandbox validation uses the external cap. Quality checks reject uninformative constant or fallback-dominated outputs even when the sandbox reports a raw score.

Timeout taxonomy stores evidence and source. Exact external timeout status and explicit events such as `TimeoutError`, `timed out`, `deadline_guard`, and `BudgetExhausted` support timeout recovery. Configuration variable names and incidental tokens do not.

A zero-output external timeout proves that the sandbox wall was reached, but it does not prove which solution stage or method change caused it. Memory and diffs must preserve that uncertainty.

The eligible portfolio contains only scored candidates that pass static and quality gates. Final selection follows metric direction and validation best, not branch recency.

## Memory and Experience

Each completed round creates one memory card. Comparable parent rounds may create a method diff. A scored new draft is compared with the previous validation-best draft.

`memory_bank/high_level_memory.md` is rebuilt from diffs:

- positive experiences: improved parent patches and better-draft advantages;
- negative experiences: scored parent regressions;
- debug experiences: explicit failure-to-scored-success repairs.

Experience statements describe observed association, not unverified causality. Successful cards omit verbose diagnostics; failed cards retain repair-relevant evidence.

Draft prior memory freezes at most four representative draft cards. Every entry contains round, score, and the complete `method_summary`. It is not a parent, code source, modeling directive, or new long-term card.

## Primary Artifacts

```text
rounds_summary.json                  compact run history and final selection
index/current_branch_decision.json   mutable current-round control
index/best_validation_candidate.json validation-best eligible vault
graph/nodes.jsonl                    append-only candidate ledger
graph/portfolio.json                 scored eligible frontier
memory_bank/card_index.jsonl         compact post-round index
memory_bank/cards/*.md               method and result evidence
memory_bank/diffs/*.md               parent or draft method changes
memory_bank/high_level_memory.md     derived positive/negative/debug experience
commits/<hash>/                      code, feedback, result, and summaries
failed_rounds/<name>/                non-commit failure evidence
traces/round_<n>_trace.json          Codex prompt, response, stderr, use, and timing
context_sources/sandbox_model_cache.txt branch-routed ready-only cache lookup inventory
```

`graphic.png` is a human-only derived view and never participates in scheduling or prompt construction.

## Handoff Checklist

Before changing scheduling, prompts, or validation:

1. read the active implementation rather than relying only on documentation;
2. distinguish mutable control from frozen historical evidence;
3. preserve the actual round decision in detailed and compact results;
4. keep concrete modeling choice with Codex unless the architecture intentionally changes;
5. verify metric direction, eligibility, timeout evidence, and final selection;
6. keep parent, prefill, baseline, and PART 4 identities aligned;
7. verify draft, debug, improve, final-audit, and static-repair prompt variants;
8. ensure PART 3 has one directive and one read-only external timeout;
9. ensure readiness remains an evidence and implementation-planning artifact;
10. distinguish timeout cap, actual sandbox runtime, wall time, and token estimates;
11. test both explicit runtime exhaustion and ordinary exception routing;
12. keep memory claims within observed evidence;
13. verify the task-local model-cache inventory matches the repository source and is queried rather than prompt-expanded.

## Known Cleanup Items

- Unreachable legacy operator-selection helpers remain for compatibility.
- `branch_strategy` and `warmup_branches` are accepted but ignored by the active v4 scheduler.
- `runtime/bootstrap.py` still injects a merged namespace back into modules.
- Traces and detailed results duplicate large payloads.
- Full evaluator smoke tests require external sandbox and inference services.
