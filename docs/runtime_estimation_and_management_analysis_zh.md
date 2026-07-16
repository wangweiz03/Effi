# 时间估算与管理机制分析报告

## 1. 报告范围

本报告分析 BSPM Codex v4 当前的方案时间估算与运行时间管理机制，重点回答以下问题：

1. 为什么 draft 已设置约 1 小时的工作量目标，重任务仍会运行到 3 小时 external timeout。
2. 是否应在保持 3 小时硬上限的同时，让 draft 更倾向于低耗时但仍有竞争力的完整方案。
3. 如何利用已经完成的在线运行时间，提高 improve 阶段的估算可靠性。
4. 如何避免把“轻量化”错误实现为低质量 baseline、冻结特征方案或无意义 fallback。

原始逐轮数据见 [runtime_estimates_test3_tries4_7.csv](runtime_estimates_test3_tries4_7.csv)。该表覆盖 `test3-tries4`、`test3-tries5`、`test3-tries6` 和 `test3-tries7` 中所有带 commit 归档 `context_readiness.md` 的轮次。

## 2. 设计原则

建议继续坚持以下分层原则：

- external validation timeout 是容错硬上限，可以维持 3 小时，用于吸收环境波动、未知数据开销以及后续高价值扩展。
- draft 的目标不是消费完 external timeout，而是尽快得到一个任务正确、经过训练、可评分且可能有竞争力的完整方案。
- improve 使用已有方案的真实分数、真实耗时和工作量结构，逐步增加 folds、epochs、分辨率、TTA 或模型宽度。
- 更高计算开销应通过增量收益购买，而不应在首轮一次性预付。

这一原则比把所有 round 的硬 timeout 收紧到 1 小时更合理。硬 timeout 过低可能误杀正常但高价值的方案，而低耗时建模偏好可以提高初始成功率，并为后续搜索建立可靠基线。

## 3. 数据与统计口径

CSV 中共包含 45 个 commit：

| 类别 | 数量 |
|---|---:|
| 成功完成 | 36 |
| Timeout | 3 |
| 提前代码执行错误 | 6 |
| 点估计 | 28 |
| 区间估计 | 15 |
| 定性估计 | 1 |
| 缺失数值估计 | 1 |

统计遵循以下口径：

- 成功轮的 sandbox runtime 是完整路径的精确观测，可用于估计精度分析。
- Timeout runtime 只是完成时间下界，不能把 `10800s` 当作真实完成时间。
- 提前执行错误只反映失败前已经消耗的时间，不能与完整路径估计直接比较。
- 区间估计使用区间中点计算倍率，同时保留相对上界的倍率。
- 没有明确数值的定性描述不会被上下文中的其他数字替代。

## 4. 总体统计结果

在 35 个“成功且包含数值估计”的样本中：

| 指标 | 结果 |
|---|---:|
| 实际耗时 / 估计中点的中位数 | 0.709 |
| 高估耗时 | 24 / 35 |
| 低估耗时 | 11 / 35 |
| 落在 1.25 倍范围内 | 10 / 35 |
| 落在 1.5 倍范围内 | 16 / 35 |
| 落在 2 倍范围内 | 21 / 35 |

当前估计并不是整体过于乐观。中位数显示实际耗时通常只有估计的约 71%，说明多数估计偏保守。但分布存在明显重尾：少量方案被低估 5 至 8 倍，三个重图像任务更全部形成至少 3.38 至 4.50 倍的低估。

因此，不能通过给所有估计统一乘一个安全系数来解决问题。全局放大会进一步浪费多数轻任务的预算，同时仍然无法识别由数据管线、TTA、重复解码或训练实现造成的异常慢路径。

## 5. 在线时间参考的价值

按 branch 对成功数值样本进行近似分组：

| Branch | 样本数 | 实际 / 估计中位数 | 2 倍范围内 |
|---|---:|---:|---:|
| draft | 12 | 0.473 | 5 / 12 |
| improve | 20 | 0.904 | 16 / 20 |
| debug | 3 | 0.077 | 0 / 3 |

