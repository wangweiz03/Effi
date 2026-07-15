# Static Sandbox Model Cache Audit

## Purpose

This document records the evidence boundary for the repository-maintained ready-only sandbox model-cache inventory. The audit was performed on 2026-07-14. It replaces run-start dynamic cache probing; normal evaluator runs do not inspect the complete shared cache and do not spend sandbox runtime on capability discovery.

## Survey Scope

The one-time survey enumerated the known shared Hugging Face Hub and Torch checkpoint roots:

- Hugging Face Hub: `/mnt/pubdatasets2/mlsandbox/hf_home/hub`
- Torch checkpoints: `/mnt/pubdatasets2/mlsandbox/torch_home/hub/checkpoints`

The Hugging Face survey covered 926 model repository directories. They were classified as:

- 539 with at least one snapshot containing `config.json` and a complete weight set;
- 318 with complete weights but no `config.json`;
- 44 with configuration but no weights;
- 5 with incomplete weight sets;
- 17 with neither configuration nor weights;
- 3 with no snapshot.

The Torch checkpoint survey found 109 complete checkpoint files and 5 `.partial` files.

## Publication Rule

Only the 539 ready Hugging Face repositories and 109 complete Torch checkpoints are published in `runtime/sandbox_model_cache.txt`. The evaluator copies that file unchanged to each task as `context_sources/sandbox_model_cache.txt`.

No status column is necessary because publication itself means ready. All non-ready Hugging Face categories and all `.partial` Torch files are excluded. This is a cache-availability contract, not a recommendation to use every listed model and not proof that a listed architecture is suitable for a particular task.

PART 4 makes the task-local inventory mandatory for draft and optional for debug/improve. Codex must use targeted case-insensitive lookup, for example:

```bash
grep -iE 'deberta|roberta|resnet|efficientnet' context_sources/sandbox_model_cache.txt
```

Codex must not read the entire inventory into prompt context. Cache selection remains evidence-driven, offline, and task-specific.

## Separate Runtime Observations

The same investigation observed an NVIDIA GeForce RTX 4090 sandbox device with compute capability 8.9. `nvidia-smi` reported 24,564 MiB physical VRAM, while PyTorch reported approximately 23.52 GiB usable device memory. These facts are investigation evidence only; they do not turn the model-cache inventory into a live accelerator contract.

Library versions and importability were not fully audited for this ready-only inventory. The inventory must not be cited as evidence of complete package availability.

## Maintenance

Refresh the canonical file only after an explicit cache survey confirms complete local artifacts. Review the survey classifications, regenerate the ready-only list deterministically, and commit the source and documentation together. Do not reintroduce per-run cache probing, probe CLI controls, probe artifacts, or probe runtime accounting.
