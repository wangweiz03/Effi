# SIIM Melanoma Task Skill Handoff

## Purpose

The specialized task skill is stored at:

`/hpc_data/weizwang@weizwang/frameworks/resources/hacker/siim/SKILL_siim-isic-melanoma-classification.md`

It converts the recurring, legitimate modeling lessons from 30 archived Kaggle
writeups into branch-compatible instructions for the current runtime. It does not
make leaderboard leakage, private-score tuning, public prediction reuse, hidden-label
inference, or same-patient train-label propagation permissible.

The skill is intentionally separate from the default `mle-reimagined` directory. Use
it explicitly:

```bash
TASK_SKILLS_DIR=/hpc_data/weizwang@weizwang/frameworks/resources/hacker/siim \
./run_selected_tasks.sh siim-isic-melanoma-classification
```

The loader resolves the exact filename `SKILL_<task-name>.md` directly under the
configured task-skill directory. Draft and improve require this source; debug may
route it as optional context while prioritizing failure-prevention evidence.

## Evidence and Constraints

The archived writeups consistently favor pretrained EfficientNet-family models,
patient-safe validation, controlled rare-positive sampling, moderate dermoscopy
augmentation, TTA, and rank aggregation. High-resolution multi-model ensembles and
external-year data are common in unrestricted medal solutions, but their original
cost does not fit this runtime.

The framework normally allows at most 10,800 seconds of sandbox validation runtime
for one round and owns the only timeout. The skill therefore uses statically bounded
work: three sequential patient-grouped folds, 320-384 pixel inputs, four to six short
epochs, AMP, immediate fold inference, and four deterministic TTA views. It forbids
an internal timer and cross-round checkpoints or OOF artifacts.

Reference external validation thresholds are:

- Bronze: `0.9370`
- Silver: `0.9401`
- Gold: `0.9455`

These are targets, not guarantees. Grouped OOF AUC selects methods within a round;
the sandbox validation score remains authoritative.

## Branch Behavior

Draft A trains a cached Noisy-Student EfficientNet B3/B2 as a binary melanoma ranker.
Draft B independently trains a three-class `melanoma / nevus / other` diagnosis model
and submits the melanoma probability. The second draft changes supervision rather
than making a cosmetic parameter change, which preserves useful search diversity.

Improve starts from the validation-best parent and applies one material change:
binary/diagnosis multitask supervision, a measured resolution or backbone step,
test-available metadata fusion, label-free patient-relative prediction ranks, an
OOF-supported rank blend, or one bounded diverse model family.

Debug preserves the failed parent's modeling intent. For resource failures it removes
optional work first, then reduces TTA, epochs, resolution, batch size, and finally
fold count. It must repair a concrete dependency or contract failure instead of
silently switching to an untrained or metadata-only fallback.

## Safety Boundary

Patient IDs must remain disjoint across validation folds. Diagnosis and malignancy
labels are supervision only and cannot enter test features. Patient-relative features
may use only cross-fitted OOF/test predictions and label-free group statistics. The
skill also excludes public/private leaderboard tuning, known submission blending,
hard-example deletion from model errors, test pseudo-labeling by default, downloads,
and assumptions about external data mounts.

All paths, columns, row counts, class counts, and image layouts are inferred from
`DATA_DIR`. The only persisted prediction artifact is `submission.csv`, aligned to
the exact `sample_submission.csv` IDs and columns.

## Verification

Before a run, verify that `load_task_skill` returns the specialized path and that
`extract_skill_schema` populates all seven recognized sections. Route smoke tests
must confirm the source is required for draft/improve and remains available to debug.
The file must be ASCII-only and must not contain instructions to download data,
implement an internal deadline, or persist reusable training artifacts.
