# Coding Prompt 清理计划（2026-07-08）

参考样本：

- `run_mlsp_5round_deepeda_observation_20260708_rerun/mlsp-2013-birds/context_sources/coding_prompt_after_pack.md`
- 该样本来自 `mlsp-2013-birds` Round 2 debug prompt。
- 按当前框架 packer 逻辑生成的完整审核样例见 `docs/coding_prompt_example_mlsp_debug_rewrite_20260708.md`。

目标：保留四段式框架，但把每段压成真正可执行的 prompt surface。prompt 应只内联不可丢失的硬约束和当前 round 决策；完整 task skill、完整 EDA、历史代码、feedback、memory card 等应通过 source map 路径读取。禁止继续把解释性占位文案、空值字段、重复 guard 和规则性 EDA 指导塞进 coding prompt。

## 0. 分区 Subagent 审阅摘要

本轮按四个 PART 分别审阅，结论如下：

1. `PART 1` 的主要问题不是四段式本身，而是硬规则重复。`SYSTEM INSTRUCTIONS`、`BRANCH INLINE GUARDS`、`Runtime Hardening Guard` 都在重复 offline、submission、fallback、no run、timeout 等规则，且出现 guard 内再套 `[RUNTIME HARDENING CONTRACT]` 的标题层级。应把 system 整理成结构化硬规则，只删除完全重复和占位噪声，不能删除实质约束；sandbox facts 是环境契约，资源、包、权重策略和 API 兼容信息必须完整保留。
2. `PART 2` 的主要问题是把“来源说明”和“EDA 操作规则”伪装成任务上下文。`TASK SKILL SOURCE MODE` 没有任务信息，应删除；task skill 的含义应放到 `PART 4` source map。EDA 不再内联到 `PART 2`，只把 `latest_eda_summary` 作为必读路径列入 `PART 4`；完整 EDA findings 和累计 EDA insight store 作为按需扩展路径。
3. `PART 3` 的主要问题是 state dump 不是 branch control。debug 场景仍展示 `Validation-best score: None`、空 anchor、空 best candidate，导致模型看不到真正优先级。应按 `draft/debug/improve` 分别渲染，debug 只展示 debug parent 与失败修复边界，improve 只展示 best/anchor、score feedback 和 diff，draft 不展示 incumbent code 路径。
4. `PART 4` 的方向正确，但 source label 需要有类型语义。当前 `routed_skill_source` 可能是 failure-prevention guard，也可能被 prompt 描述成 task skill，容易误导。应拆成 `failure_prevention_skill_source` 与 `task_skill_source`，并规定 memory card 先读 index 再按需读具体 card，避免把目录整体扫进上下文。

关键代码位置：

- `runtime/prompt_pack.py`: 四段 prompt 组装、空 candidate section、branch inline guard 和 source map 入口。
- `runtime/text_context.py`: `build_v35_context_source_map()`、`build_v35_hard_task_contract()`、`build_v35_context_first_protocol()`、`build_pinned_runtime_context()`。
- `runtime/branch_policy.py`: `build_v4_round_directive()` 中的 branch directive 和空字段渲染。
- `runtime/runner.py`: source 持久化命名与 routed source 类型信息。

## 1. 当前问题概览

1. `PART 1` 规则过长且重复。
   - `SYSTEM INSTRUCTIONS` 已包含大量 runtime、score-first、recipe fidelity、offline weight、submission 规则。
   - `BRANCH INLINE GUARDS` 又嵌入 `Debug Error Taxonomy Guard` 和完整 `Runtime Hardening Contract`。
   - `Runtime Hardening Guard` 标题下再出现 `### [RUNTIME HARDENING CONTRACT]`，标题层次和语义重复。
   - 结果是 Codex 在真正读 task/parent/feedback 前先消耗大量注意力在通用规则上。
