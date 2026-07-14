#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

if [ -n "${BENCH_PYTHON:-}" ]; then
  bench_python=$BENCH_PYTHON
else
  bench_python=
  for candidate in /opt/homebrew/bin/python3.12 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys, tomllib; raise SystemExit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
      bench_python=$candidate
      break
    fi
  done
fi

if [ -z "$bench_python" ]; then
  echo "bench check: Python 3.11+ with tomllib is required (set BENCH_PYTHON to override)" >&2
  exit 1
fi

"$bench_python" scripts/validate_seam_agency.py
git diff --check
