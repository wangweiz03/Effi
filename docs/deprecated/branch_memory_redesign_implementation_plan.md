# 仅分支调度与记忆卡片设计实现记录

本文档记录当前 branch-only runtime、source-map prompt、memory card/diff 和 search graph monitor 的设计动机、已实现状态与后续边界。旧版设计评审和 prompt cleanup 观察文档不在非 deprecated 文档入口中，不能作为当前实现事实来源。

当前 checkout 使用 `docs/` 作为文档库入口；若外部说明写 `doc/`，在本仓库中按 `docs/` 执行。

## 0. 当前实现状态

截至本轮修改，主体代码已经按本文档的 v2 方案落地：

- `runtime/branch_policy.py` 的正常路径已改为仅选择 `branch`、有限 `branch_state`、`branch_reason`、`runtime_profile`、`eda_mode`、`anchor_parent`、`debug_parent` 和 `source_policy`；旧 `search_intent/search_operator` 只作为兼容中性字段保留。
- `improve` 默认锚定进入本轮前的 best 可提交/有分数节点，`solution.py` 预填和方法差分都以该锚点父节点为基线；其他节点方法只能作为 Codex 读卡/读代码后的引入来源。
- `draft` 不再因为旧 intent 缺失而读取父代码或无法累计 draft-origin seed；有效分支为 `draft` 且有分数的结构性种子可进入 seed pool。
- `runtime/prompt_pack.py` 的编码路径使用 `v50_four_part_branch_memory_source_map` 四块提示词；完整技能和记忆不再内联，改由 `[CONTEXT SOURCE MAP]` 列出必读/选读路径。
- 编码 after-pack Markdown 使用清晰标题系统：`# PART ...` 是四块一级标题，独立方括号 marker 自动提升为二/三级标题，原始 Markdown 小节会按当前容器下沉，避免容器和内容同级；`[BRANCH INLINE GUARDS]` 只出现一次，EDA 不再内联，`latest_eda_summary` 作为 source map 必读路径，完整 `eda_findings.md/json` 和 `eda_insights.jsonl` 作为按需扩展路径。
- `runtime/memory_cards.py` 已新增。沙盒返回、静态门禁阻断、重复解和无提交结果都会写英文 `memory_bank/cards/*.md`；有父节点的 `improve/debug` 会写英文 `memory_bank/diffs/*.md`。
- 记忆卡片硬记录同步写入；软总结先标记 `pending_local_async`，再由轻量后台线程回填为 `completed_local` 或 `failed`。prompt-facing card 使用 `Meta`、`Method Portrait`、`Result Signal` 三段保存 solution.py 的零阶高密度画像；软字段优先使用 Codex 写完代码后单独写入的 `post_code_memory_summary.md`，`method_keywords/core_components` 会稳定去重，避免 `initial_seed, initial_seed` 这类重复。
- `graph/portfolio.json`、`nodes.jsonl`、`rounds_summary.json` 和兼容记忆视图继续保留，并新增 `memory_card_path`、`memory_diff_path`、`branch_state`、`runtime_profile`、`anchor_parent`、`debug_parent` 等字段。
- 新增确定性搜索图监控挂件：每轮 summary 落盘后 best-effort 重建任务目录根部的 `graphic.png`，按继承关系展示 round、branch、父节点、score、sandbox/wall time、失败主因、错误反馈摘要以及 card/diff 路径；该视图只读硬账本，不写回 summary，不参与调度，失败只记 warning。
- `prompts.py` 已更新为 branch-state/source-map 口径，不再把 `[ROUND DIRECTIVE]` 描述为 intent/operator 权威来源。
- 超时预算已优先使用 `branch_state/runtime_profile`；静态和质量门禁仍保留中性 `search_operator` 入参作为兼容层，但正常调度不会再用它选择建模路线。
- `runtime/codex_cli.py` 支持 `CODEX_CLI_<PHASE>_TIMEOUT_SECONDS` 或 `CODEX_CLI_TIMEOUT_SECONDS` 环境变量覆盖外部 Codex CLI 阶段超时，便于 smoke/debug；未设置时保持生产默认超时。

## 1. 设计结论

保留三种硬分支：`draft`、`debug`、`improve`。调度器只决定本轮属于哪种分支、为什么选择该分支、是否触发 EDA、运行预算以及必须阅读哪些证据路径；不再机械选择 `search_intent`、`search_operator` 或预设 `method_family`。具体建模路线由 Codex 在阅读任务技能文件、EDA、记忆卡片、历史代码和反馈后，在 `context_readiness.md` 中自洽选择。

关键取舍：

- `intent/operator/family` 不再是生成前控制量；只允许作为兼容字段、离线统计字段或赛后记忆卡片字段存在。
- 旧的算子注册表可以保留为“技能路线菜单 / 分析视图”，但不能再由调度器选中某个算子并写入提示词作为建议路线。
- 编码提示词从五块改为四块：硬规则、任务描述与任务契约、当前状态与记忆索引、必读/选读路径；EDA 只通过 source map 路径读取，不在 PART 2 内联。
- 不再内联技能和记忆摘录。技能与记忆通过来源路径表读取；提示词内只保留极短的状态摘要、卡片索引和路径说明。
- 每轮沙盒评测返回结果后写一个 Markdown 记忆卡片，作为最小记忆单元。记忆卡片同时包含同步写入的机械硬记录，以及可异步回填的 Codex 或本地摘要软画像。
- 静态门禁、质量门禁、超时管理、EDA、验证最佳候选提交必须保留，但其输入要从算子派生切换为从分支、运行画像、父卡片和赛后卡片派生。

