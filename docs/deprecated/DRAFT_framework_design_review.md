# 修改方略【人工草稿版】

这里提出我的修改方案构想，你需要与原框架实现方法比照，遵循我的思路，并把我未提到的其他细节模块如时间管理、静态 gate 妥善保留与安排。

新的运行时逻辑：

对于每个任务，迭代的每一轮内部，应大体改成这样：

1. 系统根据硬性指标硬判决当前 branch：

draft/debug/improve，branch 的决策方式可以沿用当前框架设计；

我对框架硬规则进行简单复述：起始先 draft 产出 2 个方向独立的 seeds，然后默认 improve，连续 【4】 轮无提升则 draft 新方向的 seed；代码出错则针对出错代码 debug；【这里仅是简述，关于 branch 决策方式，在这里你要补充说明清楚】

至于 intent/operator/family 之类细分方向，应当【彻底】取消，或不应由框架机械决定。

2. 进行 coding prompt 组装及信息收集流程。

coding prompt 既给到必要信息，也驱动 codex 进行其他信息的收集。coding prompt 的设计，在当前框架设计的基础上略做调整——目前它以比较清晰的逻辑分为 5 块，大概为 system 硬要求、task description 任务信息、state 任务状态、skill/memory 摘录、（必读/选读）文档日志路径及其简单说明；应当改良为 4 块：system 硬要求、task description 任务信息（包含简要的 EDA 信息）、state 任务状态与记忆、（必读/选读）文档日志路径及其简单说明，即不再内联 skill/memory 摘录，它们的信息由后续路径读取来收集。

根据不同 branch，coding prompt 有所侧重。必读路径为 skill。其中 draft 节点读取任务 skill 和 failure-prevention skill，improve 节点只读取任务 skill，debug 节点只读取 failure-prevention skill。EDA 完整结论必读。其余工作目录下的文件（如完整代码、日志等，以及 memory 库（应当放在一个目录下，由 markdown 形式 的 memory cards 构成，memory card 由 codex 总结+机械记录构成，是每一轮的凝练画像，后续会讲））作为选读。每个路径必须简要说明它们的含义。

state 任务状态部分保持简洁，内容由框架机械决定。我认为需要包括当前轮、路径、历史轮数-分数一览、当前轮 branch 及该 branch 含义解释（这个可以预先写好，很重要）、父节点（draft 应当没有父节点，debug 应有唯一父节点，而 improve 允许从任意多历史节点中提取方法，因此不设父节点）的 memory card，best 节点 memory card 等等，【由你结合原设计，确定细节取舍】。

关于哪部分需要包含哪些内容，我的考虑可能不周全，有所遗漏，务必检查 coding prompt 总体上做到无冗余、自洽、信息完整。

3. 信息收集完后进行编程前规划：我没有具体要改的地方，确保新框架下和其他组件保持无摩擦即可。
4. 写代码（完整或 patch）、静态检查与打回、运行
5. 写完代码提交/未通过静态检查后，开始总结 memory card，分为软性总结和硬性总结，硬性总结包括轮号、branch、父节点、该轮得分（可等返回得分后补全）、失败原因等等，软性总结包含本轮使用的方法概述（可用密集关键词快速精简刻画）等。每一轮的 memory card 信息密度必须足够高同时精简【控制在 1000 token 左右是否合适？】，且能够互相比较（mprove 用于提取增益信号）。【我的考虑可能不周全】【除此之外还可以考虑参考 /hpc_data/weizwang@weizwang/SuperML-Agent-inference-tts-mem/docs/task_memory_search_reproducible.md 的思想设计更多记忆层级，但 memory card 作为最基本的记忆单元和画像是有必要存在的】。也就是说，原先在每一轮初始进行的基于 branch/intent/operator/... 的硬性画像，迁移到了一轮结束后，且软硬兼备，这样画像更为精确丰富。
