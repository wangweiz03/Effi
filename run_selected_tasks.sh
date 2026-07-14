#!/bin/bash
set -euo pipefail

# Run selected tasks from a MLE-Bench task parquet with BSPM Codex v4 memory-bank search.
# Usage:
#   DATA_FILE=/path/to/eval.parquet ./run_selected_tasks.sh task-a task-b
# or:
#   TASKS_CSV=task-a,task-b ./run_selected_tasks.sh

PYTHON_BIN="${PYTHON_BIN:-/root/miniconda3/bin/python3}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOURCE_ROOT="${RESOURCE_ROOT:-/hpc_data/weizwang@weizwang/frameworks/resources}"
DATA_FILE="${DATA_FILE:-$RESOURCE_ROOT/automl_parquet_test_all_0406/eval.parquet}"
if [[ -n "${SUBSET_FILE:-}" ]]; then
    CLEAN_SUBSET_FILE=0
else
    SUBSET_FILE="/tmp/bspm_v4_selected_${USER:-user}_$$.parquet"
    CLEAN_SUBSET_FILE=1
fi
OUTPUT_DIR="${OUTPUT_DIR:-./codex-gpt-5.4-medium_lite_bspm_v4_memory_bank_selected}"
MODEL="${MODEL:-gpt-5.4}"
REASONING_LEVEL="${REASONING_LEVEL:-medium}"
NUM_ROUNDS="${NUM_ROUNDS:-50}"
TIME_BUDGET="${TIME_BUDGET:-43200}"
BUDGET_MODE="${BUDGET_MODE:-sandbox}"
SANDBOX_RUN_BUDGET="${SANDBOX_RUN_BUDGET:-}"
CONCURRENCY="${CONCURRENCY:-22}"
MAX_TOKENS="${MAX_TOKENS:-100000}"
TEMPERATURE="${TEMPERATURE:-0.6}"
TASK_SKILLS_DIR="${TASK_SKILLS_DIR:-$RESOURCE_ROOT/mle-reimagined}"
EDA_SKILL_DIR="${EDA_SKILL_DIR:-$RESOURCE_ROOT/mlebench-skill-eda}"
ERROR_SKILL_FILE="${ERROR_SKILL_FILE:-$RESOURCE_ROOT/mle_skill_error2/ml_failure_prevention_skill_v4.md}"
LOCAL_EDA_DATA_ROOT="${LOCAL_EDA_DATA_ROOT:-/hpc_data/ktian/superml/inference_codex_cot4/mlebench-lite-val}"
EARLY_EDA_BRANCHES="${EARLY_EDA_BRANCHES:-}"
SANDBOX_BASE_URL="${SANDBOX_BASE_URL:-${MLEBENCH_SANDBOX_BASE_URL:-http://183.222.230.175:6580}}"

usage() {
    cat <<EOF
Usage: $0 [options] task-a task-b ...

Options:
  --data-file PATH              Task parquet/json file
  --subset-file PATH            Temporary selected-task parquet path
  --output-dir DIR              Output directory
  --model NAME                  Codex model
  --reasoning-level LEVEL       Reasoning level
  --num-rounds N                Max rounds per task
  --time-budget SECONDS         Compatibility alias for sandbox validation run-time budget
  --budget-mode MODE            Must be sandbox in v4
  --sandbox-run-budget SECONDS  Sandbox validation run-time budget
  --concurrency N               Concurrent tasks
  --max-tokens N                Max generation tokens
  --temperature FLOAT           Generation temperature
  --task-skills-dir DIR         Task skill directory
  --eda-skill-dir DIR           EDA skill directory
  --error-skill-file PATH       Error-prevention skill file
  --local-eda-data-root DIR     Local EDA data root
  --early-eda-branches CSV      Extra branches that run early EDA after the mandatory first-round bootstrap EDA
  --sandbox-base-url URL        Sandbox service URL
  -h, --help                    Show this help

Examples:
  $0 --sandbox-run-budget 43200 new-york-city-taxi-fare-prediction
  TASKS_CSV=task-a,task-b $0 --sandbox-run-budget 43200
EOF
}

TASKS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --data-file) DATA_FILE="$2"; shift 2 ;;
        --subset-file) SUBSET_FILE="$2"; CLEAN_SUBSET_FILE=0; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --reasoning-level) REASONING_LEVEL="$2"; shift 2 ;;
        --num-rounds) NUM_ROUNDS="$2"; shift 2 ;;
        --time-budget) TIME_BUDGET="$2"; shift 2 ;;
        --budget-mode) BUDGET_MODE="$2"; shift 2 ;;
        --sandbox-run-budget) SANDBOX_RUN_BUDGET="$2"; shift 2 ;;
        --concurrency) CONCURRENCY="$2"; shift 2 ;;
        --max-tokens) MAX_TOKENS="$2"; shift 2 ;;
        --temperature) TEMPERATURE="$2"; shift 2 ;;
        --task-skills-dir) TASK_SKILLS_DIR="$2"; shift 2 ;;
        --eda-skill-dir) EDA_SKILL_DIR="$2"; shift 2 ;;
        --error-skill-file) ERROR_SKILL_FILE="$2"; shift 2 ;;
        --local-eda-data-root) LOCAL_EDA_DATA_ROOT="$2"; shift 2 ;;
        --early-eda-branches) EARLY_EDA_BRANCHES="$2"; shift 2 ;;
        --sandbox-base-url) SANDBOX_BASE_URL="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        --)
            shift
            TASKS+=("$@")
            break
            ;;
        -*)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            TASKS+=("$1")
            shift
            ;;
    esac