该结果支持“先完成快解，再用在线证据扩展”的设计：improve 已经拥有可比较 parent 时，估计明显更接近真实耗时。

但历史 runtime 必须满足可比性要求：

- 成功完成的同任务、同 lineage 路线是最可靠参考。
- 只改变 folds、epochs、分辨率或 TTA 时，可以按工作量比例缩放 parent runtime。
- 更换 backbone、decode backend、augmentation 或缓存策略后，不应假设耗时继续线性缩放。
- Timeout 只能作为下界。
- 提前失败耗时不能作为完整路径基准。
- Debug 修复可能移除失败前的重型路径，因此直接复用失败 parent runtime 会产生严重高估。

## 6. 当前机制为何守不住

### 6.1 一小时 ceiling 只是提示词建议

[`build_workload_plan()`](../runtime/branch_policy.py) 生成的是 soft workload contract。当前框架把 `draft_workload_ceiling_seconds=3600` 写入 prompt，但不解析或验证 agent 在 `context_readiness.md` 中填写的以下内容：

- `expected_complete_path_seconds`
- `runtime_estimate_basis`
- `complete_workload_product`
- `within_ceiling`

因此，agent 即使在没有实测依据的情况下写出 `within_ceiling: yes`，也会直接进入 sandbox。

### 6.2 External timeout 与建模计划脱钩

[`compute_validation_timeout()`](../runtime/branch_policy.py) 使用 neutral medium-cost operator 计算外部 timeout，并丢弃 `search_state`、`branch_state` 和 `runtime_profile`。实际结果是：

```text
Prompt 建议 draft 在 3600s 内完成
-> 框架不验证估算
-> sandbox 仍允许运行到 10800s
-> 只有 10800s external timeout 是硬约束
```

保持两者分离本身合理，问题在于 3600 秒目标没有任何机器消费或反馈闭环。

### 6.3 静态门禁不理解完整工作量

当前 [`inspect_solution_contract()`](../runtime/validation.py) 主要依赖文本和正则启发式，无法可靠计算：

```text
候选数 × folds × epochs × train passes
+ validation frequency × validation passes
+ test passes × TTA views
+ decode/preprocess passes
+ implementation efficiency
```

APTOS 和 RANZCR 的超时路线被判定为具有 fast score-first envelope。SIIM 的四视图 TTA 虽被识别为 `deep_media_tta_before_first_score`，但只产生 soft warning，仍然进入完整 sandbox validation。

### 6.4 没有真正的早期可评分路径

三个超时方案都在完整 CV、模型选择和 test inference 结束后才写 `submission.csv`。即使前面已经完成一部分 fold，也不会形成可评分结果。估算一旦错误，结果不是“分数稍弱”，而是整轮运行三小时后仍然零分。

### 6.5 Timeout 缺少阶段观测

这些 timeout 的 sandbox console 和 raw output 为空，框架无法判断程序停在预处理、第几个 epoch、第几个 fold，还是 test inference。下一轮只能知道 `runtime >= 10800s`，无法分别校准 decode、训练和推理成本。

## 7. 三个重任务的证据

### 7.1 APTOS

`test3-tries5` 超时路线估计 `3000s`，实际至少 `10800.8s`，低估至少 3.60 倍。它使用 384px EfficientNet、3 folds × 4 epochs，并在训练前完整解码、裁剪和预载全部 train/test 图片。

对照仓内强解可以在约 `1698s` 获得 `0.93253`，同样使用 384px 和 3 folds × 4 epochs。差异说明：只统计 folds 和 epochs 不足以判断方案是否过重；预载方式、内存复制、DataLoader 行为和实际图像管线可能比名义训练规模更重要。

APTOS 的结论不是“必须砍成一折”，而是应优先保留 pretrained ordinal CNN，同时避免未经验证的高风险数据管线。

### 7.2 RANZCR

超时路线估计 `2400s`，实际至少 `10800.9s`，低估至少 4.50 倍。虽然名义上只有 2 folds × 2 epochs，但每个 epoch 都进行完整 validation，每个 fold 都进行完整 test inference，总计约产生 9.75 万次高分辨率 JPEG decode、crop 和 resize。