## 2. 历史改造前证据

本节保留改造前审计证据，用于解释为什么要移除 prompt-facing 的机械 `intent/operator/family` 控制。它不是当前实现描述；当前正常路径已经改为仅分支调度，旧字段只作兼容、lineage、门禁入参和离线统计。

改造前代码证据：

- `runtime/branch_policy.py` 的 `choose_branch_for_round()` 表面返回分支，但实际还选择 `search_intent`、`search_operator`、`portfolio_action`、`portfolio_slot` 和算子/方法族反重复信息。
- `runtime/branch_policy.py` 的 `select_operator_for_round()` 曾是需要下线的主要机械调度入口；当前正常分支路径不再调用它。
- `runtime/branch_policy.py` 的旧 directive 曾会把 `Search intent` 和 `Suggested route` 暴露给编码 agent；当前编码提示词不再把这些字段作为建模路线建议。
- `runtime/prompt_pack.py` 生成五段式提示词，其中一块内联 selected skill 和 memory。
- `runtime/text_context.py` 会把 `[RETRIEVED MEMORY CONTEXT]` 内联到 pinned runtime packet。
- `runtime/skills.py` 按分支和意图组装紧凑技能包；`debug` 仍内联任务技能 + 失败技能，和草稿要求不一致。
- `runtime/validation.py` 写 `memory_bank/rounds.jsonl`、`failure_ledger.jsonl`、`operator_outcomes.json`、`prompt_context.md`，没有逐轮 Markdown 记忆卡片。
- `runtime/runner.py` 的静态/质量门禁使用 `search_operator` 与 `strict_score_first_required`，移除算子前必须替换这些输入。

运行证据：

- `real_run_examples/` 有 6 个任务、90 轮、79 轮有分数成功、9 轮 `code_execution_error`、2 轮 `static_gate_blocked`。
- 分支分布是 `draft=15`、`debug=10`、`improve=65`；说明三分支足够表达高层运行模式。
- 意图分布当时仍强烈存在：`portfolio_strengthen_best=22`、`strategy_replace=17`、`portfolio_expand_diverse=14` 等；说明历史样例不是当前 branch-only prompt-facing 调度。
- 六个编码提示词的 `part4_routed_knowledge` 约 3169-5018 tokens，其中技能和记忆占主要部分；取消内联摘录是真实的 token 优化点。
- 静态门禁阻断样例在 `real_run_examples/text-normalization-challenge-english-language/failed_rounds/round_014_static_gate_blocked/` 和 `real_run_examples/the-icml-2013-whale-challenge-right-whale-redux/failed_rounds/round_007_static_gate_blocked/`，这些流程必须继续可追溯且不得进入可提交前沿。

外部记忆设计证据：

- `/hpc_data/weizwang@weizwang/SuperML-Agent-inference-tts-mem/docs/task_memory_search_reproducible.md` 将任务记忆搜索定义为包在任意搜索算法外的一层任务内局部记忆封装。
- 关键原则是评测后更新、分数感知、父节点条件化、可持久化。新版记忆卡片设计应采用这些原则，但第一步先用轻量卡片索引和 Markdown 卡片落地，由 Codex 按索引自主选读，不引入向量设施或框架侧相关性检索器。

## 3. 当前单轮流程

每个任务每一轮按以下顺序执行：

1. 读取 `rounds_summary.json`、`graph/portfolio.json`、`memory_bank/card_index.jsonl`、失败账本和预算状态。
2. 调度器只硬判决 `branch`、`branch_state`、`branch_reason`、`runtime_profile`、`eda_mode`、`anchor_parent`、`debug_parent`、`source_policy`。
3. 运行需要的 EDA：
   - 第 0 轮或没有 EDA 存档时使用 early EDA。
   - deep EDA 不再作为独立 scheduler phase 机械启动；coding prompt 的 context acquisition 阶段允许 Codex 自主做 bounded/read-only 增量数据契约确认，并把事实写入 `context_readiness.md`。probe 目录必须来自 `--local-eda-data-root` 解析后的本地路径，默认根为 `/hpc_data/ktian/superml/inference_codex_cot4/mlebench-lite-val`，不能使用本地不可访问的 `/mnt/...` validation path。
4. 组装四块编码提示词。
5. Codex 先读取来源路径表中的必读路径，再写 `context_readiness.md`，最后写 `solution.py`。
6. 执行静态门禁检查；若可自动修复，保留一次静态门禁修复；若仍失败，归档 failed round 并写记忆卡片。
7. 执行沙盒验证；执行质量门禁；写提交或失败 artifact。
8. 生成或更新本轮记忆卡片。
9. 更新 graph、portfolio、branch summary、best vault、rounds summary。
10. 最终窗口执行验证最佳候选提交，不能提交最后一轮失败探索。

