#!/usr/bin/env bash
# Run one headless chopchop stage in a trial folder and keep its output.
# usage: run_stage.sh <trial dir> <stage name> "<prompt>" [max turns]
set -uo pipefail
dir="$1"; name="$2"; prompt="$3"; turns="${4:-200}"
logs="$(cd "$(dirname "$0")" && pwd)/trial-logs"
mkdir -p "$logs"
out="$logs/$(basename "$dir")-$name"
cd "$dir"
start=$(date +%s)
claude -p "$prompt" \
  --plugin-dir /Users/buminduyasith/mydata/work/chopchop-v2 \
  --permission-mode dontAsk \
  --allowedTools "Read,Glob,Grep,Write,Edit,Bash,Skill,Agent,Task,TodoWrite,SendMessage" \
  --model sonnet --max-turns "$turns" --output-format json > "$out.json" 2> "$out.err"
code=$?
end=$(date +%s)
python3 - "$out.json" "$out.txt" "$code" "$((end-start))" <<'PY'
import json, sys
src, dst, code, secs = sys.argv[1:5]
try:
    d = json.load(open(src))
except Exception as e:
    open(dst, "w").write("could not read json: %s\n" % e); print("stage failed: no json, exit", code); sys.exit(0)
text = d.get("result") or ""
usage = d.get("usage") or {}
head = "exit %s · %ss · turns %s · cost $%s · in %s out %s · error=%s\n\n" % (
    code, secs, d.get("num_turns"), d.get("total_cost_usd"), usage.get("input_tokens"), usage.get("output_tokens"), d.get("is_error"))
open(dst, "w").write(head + text + "\n")
print(head.strip()); print(text[-1800:])
PY
