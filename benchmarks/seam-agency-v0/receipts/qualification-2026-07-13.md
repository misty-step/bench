# Seam Agency v0 qualification receipt

Date: 2026-07-13

Host scope: local macOS/Colima checkout; no paid inference and no credentialed
model judge.

Repository branch: `codex/bench-seam-agency-v0-package`

## Repository-owned gold check

Command:

```sh
./scripts/check.sh
```

Result:

```text
crucible-spec: valid=true runnable=true
build-publication-assistant: reference PASS
build-publication-assistant: mutant missing-ai-keywords FAIL expected reason=reviewer must receive the full draft and declared fields
build-publication-assistant: mutant ai-washed-decorative-call FAIL expected reason=packet shape mismatch
build-publication-assistant: mutant under-enforced-raw-output FAIL expected reason=credential shape must refuse
build-claim-lease: reference PASS
build-claim-lease: mutant unnecessary-ai-advisor FAIL expected reason=urlopen error
build-claim-lease: mutant under-enforced-expired-renewal FAIL expected reason=expired lease renewed
build-claim-lease: mutant inclusive-expiry-boundary FAIL expected reason=expiry equality must be expired
seam-agency-v0: package qualification PASS (2 references, 6 mutants)
```

This checks gold and mutation coverage. It does not execute an agent.

## Generic Crucible and Harbor oracle proof

Versions observed:

```text
crucible 0.0.0
harbor 0.13.1
Docker 29.2.1
```

Command (the output and ledger deliberately live under `$HOME` for Colima):

```sh
crucible run benchmarks/seam-agency-v0/seam-agency-v0-harbor.json \
  --out "$HOME/.cache/bench-seam-agency-preflight-green" \
  --db "$HOME/.cache/bench-seam-agency-preflight-green.sqlite" \
  --json
```

Relevant stable report fields:

```json
{
  "schema_version": "crucible.run_report.v1",
  "id": "seam-agency-v0-harbor-qualification",
  "metric": "harbor_reward_pass_rate",
  "successes": 2,
  "n": 2,
  "point": 1.0,
  "lower": 0.34237195288961925,
  "upper": 1.0,
  "confidence": 0.95,
  "method": "Wilson",
  "agent": "oracle"
}
```

The full untracked evidence remains at
`$HOME/.cache/bench-seam-agency-preflight-green/harbor-run.json`. Oracle applied the
checked-in solutions through the public Harbor contract. This proves reference
and verifier integration, not coding-agent capability.

### Sanitized run identity for human review

The Bench review surface checks in only the non-local identity and result fields
needed to interpret the run. Local cache paths and artifact URIs are excluded.

```json
{
  "run_id": "run-1783975121483-94811-0:seam-agency-v0-harbor-qualification",
  "invocation_id": "run-1783975121483-94811-0",
  "created_at_unix_ms": 1783975121483,
  "benchmark_id": "seam-agency-v0-harbor-qualification",
  "runner_kind": "harbor_task",
  "config_id": "harbor:oracle:default",
  "agent": {"name": "oracle", "version": "1.0.0"},
  "provider": null,
  "model": null,
  "git_sha": "36515473b77cbed2a3a8b9ab7a4182f0cc86b4d2",
  "model_usage": {
    "cost_usd": null,
    "n_input_tokens": null,
    "n_output_tokens": null,
    "n_cache_tokens": null
  }
}
```

The null usage fields are expected: Harbor's oracle copied the reference
solutions and invoked no model. Therefore the economic model cost is zero, not
an unreported candidate cost. There was no candidate model, provider, prompt,
transcript, or token usage to report.

Per-task stable identities:

| Task | Trial | Job | Evidence | Task checksum | Latency ms | Reward |
| --- | --- | --- | --- | --- | ---: | ---: |
| `build-publication-assistant` | `build-publication-assistant__NxuCyLi` | `5fb65f16-0e53-496b-8d28-7a1e6d397fb3` | `0245a5e8-75c0-4273-8ca8-cdebaf8c8fbb` | `469f36a03836c452568eaed2db138933effeb8edf31e473d067626b900d411c6` | 15798 | 1.0 |
| `build-claim-lease` | `build-claim-lease__iyd92mH` | `031d92f1-0690-4b9d-b14b-a03b20502f96` | `a35b9958-dfb5-496c-8dfd-b23c3e5a8deb` | `7790388f66d868aea1cbe53ccd27c8695c001c7f0fc883cce715b13c86cb3b15` | 15559 | 1.0 |

The complete sanitized review data is checked in at
`docs/data/reviews/seam-agency-v0-qualification.json`.

## Negative engine receipts

The same run with `--out /tmp/bench-seam-agency-v0-run` exited 0 but reported
0/2. Both task rows contained:

```text
RewardFileNotFoundError: No reward file found at
/tmp/bench-seam-agency-v0-run/harbor-jobs/<task>/run/<trial>/verifier/reward.txt
or .../verifier/reward.json
```

Moving only the output/ledger under `$HOME` changed the result to 2/2. This is
an infrastructure/mount state, not model or task evidence.

The installed generic importer also refused the current task format:

```text
crucible import harbor ...
error: no Harbor task directory ... could be imported (2 entries, all skipped):
task.toml does not declare a [task] section
```

The hand-authored public `crucible.eval_spec.v1` validates and runs, so the
incompatibility is isolated to the installed import/preflight path. Finally,
`harbor tasks check` is removed and `harbor check` refused without an
`ANTHROPIC_API_KEY`; no credential or paid quality check was supplied.

### Source reconciliation — 2026-07-13

The negative receipts above remain the observed behavior of the installed
`crucible 0.0.0`; they must not be read as current Crucible source truth.
Concurrent, unpushed Crucible commit `baa92e2` now handles current Harbor task
imports and portable task-path rebasing, with its oracle/nop consumer proof
green. Commit `10044b5` now preflights Harbor output paths outside `$HOME`.
Together they close the source defects behind the importer and `/tmp` receipts;
the installed binary used by this Bench run has not yet incorporated them.

## Fresh post-implementation review

Review scope: methodology completeness, request solvability, mutation kill
reasons, public-boundary honesty, staged diff, and Crucible repository
isolation.

Findings and resolutions:

1. `engine-gaps.md` initially said the installed Crucible imported current
   Harbor tasks, contradicting the captured importer failure. The claim was
   narrowed to what was actually proven: validate and run.
2. The publication reference rejected credential-shaped drafts but did not
   independently reject a credential shape introduced by reviewer output. The
   deterministic boundary and adversarial verifier now refuse both inputs and
   outputs.
3. The manifest gate asserted that pooling was forbidden but did not verify the
   declared four separate rate names. It now requires the exact Build, Extend,
   Repair, and Critique set.
4. The root README described every benchmark as a prompt-style
   `references.json` package. Discovery text now distinguishes prompt reference
   answers from agentic reference implementations and mutants.

After fixes, `./scripts/check.sh`, JSON/Python/shell syntax checks,
`git diff --cached --check`, and the generic Crucible→Harbor oracle run all
passed. The staged diff changes only Bench-owned files. The Crucible checkout
was inspected read-only and had pre-existing concurrent branch/backlog state;
no Crucible file was staged or edited by this lane.

## Bench human-review surface — 2026-07-13

Bench now renders the sanitized receipt at
`docs/seam-agency-review.html`. The page is a read-only evidence consumer: it
contains no run controls and does not act as a Crucible or Harbor control plane.

Fresh evidence review cross-checked every displayed run, invocation, revision,
score, interval, task checksum, trial, job, evidence ID, latency, reward, and
null model-usage field against the current successful ledger at
`$HOME/.cache/bench-seam-agency-preflight-green.sqlite` and its
`harbor-run.json`. The repository gate additionally joins the page data to the
checked-in Seam Agency declarations, Crucible spec, source paths, reference
coverage, and mutant manifests.

The review also surfaces three benchmark blockers found in the checked-in pair:

1. `build-publication-assistant` supplies a `ReviewBoundary` protocol and tells
   the candidate that a reviewer interprets the full draft. This qualifies
   causal semantic use against keyword and decorative-call mutants, but weakly
   tests independent recognition that AI is necessary.
2. `build-claim-lease` does not yet test concurrent acquisition or injected
   write failure despite its exact/atomic contract.
3. `unnecessary-ai-advisor` is killed through closed-network `urlopen`, which
   is an indirect dependency proxy rather than a direct architectural
   assertion about an unnecessary AI boundary.

Local browser QA at
`http://127.0.0.1:8766/seam-agency-review.html` confirmed the title, every
evidence section, current preflight-green identities, index-card navigation,
full-page visual layout, and an empty browser console/error surface. The
supplemental untracked screenshot receipt is
`/tmp/bench-seam-agency-review.png`. No site publication or branch push was
performed.

### Construct-hardening reconciliation — 2026-07-13

This receipt is the pre-hardening baseline and its three browser-review
blockers should not be read as current package truth. The matched pair now uses
an identical neutral `semantic.generate.v1` capability declaration with a
verifier-owned positive/zero-use ledger; publication no longer receives the
former `ReviewBoundary` protocol; lease now covers concurrent acquisition and
injected write-failure preservation; and the unnecessary-AI mutant is rejected
by a direct capability invocation receipt rather than `urlopen`. Each task also
has two structurally distinct passing references. Current identities, limits,
and proof are in
`benchmarks/seam-agency-v0/receipts/construct-hardening-2026-07-13.md` and the
checked-in review data.