2. `TASK SKILL SOURCE MODE` 是无信息占位文案。
   - 当前文本只说明“去 source map 读 routed skill source”，没有提供任务事实、建模先验或执行决策。
   - 该 section 不应作为 `PART 2` 的实体内容出现。
   - 正确做法是在 `PART 4` 的 source map 中标注 `routed_task_skill` 是必读高质量建模先验，含义是 task-specific recipe / feature / validation prior。
   - 如果当前 routed source 实际是通用 error-prevention skill，不应把它描述为 task skill。
3. `PINNED EDA SCHEMA CARD` 混入了规则性 EDA 指导。
   - 当前样本内联了 `Data Contract`、`Submission Contract`、`Resource And Size Risks`、`Planning Constraints` 等通用指导。
   - 这些不是 EDA 结论，且与 `CONTEXT-FIRST PROTOCOL`、system prompt、runtime hardening 重复。
   - 初始 EDA 已在 prompt 前完成；coding prompt 不再内联 EDA 结论，只给 `latest_eda_summary` / `eda_insights_store` / full EDA findings 路径。
   - deep EDA 的使用规则只能放在 `CONTEXT-FIRST PROTOCOL`，不应出现在 EDA card 中。
   - `Persisted EDA Insights` 不能把 markdown 摘要压成一个 `finding=# EDA Summary ...` 长行，应拆成可读的事实条目。
4. `PART 3` 没有按 branch 类型选择性展示。
   - debug round 仍打印 `Validation-best score: None`、`Validation-best round: None`、`Anchor parent: {}` 等无效字段。
   - 对 debug 来说，最重要的是 `debug_parent` 的 card/code/feedback、failure taxonomy、parent method family、prefill status、repair boundary。
   - 对 improve 来说，最重要的是 validation-best/anchor parent 的 score/card/code/feedback/diff、score feedback、material-gain requirement。
   - 对 draft 来说，不应展示 parent/best code path，避免无意 patch incumbent。
5. `BEST VALIDATION CANDIDATE` 空对象不应出现。
   - 样本中 `## [BEST VALIDATION CANDIDATE] {}` 对 debug with no scored rounds 没有信息价值。
   - 空 section 应被省略，或并入 branch-specific compact state。
6. `INTEGRATED CONTEXT-FIRST PLANNING` 是历史兼容残留。
   - 它只解释“v4 不运行 planning phase”，这不是 Codex 需要执行的当前任务信息。
   - 应删除该 section，把唯一执行要求保留在 `CONTEXT-FIRST PROTOCOL` 和 `ROUND DIRECTIVE`。
7. `USER TASK` / `[TASK DESCRIPTION]` 应保留原始任务描述作为权威文本，不应由框架或人工手写二次总结替代。
   - 样本中 `[TASK DESCRIPTION]` 虽然较长，但它来自原始 benchmark/task prompt，是任务语义来源。
   - 对 coding 最关键的 metric、submission format、task unit、target shape、主要 data files 可以在 `[TASK CONTRACT]` 中再结构化提炼。
   - 长篇非执行性信息若要裁剪，必须来自确定性过滤规则或保留到 `full_user_task_prompt`，不能换成无来源的概括文本。
8. `PART 4` 方向正确，但标签语义不够强。
   - source map 已列 must/optional paths。
   - 但没有解释为什么 `routed_skill_source` 必读、读它要提取什么、EDA summary 与 EDA insight store 的区别、debug/improve memory card 的用途。
   - must-read 也要控制数量。debug 的核心是 parent card/code/feedback 与失败预防清单；完整 EDA JSON、全部 memory 目录、长任务原文应默认 optional expansion。

## 2. 新 Prompt 设计原则

1. 四段式保留，但每段只承担一个职责。
   - `PART 1`: non-negotiable execution rules.
   - `PART 2`: original task description and executable task contract.
   - `PART 3`: branch-specific current-round control.
   - `PART 4`: source map and reading obligations.