## 4. 分支策略 v2

### 4.1 分支字段

当前使用仅分支决策 schema。旧字段保留为兼容字段，但不能再控制提示词中的建模路线：

```json
{
  "schema_version": "branch_decision_v2",
  "round": 7,
  "branch": "improve",
  "branch_state": "score_plateau_improve",
  "branch_reason": "default_improve_after_two_scored_draft_seeds",
  "runtime_profile": "standard",
  "eda_mode": "none",
  "anchor_parent": {"role": "best", "round": 3, "commit": "...", "score": 0.01474, "card_path": "...", "code_path": "..."},
  "debug_parent": null,
  "best_candidate": {"round": 3, "commit": "...", "score": 0.01474, "card_path": "..."},
  "score_history": [{"round": 0, "branch": "draft", "score": 0.04798, "status": "success"}],
  "source_policy": {"must": ["task_skill", "eda_summary", "anchor_card", "anchor_code", "anchor_feedback"], "optional": ["eda_full", "top_cards", "top_code"]},
  "budget": {"remaining_budget": 32000, "elapsed_fraction": 0.25}
}
```

兼容字段：

- 旧 reader 仍依赖时保留 `search_intent`、`search_operator`、`portfolio_action`。
- 设置 `scheduler_controlled_route=false`。
- 对不能容忍缺字段的 reader，可使用中性值，例如 `search_intent="branch_only"` 和 `search_operator.name="agent_selected_after_context"`。
- 除原始 JSON 可选文件外，不要把这些字段写入编码提示词。

### 4.2 硬分支规则

使用有分数轮来计算提升与平台期；debug 和 LLM 基础设施失败不计入平台期改进尝试。

1. 第 0 轮：选择 `draft`，`branch_state=initial_seed`。
2. 在得到两个成功且相互独立的 draft-origin seed 之前：选择 `draft`，`branch_state=required_seed`。
   - 失败 draft seed 的 debug 修复若最终得到分数，则计作该 draft seed。
   - 独立性在赛后根据记忆卡片的 `method_family`、`method_keywords`、代码特征和分数判断；调度器不应预选方法族。
   - 如果 seed 已生成代码但失败，应先 debug，再考虑放弃，受 repair cap 限制。
3. 最新生成代码出现静态、运行或沙箱失败：选择 `debug`，`branch_state=repair_failure`，并带有唯一 `debug_parent`。
4. 重复超时或尚无任何分数前超时：选择 `debug`，`branch_state=timeout_recovery`，并设置 `runtime_profile=timeout_recovery`。
5. 两个 seed 已就绪且没有活跃失败后：默认选择 `improve`，`branch_state=frontier_improve`，并把当前 best 可提交/有分数节点设为 `anchor_parent`。
6. 连续四个有分数、非 debug 轮没有实质 best 提升：选择 `draft`，`branch_state=plateau_new_seed`。
   - `V38_PLATEAU_SCORED_ROUNDS_BEFORE_NEW_DRAFT` 已改成四轮，以匹配草稿要求。
   - 框架不会在新 draft 前机械启动 deep EDA；只在 branch decision 中给出 `deep_eda_advice`，由 Codex 在 context acquisition 阶段按需轻量确认文件契约。
7. 到最终预算窗口或剩余预算过低：选择 `improve`，`branch_state=final_audit`，并要求不做高风险建模变化。
8. LLM 瞬时或基础设施失败仍是运行系统失败，不是 ML/debug 失败。现有停止行为应保留。

### 4.3 父节点规则

- `draft`：没有父节点，不预填，不要求读取历史代码。可读取分数表和可选 seed/best 卡片，用于避免重复。
- `debug`：恰好一个父节点，即最新失败的已生成代码轮，或静态门禁阻断轮。父代码、父反馈和父卡片均为必读。允许且建议从父代码预填。
- `improve`：有一个明确锚点父节点，默认是进入本轮前的 best 可提交/有分数节点。运行时默认从该父节点代码预填或复制为 patch 基线；Codex 仍应额外多读若干高价值记忆卡片、高分且多样的候选代码和反馈，把其他节点的有效方法引入到锚点代码上。`context_readiness.md` 必须说明锚点父节点、引入了哪些其他节点思想、哪些改动是局部 patch、哪些是融合或替换。
- `final_audit`：可作为一种特殊 `improve` 状态，同样锚定 best 节点并允许预填，但目标是低风险加固所选候选，而不是自由搜索。

## 5. 无算子的运行画像

当前超时和 prompt-facing 运行预算以 `branch_state/runtime_profile` 为主，不再由生成前选中的 operator 决定：

```text
standard               普通分支轮
new_seed_score_first   尚无本路线分数的 draft seed 或平台期新 seed
debug_repair           普通失败修复
timeout_recovery       超时/OOM/无分数恢复
high_risk_parent       父卡片或代码特征显示为图像/音频/transformer/重型树模型路线
final_audit            验证最佳候选加固窗口
```

当前实现边界：

