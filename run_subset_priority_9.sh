#!/bin/bash
set -euo pipefail

# Run the fixed v4 priority subset requested for focused follow-up experiments.
# Extra arguments are forwarded to run_selected_tasks.sh before the task list, so
# callers can still override --model, --concurrency, --sandbox-run-budget, etc.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TASKS=(
    siim-isic-melanoma-classification
)

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<EOF
Usage: $0 [run_selected_tasks.sh options]

Runs this fixed v4 subset:
$(printf '  %s\n' "${TASKS[@]}")

Examples:
  $0 --sandbox-run-budget 43200 --time-budget 43200
  $0 --concurrency 22 --model gpt-5.4 --reasoning-level medium

All options are forwarded to run_selected_tasks.sh.
EOF
    exit 0
fi

export OUTPUT_DIR="${OUTPUT_DIR:-./cur/test2-siim-hack}"
export NUM_ROUNDS="${NUM_ROUNDS:-5}"

cd "$SCRIPT_DIR"
exec ./run_selected_tasks.sh "$@" "${TASKS[@]}"
