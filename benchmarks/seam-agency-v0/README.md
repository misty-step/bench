# Seam Agency v0

Status: qualification package; no agent ranking or public model claim.

Seam Agency asks a bounded product-engineering question:

> Given a compact repository and a behavioral feature request, can an agent
> recognize whether model-native judgment is necessary, implement it causally
> at the semantic seam, keep exact mechanisms deterministic, and leave the
> requested behavior working?

Bench owns this benchmark family: its construct, corpus, task gold, verifier
policy, analysis, and publication decision. Crucible is the generic evaluation
engine/workbench and Harbor is the generic sandbox/task contract. Neither owns
the benchmark, and there is no Bench-only runner or adapter.

## Decision and scope

The eventual decision is whether a declared agent configuration may implement
an AI-bearing feature without mandatory seam-placement review. V0 only
qualifies the task and verifier shape. The checked-in matched pair proves that
one AI-required Build task and one deterministic Build control have solvable
requests, passing references, and mutation-sensitive deterministic verifiers.
It does not measure an agent.

The binary implementation headline requires both correct product behavior and
an acceptable boundary. Tracked dimensions explain a failure; they cannot
average a policy bypass or decorative model call into a pass.

## Modes are separate capabilities

| Mode | Starting state | What a pass can establish |
|---|---|---|
| **Build** | A neutral pre-feature repository plus a behavioral request. | The agent can discover whether AI is needed and construct the boundary. This is the primary capability. |
| **Extend** | A sound but incomplete feature. | The agent can preserve the boundary while adding a case or capability. |
| **Repair** | A plausible implementation with a wrong-layer seam. | The agent can detect and reverse a boundary inversion. |
| **Critique** | A blinded candidate design or patch. | The agent can diagnose seam quality; this is not implementation evidence. |

Report a rate and interval for each mode. Never pool unlike modes into a single
"Seam Agency score." Reweighting is allowed only from a declared target
workload distribution fixed before results are seen.

## Outcome taxonomy

- **well-factored:** model-native judgment is causally used only where meaning
  requires it; variable structure is declarative; exact enforcement is code;
- **missing-AI:** semantic behavior is omitted or replaced by keyword, regex,
  similarity, enum, or branch heuristics;
- **AI-washed:** a model call exists but its result does not cause the semantic
  behavior;
- **over-determinized:** a model is present, but rich meaning is collapsed into
  brittle handcrafted categories or scoring machinery before judgment;
- **under-enforced:** raw or weakly parsed model output controls policy,
  authorization, persistence, filesystem effects, or exact state transitions;
- **unnecessary-AI:** a model dependency is added to an exact deterministic
  operation;
- **functional-wrong-seam:** visible examples work but held-out semantic,
  safety, or extension mutations expose the boundary error;
- **nonfunctional:** the requested behavior or ordinary regressions fail.

## Corpus and gold governance

The committed v0 pair is a clean-room public development corpus written for
Bench. It contains no copied project history, proprietary material, live
credentials, network dependency, or hidden scoring material. Each task starts
from a compact pre-feature repository, a behavioral request, an independently
authored references, named plausible wrong-seam mutants, and a deterministic
verifier.

A decision-grade corpus must be split by source incident and repository family:

- **development:** public tasks and references for harness bring-up;
- **calibration:** private tasks for verifier and model-judge calibration;
- **test:** private frozen tasks for comparisons;
- **renewal:** post-cutoff cases added on a declared cadence.

Sibling variants and repeated trials are clustered observations, not new
independent tasks. Hidden tests may vary examples and adversarial responses,
but may not introduce unstated product requirements. Two experts must agree on
the behavior, AI-necessity ruling, seam map, and invariants before model output
is reviewed; a third adjudicates disagreements. Public development references
are not evidence about held-out performance. Active calibration/test references
remain private and receive provenance/disclosure receipts before any run.

Every qualified task needs a passing reference, a structurally different
acceptable implementation before it enters the headline set, and at least two
applicable wrong-layer implementations rejected for the intended reason. Each
materialized task now has two passing references with different coordination
and persistence structures. That removes the alternative-reference blocker for
this pair; it does not qualify the five unmaterialized declarations.

## Shared runtime capability

Both materialized tasks expose the identical candidate-visible
`bench.runtime_capabilities.v1` manifest and immutable one-shot
`crucible-semantic` executable. The declared `semantic.generate.v1` transport
accepts a versioned JSON request on standard input, including messages and a
response schema, and returns a versioned `ok`, `refused`, `timeout`,
`malformed_output`, or `execution_error` result. Every returned content field is
untrusted.

