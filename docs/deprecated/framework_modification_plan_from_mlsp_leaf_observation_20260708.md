# 基于 MLSP/Leaf 10 轮观察的框架修改计划

来源观察文档：`docs/mlsp_leaf_10round_observation_20260707.md`

本文档记录当前框架的下一步修改方案。目标是提高多轮搜索的有效性、降低无效 token/文件膨胀，并让 Codex 在需要时能自主确认数据契约，而不是由框架机械判断。

实施状态：2026-07-08 已落地首版。主要实现点包括：`score_feedback` 顶层注入、debug/anchor source map 补齐、Codex context acquisition 自主 bounded deep EDA、统一 `memory_bank/eda_insights.jsonl` 结论库、英文 memory card 的 cost/reward/risk/sibling 信号、结构化 method diff，以及 compact `rounds_summary.json`。

## 1. 升级 Memory Card、Method Diff 和任务经验层

### 问题

当前 memory card 和 diff 已经能记录硬事实，但软总结过于模板化：

- `method_profile` 往往只复述 branch、status、score、static warning。
- diff 的 `Advantages` / `Risks` 经常是模板值，例如 `unknown` 或 `none`。
- 高价值变化没有被提炼成可复用经验，例如：
  - MLSP 的 tolerant numeric-token parser 修复了 sibling parser failure。
  - Leaf Round 8 的 `morph_only`、PCA-regularized QDA、pairwise blend 带来大幅提升。
  - Leaf Round 6/7 高耗时但边际收益极低或零收益，应成为成本风险信号。

### 修改方案

1. 在代码生成后、sandbox 前，让 Codex 写出 `Post-Code Memory Summary`：
   - `card_*` 字段描述本轮 solution.py 的零阶画像：核心方法、特征、模型、候选顺序、blend/stack、calibration、runtime/fallback 和复用/风险。
   - `diff_action` / `diff_reason` 描述相对 anchor/debug parent 的一阶改动；无父节点则写 `none`。
2. sandbox 返回后写 memory card hard record，再异步补充 card soft summary；有父节点时写 diff 的硬 Result。
3. method diff 改为结构化经验信号，至少包含：
   - `Action`: Codex 软填写的具体改动。
   - `Reason`: Codex 软填写的改动理由。
   - `Result`: sandbox 后硬填写的分数、状态、方向对齐 delta、`score_change_label`、sandbox time。
   - 不再写 Better/Worse/Reuse/Avoid/Next；正负优化只看机械计算的 `score_change_label`。
4. 对 sibling variants 做横向归纳：
   - 不能只看单轮 parent diff。
   - 多次 best-anchor improve 失败后，如果后续成功，需要比较成功 variant 与失败 variant 的决定性差异。
   - 多次高成本低收益后，应形成任务级 avoid/cheaper-gate 信号。

### 涉及模块

- `runtime/memory_cards.py`
- `runtime/memory_store.py`
- `runtime/validation.py`
- `runtime/text_context.py`
- `docs/artifact_schema.md`

### 验收标准

- Memory card 全文保持英文。
- 成功、失败、低收益、高成本四类信号都能在 card/diff 中表达。
- Leaf Round 8 这类结果应被总结为“high-cost high-reward”，而不是 `risk: none`。
- Leaf Round 7 这类结果应被总结为“high-cost zero-gain avoid/cheaper-gate signal”。

## 2. 强化 Branch Decision 到 Coding Prompt 的信号传递

### 问题

观察中出现几类调度信号丢失或弱化：

- `debug_parent_card` 被 policy 声明为 must-read，但 source map 有时没有具体 card path。
- `Portfolio slot` 顶部展示 best candidate，却把 `branch`、`run_time`、`wall_time`、`memory_card_path`、`memory_diff_path`、`anchor_parent` 渲染为 `null`。
- `score_feedback` 中的强约束，例如 `latest_not_material_improvement`、`0.0 delta`、`required_response`，没有稳定出现在 prompt 顶层。

### 修改方案

1. 修复 source map 构造：
   - debug round 必须把 failed/debug parent card、code、feedback 全部列为 must-read。
   - improve round 必须把 best anchor card、code、feedback、diff 列为 must-read 或强 optional。
2. 修复 `Portfolio slot` 渲染：
   - 从 branch decision / graph node / memory card index 补齐 best candidate 元数据。
   - 顶部展示必须和后文 source map 一致。
3. 将 `score_feedback` 作为 prompt 顶层控制信号：
   - 若最近一轮无实质提升，应显式要求说明 material-gain 依据，或者切换更高 ceiling 路线。
   - 若连续同 family 高成本低收益，应要求 cheaper proxy、候选收缩或换源。
4. Improve 继续锚定 best 节点，但不等于盲目重复同类局部 tuning：
   - 可以 patch best。
   - 可以引入其他节点的方法。
   - 每次 improve 后自然写出 anchor diff。

### 涉及模块

- `runtime/branch_policy.py`
- `runtime/text_context.py`
- `runtime/prompt_pack.py`
- `runtime/portfolio.py`
- `runtime/memory_cards.py`

### 验收标准

- Debug round 的 prompt 中不再出现 `debug_parent_card: <missing>`，只要对应 card 已存在。
- `Portfolio slot` 不再丢失 best 节点的 runtime/card/diff/anchor 元数据。
- `latest_not_material_improvement` 必须在 coding prompt 顶层可见。
- Improve round 的 `context_readiness.md` 应明确回应 scheduler 的 score feedback。

## 3. 治理 Runtime Budget 和 Artifact 膨胀

### 问题

观察显示：

