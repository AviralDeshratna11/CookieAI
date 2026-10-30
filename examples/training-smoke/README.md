# Authored training-pipeline smoke artifacts

These 24 independent synthetic examples test the preparation pipeline. They are
not a production training corpus or evidence of improved model quality.

`train.jsonl`, `validation.jsonl`, and `test.jsonl` contain 20, 2, and 2 examples.
The manifest preserves source/group lineage and permissions; the data card
records distributions and limitations. `training-plan.json` is deliberately
blocked for the current NVIDIA/account capability. Nothing has been uploaded.

Regenerate using `python -m scripts.experiment_pipeline training-data --output
examples/training-smoke`, supplying `--benchmarks` for every evaluation corpus
used in a real contamination review. See `docs/experiment-pipeline.md` for the
separate approval-gated training workflow.