对照强解约 `3129s / 0.90736`，使用更大的 3 folds × 4 epochs，却具有 AMP 和更轻的 OpenCV 灰度处理。当前超时实现没有 AMP，并使用较重的 PIL/torchvision augmentation。

这直接证明 `folds × epochs` 不能单独转换为秒数。训练精度模式、decode backend、原图尺寸和 augmentation cost 必须进入估算指纹。

冻结特征路线虽可在约 `1021s` 完成，但分数只有 `0.81073`。因此，不应把冻结 backbone 作为统一的 draft 轻量化策略。

### 7.3 SIIM

超时路线估计 `2400-3200s`，实际至少 `10800.9s`。它使用 EfficientNet-B3 300px、3 folds × 4 epochs，并在每个 fold 后对 validation 和 test 执行四视图 TTA。

该任务最清楚地展示了乘法型成本问题。与扩大模型族相比，draft 更应先减少 TTA、epochs、folds、分辨率和重复 test inference，同时保留 patient-disjoint split、预训练图像模型、AMP 和类别不平衡处理。

## 8. Draft 轻量化的正确边界

轻量化应定义为“单一强路径优先”，而不是“模型能力最弱”。

Draft 应保留：

- 一个任务匹配的 pretrained 强模型族。
- 足以保留主要信号的中等分辨率。
- 正确的 grouped 或 stratified validation。
- 类别不平衡处理。
- 必要且高收益的任务预处理。
- AMP 和吞吐稳定的数据管线。
- 廉价的 OOF threshold、raw/rank 选择等后处理。
- 一个经过训练、完整推理并满足 submission contract 的候选。

优先延后到 improve：

- 第二个完整 backbone 或多个完整候选。
- 增加 folds、epochs 和 seeds。
- 提升分辨率。
- TTA 或 multi-view inference。
- 重型 augmentation。
- 多阶段 metadata fusion、stacking 和宽网格搜索。
- Annotation、segmentation 等新的监督支路。
- 一个候选成功后继续运行只用于容错的完整 fallback candidate。

这些组件大多是乘法型成本，并且天然适合在已有分数和 runtime 的 parent 上逐项扩展。

不建议设置统一的 fold、epoch 或分辨率 hard guard。APTOS 和 RANZCR 的对照表明，高效实现的大路线可能比低效实现的小路线更快。

## 9. 更可靠的估算方案

### 9.1 从精确点估计改为风险区间

当前大量 `2400s`、`3000s` 等点估计体现了虚假精确性。建议使用：

```text
evidence class
+ expected runtime range
+ risk-adjusted upper bound
```

Draft 的判断条件应从：

```text
optimistic expected time <= 3600
```

改为：

```text
risk-adjusted upper bound <= 3600
```

建议的证据等级：

| 证据 | 可靠性 | 建议安全系数 |
|---|---|---:|
| 同任务、同方法、同数据管线的成功 parent | 高 | 1.25-1.5x |
| 同任务但存在有限结构变化 | 中 | 1.5-2x |
| 首个深度媒体 draft，无可比成功历史 | 低 | 至少 2x |
| Timeout 或提前失败 | 不能形成完成时间点估计 | 仅作下界或失败证据 |

安全系数应在后续统计校准后确定，不应直接视为最终固定参数。

### 9.2 保存结构化工作量指纹

每个方案应记录紧凑的 `workload_signature`：

```text
model_family
train_rows / test_rows
media_count / source_media_size
input_resolution
candidate_count
fold_count / epoch_count
validation_frequency
test_inference_passes
TTA_views
full_corpus_decode_passes
AMP_enabled
decode_backend
augmentation_cost_class
preload_or_cache_strategy
actual_sandbox_runtime
```

图像路线可以先构造相对工作量：

```text
train_units = candidates
              × fold training exposure
              × epochs
              × resized pixel area
              × model factor

eval_units = validation and test rows
             × inference passes
             × TTA views
             × resized pixel area
             × model factor

decode_units = source media volume
               × full or repeated decode passes
               × augmentation/decode factor
```