- `compute_validation_timeout()` 的调用侧已由 branch decision 提供 `branch_state/runtime_profile`、剩余预算和兼容 operator 字段；prompt-facing 路线不再来自 operator。
- `inspect_solution_contract()` 与 `detect_validation_quality_issue()` 仍可接收兼容 `search_operator`，用于风险 token、旧 route 声明和门禁兼容；生成前路线控制以 `runtime_profile`、父卡片特征、失败分类和生成后代码特征为主。
- 高风险路线的先拿分规则应继续从 `runtime_profile`、父卡片 `method_family`、失败分类和代码特征检查中派生。
- 现有超时上限与预算比例保持保守兼容。

## 6. 四块编码提示词

### 6.1 第 1 块：硬规则

内容：

- 系统提示词硬规则；
- 上下文优先协议；
- 沙箱与资源卡；
- 输出契约；
- 运行预算和静态门禁约束。

这里不应出现分支特定的建模路线。

### 6.2 第 2 块：任务描述与任务契约

内容：

- 过滤后的用户任务；
- 从 metadata 派生的任务事实；
- 从用户任务和 EDA 提取的任务契约，不从内联任务技能中提取；
- 不内联 EDA card；EDA 结论通过第 4 块 source map 中的 `latest_eda_summary` 路径读取。

不要内联任务技能章节。完整任务技能从 source path 读取。

### 6.3 第 3 块：当前状态与记忆索引

这一块由框架机械生成并保持紧凑。目标 1000-1800 tokens。

必含内容：

- 当前轮号、任务目录、指标方向、剩余预算；
- 当前分支和固定分支解释：
  - `draft`：独立强 seed，没有父节点，避免重复已有有分数 seed 路线；
  - `debug`：修复唯一失败父节点；
  - `improve`：锚定当前 best 父节点做 patch，同时允许吸收其他节点的有效方法；
- 分支原因和分支状态；
- 分数表：轮号、分支、状态、分数、commit、近期轮和最佳候选的卡片路径；
- best candidate 卡片路径和一行元数据；
- `improve` 分支下的锚点父节点卡片、代码、反馈路径；
- debug 分支下的父卡片、父代码、父反馈路径；
- early EDA 状态、`latest_eda_summary` 路径，以及完整 EDA findings 的按需扩展路径；
- 记忆卡片索引行，而不是完整卡片正文。

避免内容：

- `Search intent`；
- `Suggested route`；
- 选中算子卡；
- 机械 avoid-operator/family 禁令。

### 6.4 第 4 块：路径清单

每个路径必须包含标签、路径、必读/选读状态，以及它为什么重要。任务内 artifact 使用任务相对路径，外部资源使用绝对路径。

必读策略：

| 分支                                | 必读路径                                                                                 |
| ----------------------------------- | ---------------------------------------------------------------------------------------- |
| `draft`                             | 任务技能文件、失败预防技能文件、`latest_eda_summary`                                     |
| `improve`                           | 任务技能文件、`latest_eda_summary`、锚点父记忆卡片、锚点父代码、锚点父验证反馈           |
| `debug`                             | 失败预防技能文件、`latest_eda_summary`、父记忆卡片、父代码、父验证/静态门禁反馈          |
| `final_audit` 这种 `improve` 状态   | 任务技能文件、`latest_eda_summary`、最佳记忆卡片、最佳代码、最佳验证反馈                 |

选读路径：

- 完整用户任务提示词；
- 分支决策 JSON；
- `memory_bank/cards/`；
- 供 Codex 自主选读的记忆卡片目录和索引；
- 最佳候选代码和反馈；
- graph/portfolio JSON；
- 用于审计的 rounds/failure ledger；
- 若同时存在摘要和发现文件，则列出完整 EDA findings JSON/MD。

如果必读路径缺失，提示词应要求 Codex 在 `context_readiness.md` 中记录该事实，并继续使用任务描述、EDA 和本地数据检查。

## 7. 技能路由

当前技能路由以 source policy 为核心：

- 返回 source path 和标签，而不是紧凑技能正文。
- 像当前一样把外部技能文件的净化副本持久化到 `context_sources/`，但按分支列入必读路径。
- 只有框架规则性质的运行时加固守卫可以保留内联；不要内联技能摘录。

分支规则：

- `draft`：必须读取任务技能 + 失败预防技能。原因：draft 会写新代码，应从第一版实现就规避已知失败陷阱。
- `improve`：只必须读取任务技能。原因：方法选择应扎根于任务特定高收益配方；除非正在 debug，否则失败信息通过记忆/失败卡片提供。
- `debug`：只必须读取失败预防技能。原因：debug 应修复链接的失败，而不是根据任务技能重新设计路线。

EDA 技能仍仅用于 EDA 生成阶段，不参与编码提示词技能路由。

## 8. 记忆卡片系统

### 8.1 文件

当前一等卡片存储：

```text
memory_bank/
  cards/
    round_000_82366cde.md
    round_001_static_gate_blocked.md
  diffs/
    round_004_vs_anchor_003.md
  card_index.jsonl
  card_state.json
  prompt_context.md        # 兼容派生视图，不再是提示词权威来源
  rounds.jsonl             # 兼容/调试
  failure_ledger.jsonl     # 兼容/调试
```