- Leaf 多轮 improve 长时间接近内部预算，且有高耗时零收益或低收益样本。
- `rounds_summary.json` 正在变成大对象 dump，包含大段 validation log 和完整 code，容易造成误读和 token 膨胀。
- 旧式产物已经清理了一部分，但 trace/full diff/summary retention 还没有明确策略。

### 修改方案

1. 继续按 sandbox time 计算 time budget。
2. 每轮 prompt 必须注入当前 active remaining budget，并要求 `solution.py` 内部 deadline 不大于 pinned internal budget。
3. 当剩余 sandbox budget 收缩时，prompt 应要求：
   - 候选数量收缩。
   - proven core candidate 前置。
   - heavy optional candidate 后置或跳过。
4. 调整 static runtime guard 与 memory 风险表达：
   - static warning 不一定阻止提交，但必须进入 card/diff 风险。
   - 高耗时高收益、高耗时低收益、高耗时零收益应分开标记。
5. `rounds_summary.json` 瘦身：
   - 保留 compact round metadata、score、status、commit、paths、budget、gate。
   - 大段 validation log、full code、trace 只保留路径引用。
   - 兼容读取旧字段，但新写入避免继续膨胀。
6. 已停产旧产物保持停产：
   - `memories/MEMORY_<task>.md`
   - `memory_bank/MEMORY_FULL.md`
   - `commits/<hash>/planning.md`
   - `failed_rounds/*/planning.md`

### 涉及模块

- `runtime/runner.py`
- `runtime/validation.py`
- `runtime/text_context.py`
- `runtime/memory_store.py`
- `runtime/constants.py`
- `docs/artifact_schema.md`

### 验收标准

- 新 run 的 `rounds_summary.json` 不再随 round 线性吞入完整 code 和长 validation log。
- Leaf Round 9 这类预算收缩行为应稳定出现：anchor 旧预算大于 pinned budget 时，prompt 和代码都服从当前 pinned budget。
- 新 run 不再生成已退役旧产物。

## 4. 增加 Codex 自主 Deep EDA 和统一 EDA 结论库

### 问题

当前 deep EDA 如果由框架机械判定，容易出现两个问题：

- 不需要时浪费 token/时间。
- 真正需要 debug 时，模型反而缺少确认真实文件格式、字段、header、shape、样例值的权力。

MLSP parser failure 说明：模型需要在 debug 阶段有权确认具体文件契约，例如 `rec_id` header、非规则宽度文本表、label manifest 格式。

### 修改方案

1. 将 deep EDA 放进 coding prompt 后的 context acquisition 阶段：
   - 在 `CONTEXT-FIRST PROTOCOL` 中说明：写 `context_readiness.md` 前，Codex 可以自主执行 bounded/read-only deep EDA。
   - 框架不机械决定是否 deep EDA，只提供工具、边界、预算和记录格式。
2. Deep EDA 的定位是“信息确认”，不是建模实验：
   - 允许：列文件、读 schema、head/sample、小规模统计、确认 train/test/submission 对齐、检查失败文件格式。
   - 禁止：训练模型、跑 validation、超参搜索、写预测缓存、创建跨轮中间产物。
3. Deep EDA 必须写入 `context_readiness.md`：
   - 记录触发原因。
   - 记录检查了哪些文件。
   - 记录确认出的 data contract。
   - 记录对代码实现的直接影响。
4. 初始 EDA 和 deep EDA 共同维护统一 EDA 结论库：
   - 机器可读权威库继续使用 `memory_bank/eda_insights.jsonl`。
   - deep EDA 的新增事实还会追加到 task-local `early_eda/round_0/eda_findings.md`，作为人类可读的累计 EDA 状态；追加使用 marker 去重，避免 replay/重跑重复写入。
   - 每条 insight 至少包含：
     - `source`: `initial_eda` 或 `deep_eda`
     - `round`
     - `trigger`
     - `files_checked`
     - `finding`
     - `confidence`
     - `coding_implication`
     - `created_at`
   - Prompt pack 读取 compact EDA conclusion，不重复塞完整 EDA 文本。
5. 对 debug round 提升 deep EDA 权重：
   - 如果 validation failure 指向 parsing/schema/file contract，prompt 应明确鼓励先做 bounded deep EDA。
   - 失败类一旦确认，应进入 EDA insight 和 memory card，后续轮次作为硬结论。

### 涉及模块

- `runtime/text_context.py`
- `runtime/eda.py`
- `runtime/runner.py`
- `runtime/memory_store.py`
- `runtime/validation.py`
- `docs/artifact_schema.md`

### 验收标准

- Coding prompt 明确允许 Codex 在 context acquisition 阶段自主 deep EDA。
- Deep EDA 不训练、不验证、不写预测缓存。
- Debug round 可通过 deep EDA 确认文件契约，并把结论写入 `context_readiness.md` 和 EDA insight store。
- 初始 EDA 与 deep EDA 的结论能共同被后续 prompt 检索使用。

## 实施顺序

1. 先改 prompt/source-map 层：修复 branch decision 元数据、score feedback、debug parent card、deep EDA 协议。
2. 再改 memory 层：升级 card/diff schema 和软总结生成方式。
3. 再改 artifact 层：瘦身 `rounds_summary.json`，补 retention 规则。
4. 最后跑小规模 smoke：
   - 一个 parser-debug 任务，验证 deep EDA 能确认文件契约。
   - 一个 improve 任务，验证 best-anchor card/code/feedback/diff 必读。
   - 一个高耗时任务，验证 sandbox budget 收缩能传递到 prompt 和代码。

## 非目标

- 不引入向量检索设施；memory card 继续由 Codex 按 source map 选读。
- 不让 deep EDA 变成自动建模实验。
- 不把任务特化规则硬编码进框架；任务经验应进入 memory/EDA insight，而不是写死在调度逻辑里。
