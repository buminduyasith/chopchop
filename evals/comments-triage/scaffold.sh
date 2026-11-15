#!/usr/bin/env bash
# Build the refunds sample, then drop review comments for a payments-api PR next to it.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
python3 "$here/../sample-project/setup.py" --to .
cp "$here/review.json" ./review.json
