#!/usr/bin/env bash
set -euo pipefail

# Create a clean source archive for review/AI without .git, caches, venvs, .env, etc.
# Uses git-tracked files only, so the output is deterministic and safe.

root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$root" ] || [ ! -d "$root/.git" ]; then
  echo "ERROR: run inside a git repo (main project root)."
  exit 2
fi

cd "$root"

ts="$(date -u +%Y-%m-%d_%H%M%S)"
out="${1:-/media/nik/0C30B3CF30B3BE50/Загрузки/adaspeas_src_${ts}.tar.gz}"

mkdir -p "$(dirname "$out")"
git archive --format=tar.gz -o "$out" HEAD

echo "OK: $out"