The task request does not tell the publication candidate to call this
capability, and the matched lease control receives the same declaration. The
verifier supplies deterministic scenario responses only during hidden
verification. Candidate code runs unprivileged; the verifier-owned broker keeps
its invocation ledger outside the candidate repository and writes the receipt
after candidate exit. Publication is graded on positive causal use carrying the
full draft, declared fields, and a response schema. Lease is graded on a direct
zero-call receipt and runs again with the capability absent under Harbor's
network-denied, credential-free verifier baseline. No source keyword, regex,
prompt wording, internal class/API shape, SDK, subprocess library, or exact
positive call count is graded.

## Verifier ladder

1. **Deterministic headline:** build, observable behavior, adversarial model
   responses, invalid-output refusal, authorization/persistence/atomicity,
   offline execution, and bounded resources.
2. **Tracked dimensions:** judgment placement, declaration use, parsing, and
   deterministic enforcement. These explain the binary result.
3. **Calibrated model judge:** initially non-headline and limited to coherence
   or shallow-wrapper detection; it requires blinded independent human labels,
   `UNKNOWN`, drift probes, and fail-class precision/recall.
4. **Human audit:** inspect all verifier/judge disagreements, every novel pass,
   and a predeclared sample of other outcomes.

For AI-required tasks, the verifier controls the declared runtime capability and
requires the behavior to change with its response. A decorative call fails. For
negative controls, the task must succeed offline with no model credential or
service and the verifier-owned ledger must remain empty. The verifier grades
final state and the causal positive/zero-use boundary, not a prescribed SDK,
prompt, exact positive call count, or edit trajectory.

## Seven-task qualification manifest

[`qualification.json`](qualification.json) is the machine-readable source of
truth. The set contains three Build tasks (including the matched pair), two
Extend tasks, one Repair task, and one Critique task. Each entry fixes the
visible request, seam conflict, invariants, forbidden outcomes, required
mutations, hidden-policy ruling, and qualification state before agent runs.

The first matched pair is materialized under `harbor/`:

- `build-publication-assistant`: semantic disclosure/field drafting is causal;
  secret-shape refusal, declared fields, typed parsing, and atomic writes are
  deterministic.
- `build-claim-lease`: ownership, renewal, and expiry are exact; a model
  dependency is itself a failure.

Each is a standard Harbor task directory with `instruction.md`, an environment
microrepository, `solution/`, `solution-alt/`, `tests/`, and `mutants/`. The standard generic
Crucible spec [`seam-agency-v0-harbor.json`](seam-agency-v0-harbor.json) points
at the two tasks and uses Harbor's `oracle` agent only to qualify references.

## Experiment axes and statistics

Change one declared axis at a time: model, articulation/prompt, harness,
reasoning effort, tool envelope, frozen context packet, optional skill, frozen
memory packet, one bounded critique turn, or role topology. Hold task snapshot,
resource envelope, budgets, and every other axis fixed. Record actual model,
provider, response model, harness/adapter version, prompt hashes, tools, effort,
workspace revision, resource limits, transcript, retries, latency, and cost.

Run a small qualification pilot before a broad matrix. Repeat near-threshold
configurations three times; report both pass@3 and pass^3 while treating the
source task as the independent unit. Use paired comparisons on identical tasks.
Report mode-specific intervals, discordant-pair analysis, and the minimum
effect of interest. Do not call seven public tasks a population estimate, and
do not turn an inconclusive difference into a ranking.

## Publication and limitations

No v0 score is published. A future packet must expose task/mode counts,
cluster structure, calibration and disagreement, deterministic and judge
evidence, uncertainty, costs, runtime identity, disclosure decisions, and the
exact reason each comparison is claimed or withheld.

The current limitations are material:

- only two of seven qualification tasks are implemented;
- public development tasks cannot estimate held-out agent capability;
- the deterministic verifier cannot by itself validate broad architectural
  coherence outside its adversarial cases;
- the atomic-write checks now prove replacement, refusal preservation, and
  preservation under an injected unwritable-directory failure, not durability
  across an operating-system or storage crash;
- the controlled semantic fixture proves causal integration with the declared
  capability, not the quality, calibration, or cost of any real model;
- cross-harness identity, resource equality, transcripts, and primitive
  treatments are not yet available through one trusted generic engine receipt;
- cluster-aware inference and safe public disclosure are not complete.

Exact live engine gaps and the evidence boundary are recorded in
[`engine-gaps.md`](engine-gaps.md). The repository-owned qualification command
is `./scripts/check.sh`; it validates the package, runs both references for each
materialized task, and
proves every named mutant fails. That command is a gold-package check, not an
agent runner.
