# Harness Census v0

This package qualifies three history-free task images for the model-harness census.

Run the repository-owned qualification command with the required source root:

```sh
python3 scripts/qualify_harness_census.py --source-root /path/to/source-root
```

The command reads only the pinned local repositories. It exports each pre-fix
SHA without Git history, applies the checked-in reference or mutant patch, and
runs a deterministic grader outside the worker image. It writes one sanitized
JSON qualification receipt per task under `benchmarks/harness-census-v0/receipts/`.

The command also regenerates the deterministic smoke files:

- `smoke/stage-manifest.json`;
- `smoke/harness-census-v0.json`.

The smoke records staging identity only. It does not confirm provider availability or infer availability from requested model strings.

Task source bytes, Git history, references, and hidden graders are not checked
in. Harbor templates describe the runtime source export and permitted edits.


Run the nine-cell campaign driver with explicit operator-supplied roots:

```sh
SOURCE_ROOT=/path/to/source-root
ADAPTER_ROOT=/path/to/crucible/harbor_agents
PRIME_PACKAGE_DIR=/path/to/prime-agent
DRY_RUN_ROOT="$PWD/.harness-census-dry-run"
python3 scripts/run_harness_census.py --dry-run \
  --campaign-root "$DRY_RUN_ROOT" \
  --source-root "$SOURCE_ROOT" \
  --adapter-root "$ADAPTER_ROOT" \
  --prime-package-dir "$PRIME_PACKAGE_DIR"
```

The dry-run prints 9 cells and 27 trials, makes zero provider calls, and records
the quality and scope probes. Native cells start with null requested and
resolved identity. A live native cell resolves one common model, effort, and
effort source from its three adapter attestations.

Select bounded live smoke after the full matrix passes validation:

```sh
LIVE_ROOT="$PWD/.harness-census-live-run"
python3 scripts/run_harness_census.py --cell omp-controlled_raw --max-cells 1 \
  --campaign-root "$LIVE_ROOT" \
  --source-root "$SOURCE_ROOT" \
  --adapter-root "$ADAPTER_ROOT" \
  --prime-package-dir "$PRIME_PACKAGE_DIR" \
  --crucible /path/to/crucible
```

Each campaign is stored under the explicit `--campaign-root`:

```text
stage-manifest.json
campaign.json
runs/campaign.sqlite
bin/harbor
cells/<harness>-<composition>/{eval.json,request.json,result.json,tasks/}
exchange/<cell>/<task>/{request,result,trial,grader}.json
```

Quality outcomes write the numeric Harbor reward as `verifier/reward.json` and the detailed deterministic grader report as `verifier/grader-report.json`. Reliability outcomes write no grader receipt; they persist typed failure fields with null scores and retain transcript and attestation evidence when present.

The driver exports each pinned source SHA without Git history, writes a
cell-specific Dockerfile, installs Bun with `npm install -g bun@1.3.14`, and
mounts the hidden content manifest and deterministic grader only through
`tests/test.sh`. Native Harbor configs omit `model`, `thinking`, and default
overrides; they carry only `composition=native_default` and the exact Mint
egress host. Fresh harness settings resolve model and effort. Native Runner
Exchange candidates keep requested model and reasoning effort null, while
census payloads carry `effort_source` and receipts carry observed resolved identity
and the fixed `adapter_attestation:observed-native` model source. Controlled
requests use Harbor `model` and `thinking` with exactly
`openrouter/deepseek/deepseek-v4-flash-0731`.

Controlled Docker trials use `network_mode = "public"` for Harbor transport. The worker and task both enforce `tool_surface_no_network_tool`; adapters expose no network-capable agent tool.

Native-default trials use `network_mode = "no-network"`. The worker and task use Mint authority through `host_allowlist_mint` and the `agent_allowed_hosts` entry. Native Docker execution is not claimed by this package.
