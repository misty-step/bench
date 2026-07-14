# Seam Agency v0 construct-hardening receipt

Date: 2026-07-13

Host scope: local macOS/Colima checkout. No model candidate, paid inference,
credentialed model service, Crucible edit, branch push, or site publication.

Repository branch: `codex/bench-seam-agency-v0-package`

Qualified task revision:
`bc4b8d68c6f61c1e5f5e6e39abdd44bd89822040`

## Harbor capability and receipt falsification

Before changing the package, a disposable Harbor 0.13.1 oracle task outside the
repository tested whether hidden verification could neutrally place an
immutable `crucible-semantic` command on `PATH` and retain a receipt the
candidate repository could not author.

The probe ran the candidate as the unprivileged `nobody` user, set the injected
command mode to `0555`, kept the verifier receipt directory root-only, and gave
the candidate the exact receipt path as an authorship canary. The candidate's
write attempt raised `PermissionError`; the root-owned verifier broker served a
deterministic versioned response and exported its JSONL ledger after candidate
exit.

Stable probe fields:

```json
{
  "harbor_version": "0.13.1",
  "result_id": "2db73acc-60e2-4429-9850-fb9c0fae1eb9",
  "trial_name": "task__5z6weur",
  "task_checksum": "82c523bbfe70c5116cc76740a74a125da3e561e5f86e0eb70eae4650f9c2b424",
  "reward": 1.0,
  "candidate_receipt_authorship": "blocked",
  "model": null,
  "cost_usd": null,
  "n_input_tokens": null,
  "n_output_tokens": null
}
```

The untracked probe remains under
`$HOME/.cache/bench-semantic-harbor-probe/`. This falsifies the former runner
exchange blocker: Harbor can supply the command neutrally and the verifier can
retain a receipt outside the candidate repository's authority.

## Resolved capability contract

Both tasks receive byte-identical checked-in declarations and candidate-visible
stubs:

- manifest schema `bench.runtime_capabilities.v1`;
- capability `semantic.generate.v1`;
- one-shot JSON-over-stdio command `crucible-semantic`;
- request schema `bench.semantic_generate.request.v1` with versioned messages
  and `response_schema`;
- result schema `bench.semantic_generate.result.v1` with `ok`, `refused`,
  `timeout`, `malformed_output`, and `execution_error` statuses;
- all returned content is untrusted.

Both task environments explicitly declare Harbor
`network_mode = "no-network"`; an empty allowlist is not treated as proof of
network denial.

During hidden verification the verifier supplies deterministic scenarios over
a private Unix socket and writes the ledger after candidate exit. Publication
is graded on positive causal use with the full draft, declared fields, and a
response schema. Lease is graded on zero calls and passes again with the
capability absent under Harbor's network-denied, credential-free verifier
baseline. The verifier does not inspect candidate source keywords, regexes,
prompt wording, internal API/class shape, SDK or subprocess choice, or an exact
positive call count.

## Repository-owned gold and mutation qualification

`./scripts/check.sh` qualifies two structurally distinct references per task
and six intended mutants:

```text
semantic-capability: identical manifest/command and verifier-owned receipt harness PASS
crucible-spec: valid=true runnable=true
seam-agency-review: sanitized evidence joins PASS
build-publication-assistant: reference solution PASS
build-publication-assistant: reference solution-alt PASS
build-publication-assistant: mutant missing-ai-keywords FAIL expected reason=semantic capability not causally used
build-publication-assistant: mutant ai-washed-decorative-call FAIL expected reason=semantic response did not causally control publication
build-publication-assistant: mutant under-enforced-raw-output FAIL expected reason=credential-shaped draft crossed the semantic boundary
build-claim-lease: reference solution PASS
build-claim-lease: reference solution-alt PASS
build-claim-lease: mutant unnecessary-ai-advisor FAIL expected reason=semantic capability invoked for deterministic lease
build-claim-lease: mutant under-enforced-expired-renewal FAIL expected reason=expired lease renewed
build-claim-lease: mutant inclusive-expiry-boundary FAIL expected reason=expiry equality must be expired
seam-agency-v0: package qualification PASS (4 references, 6 mutants)
```

Publication's references differ in transport and persistence structure. Lease's
references use advisory-file locking versus atomic lock-directory acquisition.
The lease verifier races eight isolated candidate processes and requires one
persisted winner, then injects an unwritable-directory failure and requires the
prior bytes to remain exact. These are package-gate qualifications, not model
attempts and not members of the 2/2 oracle score below.

## Crucible and Harbor oracle/reference qualification

Command:

```sh
crucible run benchmarks/seam-agency-v0/seam-agency-v0-harbor.json \
  --out "$HOME/.cache/bench-seam-agency-hardening-network-green" \
  --db "$HOME/.cache/bench-seam-agency-hardening-network-green.sqlite" \
  --json
```

Sanitized stable identity:

