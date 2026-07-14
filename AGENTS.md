# Repository Guidelines

## Project Structure & Module Organization

This repository contains the BSPM Codex v4 runtime. `evaluate_codex.py` is the CLI entrypoint and compatibility re-export. Core source code lives in `runtime/`: `runner.py` coordinates task execution, `codex_cli.py` calls the Codex CLI, `validation.py` handles sandbox feedback, `skills.py` routes task skills, `memory_store.py` and `portfolio.py` manage search state, and `prompt_pack.py`/`text_context.py` assemble prompts. `prompts.py` contains shared prompt text. Shell workflows live at the root, including `run_selected_tasks.sh` and `run_subset_priority_9.sh`. `real_run_examples/` stores example run outputs, traces, memory banks, commits, and validation artifacts; treat it as reference data rather than runtime source.

## Build, Test, and Development Commands

- `python evaluate_codex.py --data-file tasks.parquet --output-dir ./runs/demo --num-rounds 1 --concurrency 1`: run the evaluator on a JSON or Parquet task file.
- `DATA_FILE=/path/eval.parquet ./run_selected_tasks.sh task-name`: select one or more named tasks and run the evaluator with repository defaults.
- `TASKS_CSV=task-a,task-b ./run_selected_tasks.sh --sandbox-run-budget 43200`: run a comma-separated task set.
- `./run_subset_priority_9.sh --concurrency 4`: run the fixed priority subset while forwarding options to `run_selected_tasks.sh`.

External sandbox, inference, task-skill, and EDA-skill paths are required for full runs. Override defaults with flags such as `--sandbox-base-url`, `--task-skills-dir`, `--eda-skill-dir`, or `PYTHON_BIN`.

## Coding Style & Naming Conventions

Use Python 3, 4-space indentation, `from __future__ import annotations`, and type hints for new public helpers. Prefer `pathlib.Path` for filesystem paths and snake_case for modules, functions, and variables. Keep changes scoped to the relevant runtime module instead of adding broad helpers to `common.py`. Shell scripts should use `set -euo pipefail` and clear environment-variable defaults.

## Testing Guidelines

No dedicated test suite is present. Validate changes with the smallest practical smoke test, usually a one-round evaluator run against a tiny task file or an existing example-derived fixture. If adding tests, place them under `tests/`, name files `test_<module>.py`, and use pytest-style assertions.

## Commit & Pull Request Guidelines

Git history is unavailable in this checkout, so use concise imperative commit subjects such as `Tighten sandbox timeout handling`. Pull requests should describe behavior changes, list smoke-test commands and outcomes, note required external services or paths, and include relevant trace or validation snippets for runtime changes.

## Resources

`./docs`: Contains documentation reflecting the latest state of the directory, including overviews and modification strategies, serving as a quick handoff reference, but it does **not** replace the work of reading the actual code.

/hpc_data/weizwang@weizwang/frameworks/resources/mle_skill_error2：error prevention skill

/hpc_data/weizwang@weizwang/frameworks/resources/mle-reimagined：task-specific ML skills

/hpc_data/weizwang@weizwang/frameworks/resources/mlebench-skill-eda：EDA guideline

/hpc_data/weizwang@weizwang/frameworks/resources/medal_thres.md：medal threshold of MLE-bench lite tasks

/hpc_data/weizwang@weizwang/frameworks/resources/shortest_medal_round_time.csv：time consumption overview of MLE-bench lite tasks

/hpc_data/weizwang@weizwang/medal-solutions/sols：an archive of MLE-bench lite medal solution codes（same sandbox env）

## Requirements

You are an outstanding software engineer with profound insights into machine learning engineering. You are required to review or modify this framework based on your objective expertise or human feedback, with the fundamental goal of improving the framework's operational efficiency and performance (code score). Additional considerations include:

* Evidence first: gather sufficient information from the framework code, execution traces, documentation, etc. before taking action, and consult the human user when necessary;
* Always maintain the framework's generality, rather than applying overfitted patches and optimizations for specific tasks;
* Start from intuition, objectively audit the rationality of the framework design. For unreasonable aspects of the current framework, extract their core ideas and re-conceive them appropriately, so as to re-implement or upgrade the original framework's functionality in a more reasonable and reliable manner; identify which components (e.g., skill, EDA, memory, etc.) contribute to the framework's gains, and think about how to best integrate and squeeze value from them;
* Control code complexity, keep code and prompts as concise and elegant as possible, and avoid significantly increasing code size after modifications; Control runtime token consumption;
* Allow running lightweight experiments to verify effectiveness;
* When designing the framework, you may refer to Kaggle leaderboards, high-quality solutions, and similar sources to extract high-level insights and general principles, but the implementation must not involve hacking issues;
* **When the workload is large, use subagents;**
* **Ensure that all modules of the framework are seamlessly integrated, with no friction or conflict;**
* **Always maintain the** **`doc/` documentation library (except the deprecated/ files), ensure it is aligned with the latest state of the current directory, and make it capable of being handed over to a new agent that has no prior knowledge of the current directory;**
* Time budget is always calculated by SANDBOX RUNTIME;
* Use Chinese during conversations, but all logs, documentation, and other artifacts written to disk within the framework should be in pure English.