`card_index.jsonl` 是调度器和来源路径表使用的机器索引。`cards/*.md` 是人类可读、提示词可读的记忆单元。`diffs/*.md` 是以父节点到当前轮为主轴的方法差异记录，供后续 `improve` 和经验文档提炼使用。

### 8.2 卡片 schema

每张卡片建议 700-1100 tokens，硬上限约 1200 tokens。卡片正文必须使用英文，便于跨任务复用和后续 Codex 直接选读。使用稳定标题：

```md
# Round 003 Memory Card

## Meta
- schema_version: memory_card_v2
- task: leaf-classification
- round: 3
- branch: improve
- branch_state: frontier_improve
- commit: d72a3fe7
- status: success
- score: 0.014744426143768027
- metric_direction: lower
- sandbox_run_time: 312.4
- risk_tags: none
- artifacts: solution=commits/d72a3fe7/solution.py; feedback=commits/d72a3fe7/validation_feedback.txt; context=commits/d72a3fe7/context_readiness.md; post_code_memory_summary=commits/d72a3fe7/post_code_memory_summary.md

## Method Portrait
- soft_summary_status: completed_local
- method_family: descriptor_shrinkage_discriminant_ensemble
- core_components: leaf descriptors, shrinkage LDA/QDA, calibrated ensemble, logloss clipping
- method_summary: A compact descriptor ensemble predicts leaf classes using shrinkage discriminants with probability calibration and clipping.
- method_profile: This attempt uses shrinkage discriminant models over compact leaf descriptors, then calibrates and clips probabilities for logloss stability. It is cheap to rerun, keeps a deterministic fallback, and should be compared against heavier image-feature routes before reuse. The main risk is overfitting descriptor artifacts or underusing raw-image signal.
- reuse_risk: Reuse the descriptor/calibration scaffold for cheap variants; avoid adding wide descriptors without a proxy gain.

## Result Signal
- validation_signal: Status=success; score=0.014744.
- cost: low_cost; sandbox_run_time=312.4
- risk: none
```

必需硬字段：

- round、branch、branch_state；
- commit 或 failed artifact path；
- 验证状态、score、指标方向；
- sandbox run time 和 risk tags；
- solution、feedback、context readiness、result JSON 的 source path。

软字段：

- `card_method_summary` / `method_summary`：写完代码后对当前 solution.py 的 1-2 句高密度描述；
- `card_method_profile` / `method_profile`：模型类别、特征/表示、验证/选择逻辑、fallback 和复用/风险信号；
- `card_core_components`：按规范化后稳定去重的关键组件；
- `card_reuse_risk`：后续轮应复用或避免的零阶经验。

### 8.3 卡片生成

最小可用版本除非开启支持调用，否则应避免额外 LLM 调用：

1. 必须在沙盒返回结果后写入记忆卡片。静态门禁阻断、未进入沙盒的轮，也必须在阻断结果确定后写入卡片。
2. 硬记录先同步写入，来源包括 `result`、`round_summary`、`validation`、`solution_contract`、`effective_lineage`、`code_features` 和卡片索引。
3. 软总结可以异步写入或回填，避免阻塞主运行流程。异步任务完成后更新同一张卡片和 `card_index.jsonl` 的软字段摘要；如果异步失败，卡片仍保留完整硬记录并标记 `soft_summary_status=failed`。
4. 软总结从以下来源构建：
   - Codex 写完 `solution.py` 后单独写入的 `post_code_memory_summary.md`；
   - 本地 `round_summary`，优先读取 `card_method_profile/method_profile`；
   - 验证诊断；
   - 代码特征推断；
   - 失败分类。
5. 如果 `V33_SUPPORT_CALLS_DEFAULT` 或新开关已启用，可使用小型总结调用生成缺失画像；否则使用确定性本地 fallback。两种路径都必须保留同步硬字段。
6. 对静态门禁阻断和未进入沙盒的轮，也在 `memory_bank/cards/` 写卡片，并复制或指向 `failed_rounds/...`。

卡片硬记录以沙盒或静态门禁结果为准。若未来引入异步验证，可先写临时硬记录，再回填 score/status；软栏目始终允许异步生成和回填。

### 8.4 方法差分层

有父节点的轮应自然写出方法差分。`improve` 的主差分是 `anchor_parent -> current`；`debug` 的主差分是失败父节点到修复后节点；`draft` 没有父节点，通常不写差分，除非显式和 best 做审计比较。

差分文件建议写入：

```text
memory_bank/diffs/
  round_004_vs_anchor_003.md
  round_005_vs_debug_parent_004.md
```

差分内容应包含：

- `Meta`：父节点/当前节点 round、commit、card path、branch；
- `Action`：Codex 写完 patch 后软填写的具体代码/逻辑改动；
- `Reason`：Codex 写完 patch 后软填写的改动理由；
- `Result`：沙盒后机械填写 score/status、指标方向、方向对齐 delta、`score_change_label` 和 runtime。

方法差分不再内嵌大段 code diff，也不重复写 Better/Worse/Reuse/Avoid。`score_change_label` 是正向/负向优化的唯一依据；卡片负责记录本轮零阶画像，差分负责说明“相对父节点到底改了什么、为什么改、结果如何”。

