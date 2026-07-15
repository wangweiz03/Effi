# Task Skill Reorganization Audit

## Scope

This audit covers only the following task skills under
`/hpc_data/weizwang@weizwang/frameworks/resources/mle-reimagined`:

- `SKILL_siim-isic-melanoma-classification.md`
- `SKILL_aptos2019-blindness-detection.md`
- `SKILL_jigsaw-toxic-comment-classification-challenge.md`
- `SKILL_tabular-playground-series-may-2022.md`
- `SKILL_ranzcr-clip-catheter-line-classification.md`

The audited candidates were installed into the external resource directory.
`runtime/skills.py` and `runtime/runner.py` now project these files into
branch-scoped prompt sources. `prompts.py` and `runtime/constants.py` remove the
global fixed candidate-count and forced-stack draft requirements.

## Required Structure

Every candidate has exactly these six level-two headings in this order:

1. `Task Contract And Traps`
2. `Seed Route`
3. `Improve Library`
4. `Debug And Fallback`
5. `Validation Contract`
6. `Avoid Or Delay`

The reorganization moves immutable source content blocks into those sections.
The former strong-first material and later-round upgrades belong to `Improve
Library`; first-valid material belongs to `Seed Route`; explicit runtime or
dependency recovery belongs to `Debug And Fallback`.

## Provenance Invariants

The executable audit is
`tests/task_skill_reorganization_audit.py`. It treats each prose paragraph and
each Markdown list item as an immutable content block. It enforces all of the
following:

- the level-one task title is unchanged;
- the six target headings exist exactly once and in the required order;
- every retained candidate block is byte-equivalent after indentation
  normalization to one source block;
- every retained source block appears exactly once in the candidate;
- no new modeling statement is introduced;
- every retained block is routed to its declared target section;
- every permitted deletion rule matches exactly one source block;
- no fixed 12-hour statement, same-script first-valid-to-strong connector, or
  listed cross-round artifact persistence statement remains.

The pre-install evidence is frozen in
`tests/task_skill_reorganization_manifest.json`. It records the original source
digest, every retained normalized block digest and target section, every exact
deleted block and reason, and the installed candidate digest. The audit script
can therefore verify installed files after the old source layout has been
replaced.

## Candidate Results

The following results were produced on 2026-07-14:

| Task | Source blocks | Candidate blocks | Deleted | Candidate SHA-256 |
| --- | ---: | ---: | ---: | --- |
| SIIM-ISIC melanoma | 69 | 69 | 0 | `342b6f959f2ebacd21accc0af6ae301bd0337bf0e5188c30dae5b666ec231c54` |
| APTOS 2019 blindness | 75 | 72 | 3 | `230cc883522d855d1efb371b64124505b853b7c1a502347d624d21576875e071` |
| Jigsaw toxicity | 88 | 82 | 6 | `a5a04e0466c5580dde56a344a1c5b270bf0350a381745034723be86f7e9a4391` |
| TPS May 2022 | 101 | 96 | 5 | `a60f0ca61f03caff409e6bdf5f16cab9c0dc866231445aac54acb5d806e403a0` |
| RANZCR catheter lines | 67 | 64 | 3 | `5170f2b7c8970759b98f2ed51032983d26d15492baf8721e2e2ad8e9ae2551f2` |

All five candidates passed the content, deletion, heading, and routing checks.

## Deletion Summary

SIIM required no content deletion. Its current source already uses the
framework-owned external validation wall and explicitly rejects cross-round
reusable model or prediction files.

APTOS deletes its fixed 12-hour compute paragraph and its explicit artifact
persistence paragraph. Its fallback route and the instruction to preserve the
same artifacts occupy one original list item. Because modeling sentences may
not be rewritten or split in this reorganization, that complete list item is
deleted. As a result, the APTOS candidate currently has an empty `Debug And
Fallback` section. Restoring only the modeling part would require a separately
approved sentence-level edit rather than a content-conserving move.

Jigsaw deletes the fixed 12-hour resource paragraph, the runtime-feasibility
claim derived from that budget, both same-script connectors, and two explicit
cross-round OOF persistence paragraphs. The sparse and transformer modeling
instructions themselves remain unchanged under `Improve Library`.

TPS May 2022 deletes the fixed 12-hour compute paragraph, the smoke-to-strong
same-script connector, and three artifact persistence statements. Its
first-valid LightGBM route remains under `Seed Route`; the multi-model feature
and blend library remains under `Improve Library`.

RANZCR deletes the fixed 12-hour compute paragraph, its artifact persistence
paragraph, and the priority paragraph whose final sentence compares ensemble
feasibility under the obsolete 12-hour budget. The one-fold compact model stays
under `Seed Route`, while the larger multi-fold model stays under `Improve
Library`.

## Reproduction

Audit the active installed skills against the immutable manifest:

```bash
python tests/task_skill_reorganization_audit.py \
  --candidate-dir /hpc_data/weizwang@weizwang/frameworks/resources/mle-reimagined
```

Audit the retained preparation candidates:

```bash
python tests/task_skill_reorganization_audit.py
```

To review a different candidate directory, pass
`--candidate-dir /path/to/candidates`. The script defaults to
`/tmp/task_skill_reorganization_candidates` as its candidate destination.
`--write-candidates` is a historical regeneration mode and requires an
unreorganized source directory; it must not be run against the active installed
six-section files.

## Application Boundary

These five skills are active framework resources. At prompt assembly time the
runtime copies only the branch-relevant sections into the task-local
`context_sources/task_skill_source_*.md`. The full installed skill remains the
audited source of truth, while the task-local SHA-256 header makes the exact
origin recoverable from each run.
