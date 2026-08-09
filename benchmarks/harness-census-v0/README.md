# Harness Census v0

This package qualifies three history-free task images for the model-harness census.

## Decision contract

This pilot decides whether each harness and composition is reliable enough for a larger study.
It does not select a winning harness or justify deleting agent context.
Three task buckets can resolve only a one-point paired delta.
Crucible therefore labels every paired interval as descriptive and non-inferential.
It reports no winner, directional claim, or deployment recommendation.
Any reliability failure invalidates the cell.
All three tasks must hard-pass before a controlled pair enters the descriptive comparison.
The study must add at least three independent task buckets and pass a prospective power check before any inferential comparison.

## Corpus contract

Bench owns the corpus, graders, references, alternatives, mutants, and run procedure.
Each task comes from a pinned pre-fix commit in a different repository and source cluster.

| Task | Missing behavior at the source SHA | Passing behavior |
| --- | --- | --- |
| `iron-forest-go-checkruns-array` | GitHub check-run object parsing | Parse populated and empty `check_runs` arrays without losing failed names or conclusions. |
| `estate-pagination-origin` | Pagination origin enforcement | Follow relative or same-origin links and reject cross-origin or scheme-relative links before requests. |
| `sploot-hydration-device-lane` | Hydration-safe device selection | Keep server and hydration output on desktop, then select iOS or Android through an external store. |

Qualification proves each reference and independent alternative scores 1.
It proves unchanged sources, mutants, syntax failures, and scope violations score 0.
The three source clusters are the paired units.
The corpus has no power for a deployment decision.

## Live readiness status

The deterministic nine-cell preflight passed on 2026-08-08.
It built all nine worker images and passed all 27 hidden-reference checks.
The OpenRouter Mint route served a bounded DeepSeek probe.
The same route refused `anthropic/claude-opus-5` because no endpoint matched the account privacy policy.
The direct Anthropic Mint alias was not configured.
No coding task produced model output, so the pilot has no capability result.
Do not change the model or privacy policy inside a frozen campaign.


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
Before any provider call, the driver starts the Compose topology. It confirms
that `main` cannot reach `1.1.1.1` and can reach only `mint-gateway`.
It also builds all nine harness-task images and runs their hidden references.
One live cell validates execution and evidence only.
Run all six controlled cells to produce paired descriptive deltas.
Native-default cells remain separate observational baselines.



Run one task as the live readiness canary after the full matrix passes validation:

```sh
LIVE_ROOT="$PWD/.harness-census-live-run"
python3 scripts/run_harness_census.py --cell omp-controlled_raw --task iron-forest-go-checkruns-array --max-cells 1 \
  --campaign-root "$LIVE_ROOT" \
  --source-root "$SOURCE_ROOT" \
  --adapter-root "$ADAPTER_ROOT" \
  --prime-package-dir "$PRIME_PACKAGE_DIR" \
  --crucible /path/to/crucible
```

Accept readiness only when the canary writes one canonical quality receipt.
Stop when it writes a reliability receipt or when the provider refuses the configured model.
After acceptance, resume the same frozen campaign without `--task` to run the two pending tasks.
Run the matching enriched cell only after the raw cell completes.
Run the remaining controlled pairs only after both first-pair cells complete.
Run native-default cells last because their observed identity needs three consistent passed attestations.

Resume the same frozen campaign after an interruption:

```sh
python3 scripts/run_harness_census.py --resume \
  --campaign-root "$LIVE_ROOT" \
  --source-root "$SOURCE_ROOT" \
  --adapter-root "$ADAPTER_ROOT" \
  --prime-package-dir "$PRIME_PACKAGE_DIR" \
  --crucible /path/to/crucible
```

Resume verifies frozen stage, task, adapter, context, grader, and receipt identities.
It runs only tasks without a canonical receipt.
It reconstructs derived cell results from canonical receipts when needed.


Each campaign is stored under the explicit `--campaign-root`:

```text
stage-manifest.json
campaign.json
runs/campaign.sqlite
bin/harbor
cells/<harness>-<composition>/{eval.json,request.json,result.json,tasks/}
exchange/<cell>/<task>/{request,result,trial,grader}.json
```

Quality outcomes write Harbor's canonical `{"reward": <number>}` map as `verifier/reward.json` and the detailed deterministic grader report as `verifier/grader-report.json`. Reliability outcomes write no grader receipt; they persist typed failure fields with null scores and retain transcript and attestation evidence when present.

The driver exports each pinned source SHA without Git history and writes a cell-specific Dockerfile.
It uses lock-backed Bun and pnpm packages for every worker image.
Prime also installs its checked-in dependency lock before the in-image CLI probe.
Prime workers relax only Docker's seccomp filter for Bubblewrap user and network namespaces.
They add no container capability, and the inner kernel remains network-isolated.
It mounts the hidden content manifest and deterministic grader only through
`tests/test.sh`.
Each staged task also contains a pinned Node Mint gateway and `docker-compose.yaml`.
The Compose `main` service joins only the internal network. The
`mint-gateway` sidecar joins the internal and egress networks and forwards
only `/proxy/https/openrouter.ai/api/v1` to the fixed Mint upstream.
The sidecar runs as a non-root UID with a read-only root filesystem, all
Linux capabilities dropped, and `no-new-privileges` enabled.
Harbor task TOML declares `network_mode = "public"` so Harbor uses the staged
Compose topology. The internal Compose network enforces worker isolation.
Every cell passes `mint_base_url=http://mint-gateway:4949/proxy/https/openrouter.ai/api/v1`.
The adapter accepts this URL or the default Mint URL only.
Transport mode remains `allowlist`; metadata names enforcement as
`docker_internal_mint_gateway` and task isolation as `docker_internal_network`.
Native Harbor configs omit `model`, `thinking`, and default overrides. Fresh
harness settings resolve model and effort. Native Runner Exchange candidates
keep requested model and reasoning effort null, while census payloads carry
`effort_source` and receipts carry observed resolved identity and the fixed
`adapter_attestation:observed-native` model source.
The process guard also requires the exact internal Mint endpoint and value-free
OpenRouter marker before launch.
Native results must report one `openrouter/<model>` identity.
Controlled results must report the requested model and effort.
The gateway constrains destination and path, but it does not issue a broker-signed
receipt for the request body.
Treat a harness that misreports its OpenRouter request model as a residual pilot risk.

Controlled requests use Harbor `model` and `thinking` with exactly
`openrouter/anthropic/claude-opus-5`.

Controlled OMP and Pi expose only read, edit, and write tools. Controlled Prime runs IPython inside a clean `bwrap --unshare-net` sandbox.
The task graders are deterministic and binary.
Reference patches and independent valid alternatives must score 1.
Mutants, unchanged sources, syntax failures, and scope violations must score 0.
The pilot uses no model judge, so it needs no model-judge calibration sample.