2. 删除无信息占位 section。
   - 删除 `TASK SKILL SOURCE MODE`。
   - 删除空 `BEST VALIDATION CANDIDATE`。
   - 删除 `INTEGRATED CONTEXT-FIRST PLANNING`。
3. EDA 不内联。
   - `PART 2` 不出现 `[PINNED EDA SCHEMA CARD]`、`[PINNED EDA FINDINGS]` 或 `[KNOWN DATA FINDINGS]`。
   - `PART 4` 把 `latest_eda_summary` 作为必读路径，把 full `eda_findings.md/json` 和 `eda_insights.jsonl` 作为按需扩展路径。
   - 不再内联 `Resource And Size Risks`、`Planning Constraints` 这类规则性段落，也不内联 EDA 结论全文。
4. Branch-specific runtime control。
   - draft: 展示 branch state、reason、seed diversity / score-first requirement、budget、must-read skill/EDA/memory index；禁止 parent/best code fields。
   - debug: 展示 debug parent card/code/feedback、failure summary、repair method family、prefill status、budget、deep EDA advice if parser/schema uncertainty exists；不展示 empty validation-best / anchor fields。
   - improve: 展示 anchor/best card/code/feedback/diff、anchor score、latest score feedback、material-gain requirement、budget；不展示 debug fields。
5. Source map 是完整信息入口。
   - 每个 source label 应有短用途说明。
   - `routed_task_skill`: high-quality task-specific modeling prior; extract recipe, features, validation hints, traps.
   - `latest_eda_summary`: initial/latest EDA facts; must read before coding.
   - `eda_insights_store`: cumulative initial/deep EDA facts; read for recent contract updates.
   - `debug_parent_card`: post-round method/failure summary.
   - `debug_parent_solution`: patch baseline for debug only.
   - `debug_parent_feedback`: authoritative failure evidence.

## 3. 分区修改方案

### PART 1 - 硬执行规则与沙盒

保留：

- `SYSTEM INSTRUCTIONS`, but reorganize/deduplicate hard rules without losing substantive constraints.
- `PINNED SANDBOX ENVIRONMENT`, with complete resource facts, complete package lists/groups from the benchmark prompt, offline model-weight policy, and API compatibility constraints.
- `CONTEXT-FIRST PROTOCOL`, including autonomous lightweight deep EDA boundary.
- `OUTPUT CONTRACT`.

修改：

- Replace full `BRANCH INLINE GUARDS` with a compact branch guard generated from current branch only.
- For debug, keep at most 5-7 bullets: repair linked parent, preserve method unless impossible, fix whole failure class, keep score-first path, no broad new model family.
- Move detailed runtime hardening into system prompt or a branch-specific runtime guard; do not duplicate the same contract twice, but do not drop hard requirements.
- Add explicit deep EDA incremental rule:
  - `Deep EDA is an incremental detail patch to initial EDA, not a replacement. Do not repeat full dataset inventory. Inspect only the smallest files/rows needed to resolve the current ambiguity or failure.`

代码落点：

- `prompts.py`: deduplicate and structure the system prompt while preserving all hard execution, modeling, runtime, offline-weight, submission, and reproducibility constraints.
- `runtime/skills.py`: stop injecting full `RUNTIME_HARDENING_CONTEXT` into branch inline guards, or provide compact guard variant.
- `runtime/text_context.py`: update `build_v35_context_first_protocol()`.

### PART 2 - 任务描述与任务契约

保留：

- `PINNED HARD TASK CONTRACT`, but only if it contains actual parsed task contract / validation contract / avoid rules.
- The original `[TASK DESCRIPTION]` text from the benchmark/task prompt, or a deterministic excerpt that preserves the original wording and source.
- A compact `[TASK CONTRACT]` that extracts executable task objective, metric, target, submission format, and core files from the original description plus observed data.

删除：

