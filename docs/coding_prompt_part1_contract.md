# Coding Prompt PART 1 Contract

## Purpose

PART 1 is the static execution contract for every coding and static-gate repair call. It contains only rules that are invariant across task, round, and branch, plus sandbox facts extracted from the original benchmark prompt. Dynamic branch behavior belongs to PART 3 and local evidence paths belong to PART 4.

The active packer identifies this layout as `v54_draft_workload_ceiling`.

## Active Composition

PART 1 contains four sections:

1. `[SYSTEM INSTRUCTIONS]`: context order, data and output safety, trained-solution requirements, complete-workload bounding, offline model loading, fail-fast contract checks, and observable progress.
2. `[PINNED SANDBOX ENVIRONMENT]`: resources, installed package groups, the fixed model-cache lookup instruction, and concrete benchmark API compatibility notes.
3. `[CONTEXT-FIRST PROTOCOL]`: required evidence reads, bounded read-only data inspection, route-specific failure-prevention review, the pre-code readiness schema, and the post-code memory schema.
4. `[OUTPUT CONTRACT]`: the files to create or repair and the required final response shape.

`[ROUND DIRECTIVE]` in PART 3 is the sole prompt-facing branch action authority. Draft requires an independent phase-scoped seed and a complete trained route before optional work. Debug binds the failed parent and failure class and explicitly reduces cumulative work for timeout or OOM recovery. Improve preserves the validation-best incumbent while making one material evidence-backed change. Routed skill bodies are not inlined into PART 1; their branch-scoped files are exposed through PART 4.

## Removed Accumulation

The compact contract removes the following former prompt policy:

- the separate `[RUNTIME HARDENING CONTRACT]`, which duplicated data, timeout, fallback, and submission rules;
- branch-specific draft, debug, improve, and runtime-hardening guard bodies in PART 1;
- prestige framing such as the top-ranked grandmaster persona;
- mandatory implementation coverage tables and fixed numbers of candidate models;
- universal composite, stack, calibration, and broad mini-portfolio requirements;
- modality-specific prescriptions that required a CNN, frozen-feature route, or a particular fallback position for every expensive task;
- subjective package preference, including a general PyTorch-over-TensorFlow rule;
- speculative policy such as one-knob warnings, vague runtime-permits expansion, and repeated score-first restatements.

These removals do not relax the hard requirements to train a task-appropriate model, produce a schema-valid submission, avoid downloads and silent invalid fallbacks, or finish within the framework-owned external timeout.

## Preserved Compatibility Facts

The sandbox card still projects concrete compatibility facts from the original benchmark prompt when their cues are present:

- use `torch.optim.AdamW` rather than the deprecated Transformers import;
- use LightGBM callbacks such as `lightgbm.early_stopping(...)` and avoid deprecated `fit()` arguments;
- use current Transformers `eval_strategy` behavior and handle class weighting in the loss;
- use verified Albumentations crop/geometric APIs such as `size=(H, W)`.

The ready-only model inventory remains a targeted `grep -i` lookup at `context_sources/sandbox_model_cache.txt`. The inventory content is never expanded into the prompt.

## Added General Safeguards

The compact contract makes the following general requirements explicit:

- estimate the complete path across discovery, preprocessing, candidate by fold by epoch work, validation, inference, TTA, and optional tiers;
- reduce resolution or input volume before expensive deterministic transforms and cache reusable preprocessing when memory-safe;
- verify meaningful parameter-name and shape coverage for manually loaded checkpoints;
- treat cache availability as infrastructure evidence, not as evidence that a pretrained model family is appropriate for the task;
- prefer proven library components for standard plumbing and validate invariants when custom logic is necessary;
- replace failed plumbing only with a deterministic, semantically equivalent component; never weaken the selected modeling route under the label of fallback;
- reject blank, constant, or template fallbacks that mask systematic read, schema, decode, or label failure;
- run generic import, initialization, representative-batch, metric, and submission-alignment checks before expensive work;
- flush phase progress around expensive work so interrupted validation leaves actionable evidence.

The frozen branch decision carries structured `workload_plan_v1` control and runtime evidence. Draft readiness records the corresponding ordinary planning fields: `draft_workload_ceiling_seconds`, `expected_complete_path_seconds`, `runtime_estimate_basis`, `dominant_cost_units`, `complete_workload_product`, `within_ceiling: yes`, and `why_no_further_expansion`. Readiness neither copies the control object nor changes the framework-owned external timeout.

For draft, PART 3 supplies a `3600s` soft planning ceiling. This is a ceiling rather than a quota; expected runtime may legitimately be only a few minutes. Debug and improve do not inherit a universal one-hour target: debug scales repair work against the failed parent, while improve scales its bounded change against the validation-best parent. Historical evidence uses actual sandbox runtime from completed same-task rounds; timeouts are lower bounds and failures before the dominant work stage are not end-to-end runtime estimates.

## Failure-Prevention Review

When branch source policy marks the failure-prevention skill as required, Codex reads the complete skill from PART 4. After choosing a concrete modeling route and before writing `solution.py`, it reviews that exact plan against the skill and records only applicable risks and concrete code actions in `context_readiness.md`. It must not copy the full checklist.

The framework does not select numbered failure-skill sections, generate excerpts, or hard-code a task-to-failure mapping. The agent performs the applicability decision from the complete skill, preserving flexibility while making the review auditable.

This revision does not add a separate sandbox preflight call, artifact, repair loop, runtime state, solution-local timer, deadline guard, or remaining-time poll. Execution still proceeds from prompt generation and the existing static gate directly to full validation. The fail-fast checks above are requirements inside the generated solution's normal execution path.

## Token and Regression Checks

The former `SYSTEM_PROMPT` used 2,199 tokens and the separately inlined runtime-hardening block used another 1,166 tokens under the repository token counter. The current compact `SYSTEM_PROMPT` uses 1,039 tokens. A representative PART 1 containing resources, model-cache routing, all four API compatibility notes, failure-prevention review, and draft workload readiness uses 2,061 tokens.

`tests/test_prompt_pack_part3.py` enforces a 2,200-token ceiling for that representative complete PART 1 and checks required and obsolete markers. `tests/test_round_context.py` verifies that branch-specific execution guards are rendered by PART 3. Prompt-pack JSON records `branch_context_routing.inlined=false`; the old `selected_skill_filter` and `branch_inline_guards` accounting fields are absent.
