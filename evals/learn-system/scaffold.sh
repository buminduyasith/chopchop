#!/usr/bin/env bash
# Build the refunds sample (4 git repos with traps and a chopchop workspace) in the empty workspace.
set -euo pipefail
python3 "$(cd "$(dirname "$0")" && pwd)/../sample-project/setup.py" --to .