相对工作量不能凭空变成秒数。绝对时间应优先由可比较的成功 parent 在线校准：

```text
new runtime range
≈ parent actual runtime
  × new workload units / parent workload units
  × uncertainty margin
```

### 9.3 规范客观数据事实

现有 EDA 已经包含 train/test 行数、媒体数量、总大小、文件类型和采样原图尺寸，但 schema 不统一。可以提取一个紧凑的 `workload_facts_v1`，供 estimator 和 prompt 共用。

这不需要恢复 sandbox environment probe，也不需要额外训练预跑。它只是把现有 EDA 客观事实转成统一结构。

### 9.4 生成后静态一致性核对

在进入 sandbox 前，框架可以核对 readiness 声明与代码中高置信度可识别的工作量：

- folds、epochs、candidates 和 seeds。
- image size 或 sequence length。
- TTA views 和 test inference 次数。
- AMP 是否启用。
- validation 是否每个 epoch 重复。
- 是否存在完整数据预载或每折重复预处理。
- 是否在一个成功候选后继续运行其他完整候选。

只有在 readiness 与代码明显不一致，或无历史的大媒体路线出现高置信度乘法膨胀时，才触发同轮修复。不要把低置信度静态猜测升级成普遍 hard guard。

### 9.5 利用正常运行的阶段时间

成功方案可以输出少量标准阶段时间点：

```text
data_ready
first_epoch_complete
training_complete
inference_complete
```

Runner 从已有 stdout 中解析这些时间，可分别校准数据准备、训练和推理成本。这不是额外 sandbox probe，也不是内部 deadline，正常开销接近零。

Timeout 日志仍需保证尽可能保留阶段输出，否则只能获得整体下界。

## 10. 不建议的方案

- 不建议把 external timeout 从 3 小时统一缩到 1 小时。
- 不建议强制所有 draft 使用一折、小模型或冻结 backbone。
- 不建议只根据 folds × epochs 估算运行时间。
- 不建议把失败 parent 的 runtime 当作完整路线耗时。
- 不建议允许 agent 无证据填写精确秒数并自行声明 `within_ceiling: yes`。
- 不建议把 `shortest_medal_round_time.csv` 等按 benchmark 任务命名的结果直接注入调度器。它们可以离线验证“快解中存在优解”的总体原则，但直接参与当前任务路由会增加 benchmark leakage 和先验过拟合风险。
- 不建议使用内部 timer、紧急 deadline fallback 或常量 submission 掩盖真正 timeout。

## 11. 建议的实现优先级

1. 将 draft 明确定义为单一强而经济的完整路线，把乘法型扩展留给 improve。
2. 将 readiness 的时间字段结构化为估计区间、证据等级和风险上界。
3. 保存成功轮的 `workload_signature + actual runtime`，并让 improve 使用可比较 parent 做比例估算。
4. 规范 EDA 中的 `workload_facts_v1`，不增加新的 sandbox environment probe。
5. 在代码生成后核对 readiness 与代码工作量，对高置信度不一致执行同轮修复。
6. 从正常 stdout 收集阶段时间，提高后续在线校准精度。
7. 最后再根据更多运行统计校准安全系数和静态触发阈值。

## 12. 总结

统计与代码对照共同支持以下结论：

1. 维持 3 小时 external timeout 与推动 draft 低耗时并不冲突。
2. 当前一小时 workload ceiling 只有文字约束，没有形成机器校验和反馈闭环。
3. 快解中可以包含优解，但轻量化必须保留任务正确的 pretrained 强路径。
4. 时间估算的主要问题不是平均偏差，而是无法识别少量灾难性慢路径。
5. folds 和 epochs 不足以描述实际成本，AMP、decode、augmentation、预载、验证频率和 test passes 同样关键。
6. 成功 parent 的在线时间显著提高 improve 估算质量，但必须与工作量指纹结合。
7. 最合理的升级方向是“工作量指纹 + 在线校准 + 风险上界 + 静态一致性核对”，而不是更短的硬 timeout 或更弱的首轮模型。