### 8.5 选读策略

不引入向量设施，也不要求框架替 Codex 预先决定“最相关”卡片。框架只提供紧凑索引、排序视图和路径说明，让 Codex 根据当前分支目标自主选读。

来源路径表和紧凑状态块应列出：

- 最佳卡片，也就是普通 `improve` 的锚点父卡片；
- debug 分支下的父卡片；
- 最近 3 张卡片；
- 分数排名前三的有分数卡片；
- 正向 delta 排名靠前的卡片；
- 近期失败、静态门禁、超时卡片；
- 平台期或新 `draft` 多样性卡片，依据方法关键词和代码特征选择。

默认不要把完整记忆卡片注入提示词。改为：

- 第 3 块包含一行式行：round、branch、score、status、method_family、卡片路径、入选原因。
- 第 4 块根据分支把完整卡片路径列为选读或必读。
- 对 `improve`，提示词应明确说明本轮以锚点父节点为 patch 基线，并鼓励 Codex 至少额外选读若干高价值卡片；如涉及融合、替换或平台期诊断，还应进一步选读相应代码和反馈。

这实现了任务记忆搜索的封装思想，同时控制提示词长度。

### 8.6 后续父节点条件化记忆

卡片稳定后，可选增加：

```text
memory_bank/parent_docs/
  parent_round_003.md
memory_bank/pending_parent_updates.jsonl
memory_bank/task_memory_doc.md
```

这遵循外部任务记忆搜索说明：子节点经验先成为父节点条件化文档的待回填更新，只有当该父节点再次被选择时才消费。在本框架中，`improve` 也锚定 best 父节点，因此 parent-conditioned doc 对 `improve` 和 `debug` 都有价值：`improve` 用它沉淀围绕 best 的有效补丁和无效补丁，`debug` 用它沉淀具体失败父节点的修复经验。不要让这一层阻塞仅分支重构。

## 9. 模块级实现记录与验收边界

本节记录已落地的模块改造和后续检查边界，不是必须逐项执行的待办清单。新增字段或 artifact 语义若继续变化，应同步更新本节和 `docs/artifact_schema.md`。

### 阶段 0：用轻量检查冻结当前行为

当前最小检查仍是：

- `python -m py_compile evaluate_codex.py runtime/*.py`
- 对 `real_run_examples/` 做 artifact 摘要脚本，检查 90 轮、分支/状态计数、best/portfolio 一致性。
- 提示词打包冒烟检查：读取已有 `context_sources/*coding_prompt_after_pack.json`，检查 `critical_marker_failures == []`。
- 关键轮分支回放快照：初始 seed、失败后 debug、平台期新 `draft`、静态门禁阻断、最终审计窗口。

### 阶段 1：记忆卡片

文件：

- 已新增 `runtime/memory_cards.py`。
- `runtime/runner.py` 于沙盒验证返回结果之后调用；静态门禁阻断轮则在阻断结果确定后调用。硬记录同步写入，软总结异步生成和回填。
- 只有当集中管理更清晰时，才在 `runtime/memory_store.py` 扩展卡片路径辅助函数。

当前实现：

- 写 `cards/*.md`、`card_index.jsonl`、`card_state.json`。
- 对有父节点的轮写 `diffs/*.md` 骨架；`improve` 使用锚点父节点，`debug` 使用失败父节点。
- 卡片先写硬栏目，软栏目允许显示 `pending`；异步任务完成后更新为 `completed` 或 `failed`。
- 如有需要，可用离线脚本从 `real_run_examples/` 回填样例卡片，但不要把生成样例视为运行时源代码。
- 保留现有 `rounds.jsonl`、`prompt_context.md`、`operator_outcomes.json` 作为兼容视图。

验收：

- 每个已提交轮和静态门禁失败轮都有卡片。
- 沙盒返回后卡片硬字段和 artifact 路径已经可用；软栏目可异步补齐。
- 卡片索引能识别最佳卡片、近期卡片、失败卡片和 debug 父卡片。
- 普通 `improve` 轮能写出 `anchor_parent -> current` 的差分骨架。

### 阶段 2：仅分支决策 schema

文件：

- `runtime/branch_policy.py`。
- `runtime/constants.py` 中的分支状态和运行画像常量。

当前实现：

- 已新增 `choose_branch_state_for_round()`，`choose_branch_for_round()` 是兼容 wrapper。
- 正常分支选择路径停止调用 `select_operator_for_round()`。
- 旧算子函数保留为兼容/分析 helper。
- `V38_PLATEAU_SCORED_ROUNDS_BEFORE_NEW_DRAFT` 当前为四轮平台期阈值。
- 决策写出 `branch_state`、`branch_reason`、`runtime_profile`、`anchor_parent`、`debug_parent`、`source_policy`、`score_history`、`best_candidate`。
- 旧字段只为兼容存在，并标记 `scheduler_controlled_route=false`。

验收：

- 第 0 轮和第二个 seed 仍为 `draft`。
- 最新生成代码失败会选择带一个父节点的 `debug`。
- 四个有分数、非 debug、无提升轮后会选择 `draft`。
- seed pool 就绪后默认选择 `improve`，并把进入本轮前的 best 节点写入 `anchor_parent`。
- 编码提示词不包含选中算子或建议路线文本。

