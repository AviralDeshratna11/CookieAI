#!/usr/bin/env bash
# Installation and offline preparation only. Does not run paid inference.
set -euo pipefail
cd "$(dirname "$0")/../.."
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip git
python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements.lock
.venv/bin/python -m pip install -q --no-deps -e .
.venv/bin/python scripts/setup_hermes.py
.venv/bin/python -m pytest tests/unit/test_cloud_benchmark.py tests/unit/test_architecture_launch_review.py tests/unit/test_experiment_pipeline.py tests/unit/test_benchmark_harness.py -q
.venv/bin/python -m scripts.benchmark_cloud_runner prepare