- `TASK SKILL SOURCE MODE`.
- `CURRENT FRAMEWORK USER CONTRACT` if it only says to ignore legacy markdown answer. This belongs in system/output contract.
- Hand-written task-description summaries that are not directly traceable to the original task prompt.
- All EDA inline cards, including schema cards, findings cards, and generic EDA method guidance.

修改：

- Keep `PART 2` focused on the original task wording and executable contract.
- Move all EDA access to `PART 4`: `latest_eda_summary` must-read, full `eda_findings.md/json` and `eda_insights_store` optional expansion.
- Move all deep EDA decision guidance to `CONTEXT-FIRST PROTOCOL`; no EDA guidance should appear as a task-context card.

代码落点：

- `runtime/prompt_pack.py`: do not call or inject an EDA card in `PART 2`.
- `runtime/text_context.py`: make `build_v35_context_source_map()` list `latest_eda_summary` as must-read and full EDA artifacts as optional expansion.
- `runtime/text_context.py`: change `filter_user_task_for_context_first_coding()` to preserve original `[TASK DESCRIPTION]` wording or deterministic excerpts, while routing full task text to source map when truncation is required.
- `runtime/text_context.py`: make `build_v35_hard_task_contract()` return no placeholder section for guard-only skill packets.

### PART 3 - 当前轮控制

保留：

- `ROUND STATE`, but make it one compact branch-specific card.
- `ROUND DIRECTIVE`, but remove duplicates already in runtime control.
- `Score feedback`, but only if non-empty and actionable.
- Runtime budget fields.

删除：

- Empty `BEST VALIDATION CANDIDATE`.
- `INTEGRATED CONTEXT-FIRST PLANNING`.
- `Validation-best ... None` fields.
- Empty `Anchor parent` fields in debug/draft.
- Empty `Debug parent` fields in draft/improve.

修改：

- Generate branch-specific cards:
  - `[DRAFT ROUND CONTROL]`
  - `[DEBUG ROUND CONTROL]`
  - `[IMPROVE ROUND CONTROL]`
- Debug card should show:
  - branch state and reason
  - debug parent round/commit/card/code/feedback
  - failure primary and method family
  - prefill source
  - repair boundary
  - budget and internal budget
  - deep EDA advice only if schema/parser/data-contract uncertainty is plausible
- Improve card should show:
  - anchor/best round/commit/score/card/code/feedback/diff
  - latest score feedback and required response
  - material gain threshold
  - optional import rule for other nodes
  - budget
- Draft card should show:
  - seed objective
  - diversity/family anti-repeat state
  - no parent/best code inspection rule
  - required skill/EDA/memory index sources
  - budget

代码落点：

- `runtime/text_context.py`: split `critical_lines` construction into branch-specific helper.
- `runtime/branch_policy.py`: make `build_v4_round_directive()` skip empty fields and avoid duplicating data already in `ROUND CONTROL`.
- `runtime/prompt_pack.py`: omit empty `BEST VALIDATION CANDIDATE`; drop `INTEGRATED CONTEXT-FIRST PLANNING`.

### PART 4 - Source Map

保留：

- One canonical source map.
- Must/optional separation.
- Relative task paths.
- Context acquisition data directory, but only as read-only probe root and never as code constant.

修改：

- Rename labels to make semantics obvious:
  - `task_skill_source` instead of ambiguous `routed_skill_source` when it is task-specific
  - `failure_prevention_skill_source` when it is the generic MLE error-prevention skill
  - `latest_eda_summary` for the current initial/latest EDA handoff that must be read before coding
  - `eda_insight_store` for cumulative initial/deep facts
- Add one-line purpose per source class.
- In debug, ensure debug parent card/code/feedback are must-read; EDA full findings should be optional unless failure indicates data-contract uncertainty.
- In improve, anchor card/code/feedback/diff are must-read; top-diverse cards/code are optional.
- In draft, task skill and initial EDA facts are must-read; prior code remains optional or suppressed.

