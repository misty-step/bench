# Bench

Bench is a public benchmark laboratory for language models, harnesses, and
agents. It publishes small, sharp, independently reproducible measurements with
the evidence needed to understand every score and the restraint to leave weak
comparisons unclaimed.

Bench is a long-lived open-source product, not a private leaderboard export. It
should be useful to model users, agent builders, benchmark authors, and
researchers who want to answer a bounded capability question without trusting a
vendor chart or reconstructing the method from a blog post.

## The public artifact is the product

A Bench result is not a score row. It is a versioned research packet:

- the exact benchmark definition and clean-room task corpus;
- the construct and decision the benchmark is designed to inform;
- reference answers and near-misses that prove the grader is testing the stated
  rule;
- model, provider, served response model, harness, prompt, sampling, resource,
  and relevant runtime identity;
- per-task evidence, aggregate uncertainty, paired comparisons, costs, and
  known measurement artifacts;
- the methodology, limitations, and interpretation written after the run;
- provenance connecting the packet to the benchmark revision and the engine
  contract that produced it.

The website renders those artifacts. Editorial design should make the method,
uncertainty, task evidence, and caveats easier to understand; it must never
invent claims that are absent from the packet or notes.

## A strict Crucible consumer

Bench owns its public benchmark definitions, clean-room corpora, reference and
near-miss answers, methodology, notes, publication choices, and presentation.
[Crucible](https://github.com/misty-step/crucible) owns the generic evaluation
engine, trust transitions, run evidence, versioned process and artifact
protocols, and safe publication machinery.

The boundary is deliberately hard:

- Bench receives no privileged Crucible code path or Misty Step-only adapter.
- A result must be reproducible through the same public CLI or MCP contract an
  outside repository receives.
- Bench validates the packet schema, provenance, disclosure decision, and
  benchmark join independently before accepting publication.
- Crucible may use Bench as a compatibility fixture, but Bench requirements do
  not leak into generic engine policy.
- Breaking protocol changes are explicit during the pre-1.0 proof period;
  published editions remain interpretable and link to the contract that wrote
  them.

This separation is what makes Bench credible as both a public laboratory and a
reference consumer. If the engine can only publish Bench by knowing Bench, the
reference proof is circular.

## Honesty before breadth

Bench publishes only claims the measurement can support.

- Graders must test the semantic and structural requirements named by the task,
  not a convenient proxy while the headline implies the full construct.
- Reference answers must pass; designed near-misses must fail for the intended
  reason.
- Task families, repeated trials, clustering, multiplicity, and uncertainty
  must match the inference being made. A confidence interval over a fixed task
  set does not establish every source of model or task variance.
- Provider substitutions, truncations, timeouts, refusals, parse errors, and
  undeclared reasoning settings are measurement states, not ordinary model
  failures.
- Public corpora carry contamination and freshness limitations. Hidden or
  spend-once material, when needed, must have a reviewable governance story
  rather than a secret benchmark theater.
- Model or agent judges require independently grounded calibration. Author
  declarations alone are not gold labels.
- An inconclusive paired result is a result. Bench does not manufacture a
  ranking from a gap below the measurement’s resolution.

The Constraint Gauntlet is intentionally a narrow deterministic sensor of
countable instruction constraints. It is not a general intelligence score and
must not be marketed as one. New families should add distinct, defensible
constructs rather than merely more models on the same leaderboard.

## Publication is an explicit safety boundary

Private run records may contain proprietary prompts, source material, raw model
outputs, labels, traces, repository identity, or other sensitive data. Nothing
becomes public merely because Crucible can serialize it.

Every publication must pass a deny-by-default disclosure gate. Public prompts,
outputs, system prompts, provenance, and context are either born from a declared
clean-room corpus or explicitly reviewed, sanitized, and allowlisted. The packet
records that decision. Bench rejects packets that lack the required safety,
schema, provenance, benchmark-consistency, and trust evidence.

Publication must also be operationally boring: deterministic validation,
atomic output, an immutable or checksummed packet, a reviewable manifest change,
and visible failure rather than a partially rendered page.

## The first proof horizon

Over the next 6–12 months, Bench should prove that the Crucible contract can
support a credible public laboratory without bespoke infrastructure:

1. the current constraint benchmark is narrowed and hardened so every grader
   matches its claim, its statistical scope is explicit, and its publication is
   independently checked;
2. at least one additional benchmark family measures a materially different AI
   behavior and exercises an appropriate mixed deterministic, model, and human
   judgment path;
3. a cold external user can install Crucible, reproduce a published result with
   their own key, inspect any provider drift, and understand why the comparison
   is claimed or withheld;
4. the repository gate validates definitions, references, near-misses, packets,
   manifests, publication safety, and the static site before release;
5. methodology and limitations remain first-class even when a surprising model
   result would be more promotable without them.

Bench participates in Crucible’s broader three-consumer proof alongside Roster
and Memory Engine. Bench proves public reproducibility; it does not need to
pretend one benchmark demonstrates every private product-evaluation workflow.

## What Bench is not

- Not a generic model leaderboard or a race to seat every new release.
- Not the home for project-specific private evals; those live with the projects
  they measure.
- Not a benchmark registry, model gateway, optimizer, or managed evaluation
  service.
- Not an alternate Crucible UI or control plane.
- Not a place to publish scraped, proprietary, ambiguously licensed, or
  accidentally disclosed material.
- Not evidence that a model or harness is broadly superior when the benchmark
  measured one narrow behavior.

## What excellent feels like

A skeptical reader can start from a headline, inspect the paired evidence,
re-run the exact benchmark, see what changed, identify what remains uncertain,
and reach the same bounded conclusion without trusting Misty Step. A benchmark
maintainer can add a family without hand-editing hidden infrastructure. A
surprising score makes the method more visible, not less. The public record gets
more useful over time without rewriting what earlier packets proved.

This direction was ratified with the operator on 2026-07-11. Change it when
published evidence or real external use disproves an assumption, not to make a
leaderboard easier to fill.