done

cd "$SCRIPT_DIR"
if [[ "$CLEAN_SUBSET_FILE" == "1" ]]; then
    trap 'rm -f "$SUBSET_FILE"' EXIT
fi

case "$BUDGET_MODE" in
    sandbox) ;;
    *)
        echo "ERROR: v4 requires --budget-mode sandbox" >&2
        exit 1
        ;;
esac
SANDBOX_RUN_BUDGET="${SANDBOX_RUN_BUDGET:-$TIME_BUDGET}"

if [[ ! -f "$DATA_FILE" ]]; then
    echo "ERROR: MLE-Bench task file not found: $DATA_FILE" >&2
    exit 1
fi

if [[ ${#TASKS[@]} -eq 0 && -n "${TASKS_CSV:-}" ]]; then
    IFS=',' read -r -a TASKS <<< "$TASKS_CSV"
fi
if [[ ${#TASKS[@]} -eq 0 ]]; then
    echo "ERROR: provide task names as arguments or set TASKS_CSV=task-a,task-b" >&2
    exit 1
fi

TASKS_JSON="$("$PYTHON_BIN" - "${TASKS[@]}" <<'PYEOF'
import json
import sys
print(json.dumps([x.strip() for x in sys.argv[1:] if x.strip()]))
PYEOF
)"

"$PYTHON_BIN" - <<PYEOF
import json
import sys
import pandas as pd

data_file = "$DATA_FILE"
subset_file = "$SUBSET_FILE"
tasks = json.loads('$TASKS_JSON')

df = pd.read_parquet(data_file)

def get_task_name(meta):
    return meta.get("task_name", "") if isinstance(meta, dict) else ""

names = df["metadata"].map(get_task_name)
subset = df.loc[names.isin(tasks)].copy()
found = set(subset["metadata"].map(get_task_name))
missing = [task for task in tasks if task not in found]
if missing:
    print("ERROR: Missing requested tasks:", file=sys.stderr)
    for task in missing:
        print(f"  {task}", file=sys.stderr)
    sys.exit(1)

subset.to_parquet(subset_file, index=False)
print(f"Wrote {len(subset)} task row(s) to {subset_file}")
for task in tasks:
    print(f"  {task}")
PYEOF

echo "=== BSPM Codex v4 Selected Tasks Memory-Bank Search ==="
echo "Data file:   $DATA_FILE"
echo "Subset file: $SUBSET_FILE"
echo "Output dir:  $OUTPUT_DIR"
echo "Model:       $MODEL"
echo "Reasoning:   $REASONING_LEVEL"
echo "Rounds:      $NUM_ROUNDS"
echo "Time budget: $TIME_BUDGET"
echo "Budget mode: $BUDGET_MODE"
echo "Sandbox run: $SANDBOX_RUN_BUDGET"
echo "Concurrency: $CONCURRENCY"
echo "Task skills: $TASK_SKILLS_DIR"
echo "Bootstrap EDA: mandatory on round 1 portfolio seed"
echo "Extra EDA:   ${EARLY_EDA_BRANCHES:-disabled}"
echo "Python:      $PYTHON_BIN"
echo ""

"$PYTHON_BIN" evaluate_codex.py \
    --data-file "$SUBSET_FILE" \
    --output-dir "$OUTPUT_DIR" \
    --model "$MODEL" \
    --reasoning-level "$REASONING_LEVEL" \
    --num-rounds "$NUM_ROUNDS" \
    --time-budget "$TIME_BUDGET" \
    --budget-mode "$BUDGET_MODE" \
    --sandbox-run-budget "$SANDBOX_RUN_BUDGET" \
    --concurrency "$CONCURRENCY" \
    --max-tokens "$MAX_TOKENS" \
    --temperature "$TEMPERATURE" \
    --task-skills-dir "$TASK_SKILLS_DIR" \
    --eda-skill-dir "$EDA_SKILL_DIR" \
    --error-skill-file "$ERROR_SKILL_FILE" \
    --local-eda-data-root "$LOCAL_EDA_DATA_ROOT" \
    --early-eda-branches "$EARLY_EDA_BRANCHES" \
    --sandbox-base-url "$SANDBOX_BASE_URL"

echo ""
echo "Done. Check $OUTPUT_DIR for results."