代码落点：

- `runtime/text_context.py`: update `build_v35_context_source_map()`.
- `runtime/prompt_pack.py`: move task skill explanation from `PART 2` to `PART 4` description.

## 4. 新 Coding Prompt 示例

下面示例展示类似 MLSP 样本 debug round 的目标 prompt 形态。它刻意保持紧凑，并省略长任务原文。

```markdown
# PART 1 - EXECUTION RULES

## [SYSTEM RULES]
- Create `context_readiness.md`, then `solution.py`.
- Do not run `solution.py`, validation, sandbox jobs, training scripts, notebooks, EDA scripts, model fitting, hyperparameter search, or internet.
- `solution.py` must read only `DATA_DIR`, train from current train files, and write only `submission.csv`.
- Do not hardcode local paths, row counts, class counts, IDs, or public-data facts.
- Use the pinned internal budget as a hard deadline; complete one trained score-first candidate before optional work.
- This block may be deduplicated and reorganized, but must not lose substantive hard constraints from the benchmark/system prompt.

## [CONTEXT-FIRST PROTOCOL]
- Inspect every must-read source in PART 4 before editing code.
- You may perform bounded read-only data-contract probes only when needed to resolve a concrete ambiguity or failure.
- Deep EDA is an incremental detail patch to initial EDA, not a replacement. Do not repeat full dataset inventory.
- Allowed probes: shallow file listing, heads, metadata reads, tiny Python snippets over limited rows/files.
- Forbidden probes: training, validation, model fitting, full scans, recursive media decoding, prediction caches, writes outside `context_readiness.md` and `solution.py`.
- If deep EDA is used, record a fenced JSON object in `context_readiness.md` with `source=deep_eda`, `trigger`, `files_checked`, `commands_or_reads`, `finding`, `confidence`, `coding_implication`.

## [SANDBOX FACTS]
- Resource: GPU, 6 CPU cores, 200GB RAM, 24GB VRAM.
- Preinstalled package groups:
  - numpy, pandas, scikit-learn, scipy
  - xgboost, lightgbm, catboost
  - torch, torchvision, torchaudio, timm
  - transformers, datasets, tokenizers, accelerate, sentence-transformers
  - opencv-python, scikit-image, pillow, albumentations
  - librosa, soundfile, speechbrain, openai-whisper
  - optuna, bayesian-optimization, shap
- Other listed packages: tensorflow, huggingface-hub, torch-geometric, spacy, nltk, sentencepiece, tiktoken, einops, safetensors, keras, ultralytics.
- Model-weight handling:
  - No internet/model downloads.
  - Use offline/cache-only pretrained weights when available.
  - Print whether pretrained weights were actually loaded.
  - Keep a trained no-download fallback.
- API compatibility constraints: use stable package APIs such as `torch.optim.AdamW`, LightGBM callbacks, recent Transformers `eval_strategy`, and verified albumentations arguments.

# PART 2 - TASK DESCRIPTION AND CONTRACT

## [TASK CONTRACT]
- Task: multi-label bird species prediction from 10-second audio clips.
- Metric: AUC.
- Target: 19 species probabilities per test recording.
- Submission: preserve sample submission columns/order; probability values in [0, 1].
- Primary files: `essential_data/*`, audio/spectrogram/supplemental feature files under `DATA_DIR`.

## [TASK DESCRIPTION]
<Original benchmark task description or deterministic excerpt from it. Do not replace this with a hand-written summary.>

# PART 3 - DEBUG ROUND CONTROL

## [DEBUG CONTROL]
- branch_state: repair_failure
- reason: latest generated code failed with schema/data parsing error
- repair parent: round 0, commit `dfc98b14`
- parent method family: `tabular_multiview_multilabel_ovr_auc`
- must patch parent code, not start a broad new model family
- repair the whole parser failure class across sibling files, not only the stack-frame line
- if feedback leaves file-format uncertainty, do bounded deep EDA before coding

## [RUNTIME BUDGET]
- validation timeout: 3600s
- internal solution budget: <=3060s
- preserve one trained score-first path and skip optional heavy work if budget is tight

## [SCORE FEEDBACK]
- no scored rounds yet
- required response: build a practical trained candidate after fixing the parser; do not optimize around scaffolding alone

# PART 4 - SOURCE MAP

Must inspect before coding:
- `debug_parent_card`: `memory_bank/cards/round_000_dfc98b14.md` - method/failure summary
- `debug_parent_solution`: `commits/dfc98b14/solution.py` - patch baseline
- `debug_parent_feedback`: `commits/dfc98b14/validation_feedback.txt` - authoritative failure evidence
- `task_skill_source`: `context_sources/task_skill_source_1.md` - task-specific high-quality modeling prior and core modeling basis, especially for draft/improve
- `failure_prevention_skill_source`: `context_sources/failure_prevention_skill_source_1.md` - general MLE failure checklist
- `latest_eda_summary`: `early_eda/round_0/eda_summary.md` - initial/latest factual data findings; must read before coding

Optional expansion:
- `eda_insight_store`: `memory_bank/eda_insights.jsonl` - cumulative initial/deep EDA findings
- `full_eda_findings_json`: `early_eda/round_0/eda_findings.json` - structured EDA facts when the summary is insufficient
- `full_eda_findings_md`: `early_eda/round_0/eda_findings.md` - full EDA findings when the summary is insufficient
- `memory_card_index`: `memory_bank/card_index.jsonl` - prior cards and statuses
- `failure_ledger`: `memory_bank/failure_ledger.jsonl` - compact failure history
- `full_user_task_prompt`: `context_sources/coding_user_task_full.md` - original long benchmark text
```

## 5. 实施清单

1. Refactor prompt packer sections.
   - Update `runtime/prompt_pack.py` part descriptions.
   - Remove `INTEGRATED CONTEXT-FIRST PLANNING` from coding prompt.
   - Skip empty candidate sections.
2. Refactor EDA routing.
   - Remove EDA inline cards from `PART 2`.
   - Require `latest_eda_summary` through source map; expose full EDA artifacts and `eda_insights.jsonl` as optional expansion.
   - Do not include generic resource/planning instructions or EDA conclusions as inline task sections.
3. Refactor hard task contract / skill source handling.
   - If routed skill context is only guards, emit no `TASK SKILL SOURCE MODE` section.
   - Add task skill source purpose in source map.
   - Persist routed sources with type-aware filenames, e.g. `task_skill_source_*.md` and `failure_prevention_skill_source_*.md`.
4. Refactor round control.
   - Add branch-specific rendering helpers.
   - Omit `None`, `{}`, and empty path fields.
   - Debug shows debug parent only; improve shows anchor/best only; draft suppresses incumbent code paths.
   - Fix zero-valued fields rendered empty by `or ''`; use explicit `is not None`.
5. Refactor guards.
   - Keep one compact branch guard and one compact runtime guard.
   - Avoid repeating full runtime contract in both system prompt and branch inline guards.
6. Add prompt smoke checks.
   - Assert no `TASK SKILL SOURCE MODE`.
   - Assert no `Validation-best score: None`.
   - Assert no empty `BEST VALIDATION CANDIDATE`.
   - Assert no `[PINNED EDA SCHEMA CARD]` containing generic EDA rules.
   - Assert no `[PINNED EDA FINDINGS]` / `[KNOWN DATA FINDINGS]` inline EDA section in `PART 2`.
   - Assert `latest_eda_summary` appears in must-read source paths.
   - Assert `context_readiness.md` post-code memory summary instructions are present.
   - Assert debug prompt must-read includes parent card/code/feedback and routed task skill source.
   - Assert `draft/debug/improve` prompt samples expose only their branch-relevant parent/best/debug fields.