```json
{
  "run_id": "run-1783984173707-25833-0:seam-agency-v0-harbor-qualification",
  "invocation_id": "run-1783984173707-25833-0",
  "created_at_unix_ms": 1783984173707,
  "benchmark_id": "seam-agency-v0-harbor-qualification",
  "runner_kind": "harbor_task",
  "config_id": "harbor:oracle:default",
  "agent": {"name": "oracle", "version": "1.0.0"},
  "provider": null,
  "model": null,
  "git_sha": "bc4b8d68c6f61c1e5f5e6e39abdd44bd89822040",
  "model_usage": {
    "cost_usd": null,
    "n_input_tokens": null,
    "n_output_tokens": null,
    "n_cache_tokens": null
  },
  "score": {
    "metric": "harbor_reward_pass_rate",
    "successes": 2,
    "n": 2,
    "point": 1.0,
    "lower": 0.34237195288961925,
    "upper": 1.0,
    "confidence": 0.95,
    "method": "Wilson"
  }
}
```

Per-task stable identities:

| Task | Trial | Job | Evidence | Task checksum | Latency ms | Reward |
| --- | --- | --- | --- | --- | ---: | ---: |
| `build-publication-assistant` | `build-publication-assistant__6vcmGvu` | `c99c0715-bd75-4cb9-b63c-7f7400f1ae47` | `f0364606-8c46-435f-b5a0-7254d374d9f8` | `9ba2633d0e1fe0db756d45ec5cdcc7cac0604dba74c8e2784dbd47f34f313221` | 16931 | 1.0 |
| `build-claim-lease` | `build-claim-lease__GtDErFg` | `4591d82a-1246-4f67-a1e7-ca1cacd65cad` | `ffb3c274-8d84-465d-91f1-ebb683ad024b` | `85e737729e680ca0df9942aab87f10114a65870265b9c19f3e8e00e691849766` | 15207 | 1.0 |

Publication's verifier summary records positive semantic use, the full draft,
declared fields and response schema, causal publish/withhold behavior, and
blocked candidate receipt authorship. Lease's summary records zero calls,
concurrent and failure-preservation success, an absent-capability pass, and the
network-denied credential-free baseline. The full untracked run evidence is at
`$HOME/.cache/bench-seam-agency-hardening-network-green/harbor-run.json`.

This was Harbor oracle/reference qualification, not a model candidate run. The
oracle applied checked-in reference solutions. Zero economic model cost and
null token fields are expected because no model was invoked. No candidate,
provider, prompt, transcript, retry, candidate token, or candidate result was
invented.

## Fresh methodology criticism

The post-implementation criticism re-read the candidate-visible request,
capability declaration, hidden process boundary, causal scenarios, mutation
kills, lease race/failure injection, sanitized review, and Harbor 0.13.1 network
policy instead of relying on the green score alone.

It found one material overclaim: the first hardening run had empty Harbor
`extra_allowed_hosts` fields, but the task TOMLs inherited Harbor's `public`
network default. That did not prove the claimed network-denied recheck. Both
task environments now explicitly set `network_mode = "no-network"`; task
revision `bc4b8d68c6f61c1e5f5e6e39abdd44bd89822040` was then requalified through
the real Crucible-to-Harbor path, producing the current 2/2 receipt above. The
obsolete pre-fix hardening run is not used by the operator review.

After that repair, the criticism found no remaining blocker in the original
two-task hardening criteria:

1. both candidates see the identical neutral capability surface, while only
   publication needs semantic judgment;
2. publication must carry complete semantic inputs and change behavior under
   controlled publish/withhold responses, with malformed and typed failure
   envelopes treated as untrusted;
3. lease has a direct verifier-owned zero-call invariant and passes with the
   command absent under an explicit no-network policy;
4. candidate source vocabulary, prompt wording, class/API internals,
   subprocess choice, and exact positive call count are not graded;
5. the candidate process cannot author the verifier's root-owned receipt; and
6. two structurally different references pass per task while every named
   mutant fails for its intended construct reason.

The criticism does not erase the remaining evidence limitations below.

## Remaining evidence boundary

The hardening resolves the three construct blockers previously shown for the
materialized pair: prompted semantic-interface recognition, missing lease
concurrency/write-failure coverage, and indirect closed-network unnecessary-AI
detection. It does not turn the two-task public development pair into a usable
benchmark. Five declarations, independent source-clustered splits, real model
candidate evidence, calibrated judging, human audit, cross-harness comparison,
and independent packet acceptance remain missing.

Bench remains a read-only evidence consumer of Crucible and Harbor. No
Bench-specific runner or alternate control plane was added.

## Local browser inspection

The checked-in static review was served locally at
`http://127.0.0.1:8766/seam-agency-review.html` and inspected at 1440×1000 and
390×844 viewports. The index review card navigated to the page; the current
run/invocation/revision identities, score and interval, null model-use fields,
two tasks, four reference links, verifier and mutant coverage, capability
receipts, four-state evidence ledger, construct findings, readiness path, and
source links all rendered. Browser console and page-error surfaces were empty,
and full-page visual inspection found no clipping or overlap.

Supplemental untracked screenshots:

- `/tmp/bench-seam-agency-hardening-qa-20260713/screenshots/desktop-network-final.png`
- `/tmp/bench-seam-agency-hardening-qa-20260713/screenshots/mobile-network-final.png`

No site publish or push was performed.