### 阶段 3：来源路径表优先提示词

文件：

- `runtime/prompt_pack.py`。
- `runtime/text_context.py`。
- `runtime/skills.py`。
- `prompts.py` 中把 `[ROUND DIRECTIVE]` 视作 branch-state/source-map 权威来源的措辞。

当前实现：

- 使用四块打包器 `v50_four_part_branch_memory_source_map`。
- 从编码提示词组装中移除 `build_v35_selected_skill_card()`。
- 停止向 pinned runtime packet 追加 `[RETRIEVED MEMORY CONTEXT]`。
- 通过 `build_v35_round_state()` 和 `build_v35_context_source_map()` 生成第 3 块状态摘要和第 4 块来源路径表；不新增单独的向量或检索设施。
- 让来源路径表支持标签、必读标志、路径和说明。
- 将 `latest_eda_summary` 列为必读；完整 `eda_findings.md/json` 和 `eda_insights.jsonl` 作为按需扩展路径。
- 将分支必读技能路径放入必读清单，而不是选读清单。

验收：

- 打包后的编码提示词有四个命名部分。
- `section_tokens.part4_source_paths` 替换旧的 `part4_routed_knowledge`。
- 编码提示词中不出现 `[SELECTED SKILL CONTEXT]` 标记。
- 编码提示词中不出现大块 `[RETRIEVED MEMORY CONTEXT]`。
- `critical_marker_failures == []`。

### 阶段 4：runner 父节点与预填语义

文件：

- `runtime/runner.py`
- `runtime/skills.py` 中的 `prefill_active_solution_from_incumbent()`
- `runtime/text_context.py` 中的 parent/best 路径逻辑

当前实现：

- `draft`：永不预填，父节点路径不进入必读。
- `improve`：默认以 `anchor_parent` 的最佳代码预填或复制为 patch 基线；高分候选代码、相关记忆卡片和反馈作为鼓励选读路径，用于把其他节点的有效方法引入锚点代码。
- `debug`：从 debug 父节点预填；父卡片、父代码、父反馈必读。
- 确保 `context_readiness.md` 必须解释 Codex 基于哪个锚点父节点 patch、引入了哪些其他节点方法，以及为何这些改动比直接保留锚点更可能有效。

验收：

- `improve` 轮必须有 `anchor_parent`，默认从锚点父代码开始 patch，并在 `context_readiness.md` 记录锚点代码已读和外部方法来源。
- `improve` 轮结束后应写出相对锚点父节点的 diff artifact。
- `debug` 仍修复具体失败代码。

### 阶段 5：静态门禁与超时输入迁移

文件：

- `runtime/validation.py`
- `runtime/branch_policy.py`
- `runtime/runner.py`

当前实现边界：

- 运行预算和 prompt-facing route control 使用 `runtime_profile`、`branch_state`、父卡片特征和生成后的 `code_features`；`search_operator` 仍可作为兼容门禁入参存在。
- 静态门禁仍阻断缺失 `DATA_DIR`、缺失 `submission.csv`、硬编码外部路径、不安全下载、副输出预测/模型文件、重型代码缺预算守卫等问题。
- 质量门禁仍检测常量/兜底逻辑主导的假成功。
- 超时计算使用分支、运行画像和剩余预算。

验收：

- 现有静态门禁样例仍会被阻断。
- 超时恢复提示词仍强制先拿分和随时可提交。

### 阶段 6：artifact 与 portfolio 迁移

文件：

- `runtime/portfolio.py`
- `runtime/validation.py`
- `runtime/memory_store.py`
- `docs/artifact_schema.md`

当前实现与后续边界：

- `graph/nodes.jsonl` 应存储：
  - raw branch decision v2；
  - 从卡片/摘要来的赛后 `method_family`；
  - 卡片路径；
  - 锚点父节点谱系；
  - debug 父节点谱系。
- `portfolio.json` 保持可提交的有分数前沿候选，并带有卡片路径和赛后方法族。
- `graphic.png` 作为派生监控视图，由 `rounds_summary.json`、`nodes.jsonl`、`events.jsonl`、`memory_bank/rounds.jsonl` 和 `card_index.jsonl` 重建；`draft` 轮不从兼容 parent 字段画继承边。
- `operator_outcomes.json` 降级为兼容/调试视图。若未来需要更干净的聚合视图，可从 cards/nodes 派生 `memory_bank/method_outcomes.json`；当前尚未实现该文件。
- `rounds_summary.json` 保留旧字段，同时新增或透传 `memory_card_path`、`memory_diff_path`、`branch_state`、`runtime_profile`、`anchor_parent` 等 compact 信息。

验收：

- 旧读取器仍可解析 `rounds_summary.json`、`graph/nodes.jsonl`、`portfolio.json`。
- 新读取器可从卡片和 graph 重建分支决策和提示词来源路径。
- 打开任务目录根部 `graphic.png` 可审计搜索树、分数、耗时和错误信号；`python search_graph_monitor.py <task_dir> --watch` 可对已有 run 独立刷新。

