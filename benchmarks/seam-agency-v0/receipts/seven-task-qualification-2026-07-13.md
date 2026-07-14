# Seam Agency v0 seven-task qualification receipt

Date: 2026-07-13 (America/Chicago)

Host scope: local macOS/Colima checkout. No model candidate, model service,
credential, Crucible edit, repo-tier change, push, site publication, or public
packet publication.

Repository branch: `codex/bench-seam-agency-v0-package`

Clean source revision used by Crucible:
`17b21930c0514fb039f1eaf6bbd1f484719703de`

## Qualification boundary

This is Harbor oracle/reference qualification through Crucible's generic
`harbor_task` runner. Harbor's `oracle` agent applied one checked-in reference
per task. It is not a coding-agent or model-candidate run. Provider and model
are null, all raw token and cost fields are null, and expected economic model
cost is zero because no model was invoked.

All seven tasks expose the byte-identical `semantic.generate.v1` manifest,
one-shot JSON-over-stdio executable, and verifier fixture, and explicitly use
Harbor `network_mode = "no-network"`. Per-task qualification policy is:
positive causal full-input use for publication, incident grouping, provider
routing, and memory extraction; zero use plus capability-absent replay for
lease and comparison; observed non-scoring metadata for critique.

The critique score is limited to the deterministic versioned artifact: schema,
actual counterexample replay, expected versus observed action/state, exact
affected boundary, repair invariants, and accepted `UNKNOWN`. It does not claim
finding completeness, consequence quality, or architectural soundness.

## Clean-SHA Crucible oracle evidence

Command:

```sh
crucible run benchmarks/seam-agency-v0/seam-agency-v0-harbor.json \
  --out "$HOME/.cache/bench-seam-agency-seven-task-green" \
  --db "$HOME/.cache/bench-seam-agency-seven-task-green.sqlite" \
  --json
```

Stable run identity:

```json
{
  "run_id": "run-1783988831378-17513-0:seam-agency-v0-harbor-qualification",
  "invocation_id": "run-1783988831378-17513-0",
  "created_at_unix_ms": 1783988831378,
  "benchmark_id": "seam-agency-v0-harbor-qualification",
  "runner_kind": "harbor_task",
  "config_id": "harbor:oracle:default",
  "agent": {"name": "oracle", "version": "1.0.0"},
  "provider": null,
  "model": null,
  "git_sha": "17b21930c0514fb039f1eaf6bbd1f484719703de",
  "model_usage": {
    "cost_usd": null,
    "n_input_tokens": null,
    "n_output_tokens": null,
    "n_cache_tokens": null
  },
  "score": {
    "metric": "harbor_reward_pass_rate",
    "successes": 7,
    "n": 7,
    "point": 1.0,
    "lower": 0.6456611570247934,
    "upper": 1.0,
    "confidence": 0.95,
    "method": "Wilson"
  }
}
```

The untracked full engine artifact is
`$HOME/.cache/bench-seam-agency-seven-task-green/harbor-run.json`; the Crucible
ledger is `$HOME/.cache/bench-seam-agency-seven-task-green.sqlite`.

Mode-specific reference integration rates (never a pooled Seam Agency model
score):

| Mode | Passes | Wilson 95% interval | Claim ceiling |
| --- | ---: | --- | --- |
| Build | 3/3 | [0.43849391955098227, 1.0] | public reference integration only |
| Extend | 2/2 | [0.34237195288961925, 1.0] | public reference integration only |
| Repair | 1/1 | [0.20654329147389294, 1.0] | public reference integration only |
| Critique | 1/1 | [0.20654329147389294, 1.0] | deterministic replay artifact only |

Per-task stable identity:

| Task | Trial | Job | Evidence | Task checksum | Latency ms | Reward |
| --- | --- | --- | --- | --- | ---: | ---: |
| `build-publication-assistant` | `build-publication-assistant__8QXajCZ` | `c65d673f-26ea-462f-8c61-98c140b5f626` | `08252cb7-14ab-4bd8-ae96-53e25700335f` | `49f67bdccef52ad8429e55ae27f3a5a495393c8e5d45d70007f045b9d37939e4` | 17619 | 1.0 |
| `build-incident-grouping` | `build-incident-grouping__hqM9y8z` | `60a738c6-a702-4a60-94a3-9f7a6e6572a3` | `da38b353-6e6e-4078-9d3c-3712fd2deb25` | `0bcb8c5a2749934d8149c2a26ca240a6e4436b2ccf51c31e41b2951c7d400844` | 16921 | 1.0 |
| `build-claim-lease` | `build-claim-lease__dicVvW6` | `c946a7d6-aebe-4dfd-bb18-9b744880d8c3` | `88bc29e6-763f-4194-b7d1-96f39dcb53ea` | `a1def054a8e027c0778386fd73179b45de2de97564da3f23ec44155c4b47857b` | 20017 | 1.0 |
| `extend-provider-routing` | `extend-provider-routing__Seyh2gk` | `eca93b66-3b47-42ff-9289-27489c606f77` | `321ce34f-f32f-42b8-a1e0-151fb5e480a2` | `a7e049419af0715e3e97be6bce724ea515d0f090c4a707327718c7f0adcfa0d0` | 16663 | 1.0 |
| `extend-comparison-attribution` | `extend-comparison-attribution__3JsjnVc` | `88cb2aef-2c28-4740-aa74-15003a48465d` | `b8917b22-bbdd-4305-a6d0-10aad7100458` | `4d6e03d773cb8bed5e745c2aad4156a86ef85b06a193e474395522bc7a5b1c3d` | 17141 | 1.0 |
| `repair-memory-extraction` | `repair-memory-extraction__gGbTKiB` | `4162e24f-0f27-4d09-8ce7-42214f838672` | `3e51bbaa-143b-4404-a096-3841943831dc` | `84e753190dcf900524b38f7a525d6589fda9e607c61b6eb0a66286b4e7164f91` | 17673 | 1.0 |
| `critique-operator-action-router` | `critique-operator-action-router__dqS3stH` | `cfb53837-1fe5-452d-ae8d-a19d7dd91530` | `2ef43cf2-cd0d-401f-aff1-3d8075089b4c` | `7dc5510907b1e6db444ed12cc8819cd78b152c69d2eac731b7b38b5abb918793` | 15403 | 1.0 |

## Repository-owned reference and mutation proof

`./scripts/check.sh` runs both references for all seven tasks, requires each
reference to pass its verifier, and requires each pair to emit different
externally observed strategy markers. A prose distinction in `references.json`
alone cannot pass.

| Task | Reference 1 witness | Reference 2 witness | Mutants killed |
| --- | --- | --- | ---: |
| `build-publication-assistant` | `reference-behavior: replace-equivalent-packet` | `reference-behavior: preserve-equivalent-packet` | 3/3 |
| `build-incident-grouping` | `reference-behavior: report-id-derived-group` | `reference-behavior: report-text-derived-group` | 3/3 |
| `build-claim-lease` | `reference-behavior: ignores-unrelated-lockdir` | `reference-behavior: bounded-lockdir-refusal` | 3/3 |
| `extend-provider-routing` | `reference-behavior: sole-eligible-deterministic` | `reference-behavior: sole-eligible-semantic` | 3/3 |
| `extend-comparison-attribution` | `reference-behavior: alphabetical-attribution-order` | `reference-behavior: declared-axis-priority-order` | 3/3 |
| `repair-memory-extraction` | `reference-behavior: minimal-memory-record` | `reference-behavior: evidence-offset-record` | 3/3 |
| `critique-operator-action-router` | `reference-behavior: omit-passing-findings` | `reference-behavior: include-passing-findings` | 3/3 |

Totals: 14/14 passing references, seven behaviorally distinct pairs, and 21/21
mutants rejected at their declared observable failure marker. The executable
witnesses cover equivalent-repeat persistence, contention behavior, stable
incident-ID policy, sole-eligible routing, attribution ordering, optional
evidence offsets, and inclusion/omission of passing critique findings.

## Fresh methodology criticism and reconciliation

The fresh critic independently inspected the seven task requests, shared
capability, references and executable witnesses, verifiers, mutants, and
critique claim ceiling. It accepted the executable methodology: 14 passing
references with real behavioral distinctions, 21 intended mutant kills, no
source-keyword/prompt/trajectory proxy, and a sound replay-only critique limit.

Closeout initially remained blocked because `./scripts/check.sh` resolved
`python3` to Python 3.7.9 on this host and failed before qualification at the
`tomllib` import. The gate now requires Python 3.11+ with `tomllib`, honors an
explicit `BENCH_PYTHON`, and otherwise selects a supported interpreter
(including the critic-verified `/opt/homebrew/bin/python3.12`). The review and
validator were also reconciled from their obsolete two-task hard-codes to the
clean source SHA and current 7/7 ledger.

Final repository gate:

```sh
./scripts/check.sh
```

Expected terminal line after all joins, 14 references, and 21 mutant checks:

```text
seam-agency-v0: package qualification PASS (14 references, 21 mutants)
```

## Remaining evidence boundary

Seven public development tasks are now construct-qualified, but this is not a
usable decision benchmark. Independent private source clusters, blinded expert
gold and adjudication, a real candidate run, calibrated semantic judging,
human audit, cluster-aware inference, complete treatment identity, independent
Bench packet intake, and fail-closed disclosure remain missing. Broad critique
quality additionally remains blocked on two blinded experts plus a
decorrelated calibrated judge with fail-class precision/recall at least 0.90,
`UNKNOWN`, format/drift probes, and human adjudication.

Bench remains a read-only evidence consumer of Crucible and Harbor. No
Bench-specific runner or alternate control plane was added.