### 阶段 7：文档与样例

文件：

- `docs/framework_handoff_guide.md`
- `docs/artifact_schema.md`
- 本设计实现文档
- 若实现复杂度增长，可选新增 `docs/memory_card_schema.md`

当前边界：

- 非 deprecated 交接指南、artifact schema 和本设计文档必须与当前代码保持同步。
- 冒烟 run 的具体卡片样例留在 run 目录中，不复制为顶层权威文档。
- 当前 artifact 权威语义和未来可选 artifact 应明确分开，避免把可选脚本写成已存在脚本。

## 10. 验证策略

最小本地检查：

```bash
python -m py_compile evaluate_codex.py runtime/*.py
```

提示词单元/冒烟检查：

- 从一个现有样例任务和伪 metadata 构建编码提示词。
- 断言四个部分存在。
- 断言没有选中技能或记忆摘录标记。
- 断言来源路径表的必读路径包含分支要求的技能和 `latest_eda_summary`。
- 断言 `improve` 来源路径表包含锚点父卡片、锚点父代码和锚点父反馈。
- 断言六个样例的提示词 tokens 低于旧 prompt pack，重点来自移除旧第 4 块。

分支策略检查：

- 使用合成轮次历史覆盖：
  - 第 0 轮；
  - 一个成功 draft seed；
  - 最新代码执行错误；
  - 有生成代码的静态门禁阻断；
  - 两个 seed + 默认 `improve` + 锚点父节点；
  - 四个有分数但无提升的轮；
  - 最终审计窗口。

记忆卡片检查：

- 为成功、代码执行错误、静态门禁阻断、无分数超时写卡片。
- 解析卡片索引，解析最佳、近期、失败和 debug 父卡片。
- 确保每张卡片都有 artifact 路径和指标方向。
- 为普通 `improve` 写 `anchor_parent -> current` 差分，并检查 delta、代码 diff 摘要和外部方法来源字段。

集成冒烟：

```bash
./run_selected_tasks.sh leaf-classification --num-rounds 1 --concurrency 1 --sandbox-run-budget 3600
```

完整行为验证需要 sandbox、Codex CLI、任务技能、EDA 技能、错误技能和数据路径。

## 11. 风险与缓解

- 风险：移除算子指导后，Codex 可能选择更弱或重复的路线。
  - 缓解：强制读取任务技能、`latest_eda_summary`、分数表、卡片索引，并把完整 EDA findings / insight store 作为按需扩展路径；要求 `context_readiness.md` 给出路线理由。
- 风险：移除内联技能后，模型可能不读必需文件。
  - 缓解：来源路径表必读契约、`context_readiness.md` 已读文件清单、提示词打包关键标记、后续 `context_readiness.md` 检查器。
- 风险：静态/超时门禁失去来自算子的成本信号。
  - 缓解：使用 `runtime_profile`、父卡片方法/风险提示和生成后代码特征分析。
- 风险：`improve` 过度锚定 best 节点，可能只做保守小补丁，错过结构性替换机会。
  - 缓解：平台期仍通过 `draft` 产生新 seed；普通 `improve` 虽锚定 best，但提示词鼓励选读高分多样候选、记忆卡片和反馈，把其他节点方法引入锚点代码。若需要结构性替换，`context_readiness.md` 必须说明替换范围和相对锚点的预期收益。
- 风险：`improve` 差分把其他节点方法归因到锚点父节点，导致经验来源混淆。
  - 缓解：diff artifact 必须列出“引入方法来源”，包括卡片路径、代码路径或反馈路径；软总结中区分锚点 patch 与外部方法融合。
- 风险：记忆卡片变得冗长。
  - 缓解：硬上限、稳定标题、提示词中只放卡片索引行，完整卡片通过路径读取。
- 风险：兼容字段混淆未来代码。
  - 缓解：把旧字段标记为仅兼容，并从面向提示词的构建器中移除。

## 12. 完成清单

当前完成口径如下；若未来代码偏离这些条件，应同步修正文档或重新打开设计：

- 分支决策 JSON 在行为和提示词表面都是仅分支调度。
- `select_operator_for_round()` 不再位于正常编码路径上。
- 编码提示词有四个部分，并且不内联技能/记忆摘录。
- 分支特定来源路径表规则与草稿一致。
- 普通 `improve` 决策都有 `anchor_parent`，并以进入本轮前的 best 节点作为 patch 基线。
- `latest_eda_summary` 是必读路径，完整 EDA findings / EDA insight store 是按需扩展路径。
- `context_readiness.md` 是代码前读源/路线审计 artifact；`post_code_memory_summary.md` 是代码后 memory 软总结 artifact，供 card/diff 软字段优先读取。
- 每个已评测轮或静态门禁阻断轮都会写记忆卡片。
- 每个有父节点的 `improve`/`debug` 轮都会写方法差分 artifact。
- 调度器把记忆/卡片用作建议性证据，而不是生成前算子标签。
- 静态门禁、质量门禁、超时恢复、EDA、graph/portfolio 和验证最佳候选提交仍可工作。
- `docs/` 反映已实现的 artifact 语义，并且能交接给没有先验知识的新 agent，不依赖缺失文件。
