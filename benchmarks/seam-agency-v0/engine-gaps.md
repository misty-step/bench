# Live engine and publication gaps

Observed from the public CLIs and repository contracts on 2026-07-13:

- `crucible 0.0.0` accepts `crucible.eval_spec.v1`, validates `harbor_task`,
  and invokes Harbor once per task.
- `harbor 0.13.1` exposes generic `oracle`, Codex, Claude Code, Goose, OpenCode,
  Pi, and other agents; Docker 29.2.1 is available on the qualification host.
- The checked-in spec deliberately uses `oracle`. An oracle pass proves that
  the reference solution and verifier integrate; it is not evidence that a
  coding agent solved the task.

The following gaps prevent a trusted cross-harness or public benchmark run:

1. **No narrow versioned external-runner/artifact waist.** Current Crucible
   runner policy is coupled to closed runner/corpus variants. A trusted
   external harness needs a language-neutral envelope for adapter identity,
   capabilities, inputs, outputs, evidence, resources, authority, and
   structured errors. Tracked by `crucible-runner-artifact-protocol`.
2. **Harness treatments are not fully receipted.** Harbor can launch named
   agents, but Crucible's shared `harbor_task` config does not capture a
   complete versioned adapter configuration, actual system prompt, applied
   reasoning effort, effective tools/skills/MCP, imported transcript, retries,
   or primitive topology. A direct model call or a name in identity metadata
   must not be relabeled as a Pi/Codex/Goose/OpenCode comparison.
3. **Reasoning/articulation/primitive attribution is incomplete.** Reasoning
   effort is not a consistently applied and identity-hashed axis; prompt deltas
   collapse into generic config differences; frozen context, skill, memory,
   critique, and multi-agent topology do not have first-class one-axis receipts.
4. **Grouped inference is absent.** Crucible can compute task-level Wilson and
   paired McNemar outputs, but Seam Agency variants and repeated attempts are
   clustered by source task. No cluster-aware interval or grouped-analysis
   export exists, so population claims would overstate independence.
5. **Graduated trust is not structural.** Run/publication artifacts do not yet
   carry a scoped trust state, machine-readable missing-evidence reasons, and
   an interface-invariant ceiling on allowed claims. Author-declared canaries
   alone do not qualify model judgment. Tracked by
   `crucible-graduated-trust-contract`.
6. **Safe publication is not fail-closed.** Current packet publication lacks
   field-by-field clean-room/review allowlisting, a deny-by-default sensitive
   content receipt, and atomic/no-clobber public output. Tracked by
   `crucible-safe-publication-contract`.
7. **Bench intake is not yet independent.** Bench does not yet have the
   repository gate that validates packet schema, joins, runtime identity,
   disclosure, integrity, duplicates, and manifest drift before tracked
   publication. Tracked by `bench-packet-acceptance-gate`.
8. **Private decision evidence is absent.** The seven public development tasks
   are now materialized with two behaviorally distinct references and three
   mutation-qualified wrong-seam implementations each. No independently
   sourced private calibration/test corpus, blinded expert labels, or frozen
   disclosure review exists, so the package still cannot support held-out
   capability or population claims.

## Historical installed-binary baseline — former gaps 9 and 10

The installed `crucible 0.0.0` used during the initial two-task qualification
produced two valid baseline receipts that are not current Crucible source gaps:

- A run with `--out /tmp/bench-seam-agency-v0-run` exited successfully but
  recorded 0/2 with `RewardFileNotFoundError` because Colima could not mount the
  verifier receipt path outside `$HOME`. The identical run under
  `$HOME/.cache/bench-seam-agency-v0-run` produced 2/2.
- `crucible import harbor` rejected Harbor 0.13.1's current `task.toml` shape
  even though a hand-authored generic spec validated and ran both tasks.

Current Crucible source supports the current Harbor task format, portable
task-path rebasing, and preflight refusal when either the Harbor task or run
output path is outside the Colima-mounted `$HOME` tree. Those durable source
contracts supersede the installed-binary failures above without erasing them
as historical qualification receipts.

Therefore this package claims only gold and Harbor-oracle reference
qualification. The clean source revision
`17b21930c0514fb039f1eaf6bbd1f484719703de` produced 7/7 through Crucible's
generic `harbor_task` path; both references per task pass the repository gate,
each pair has an executable behavior distinction, and the 21 named wrong-seam
mutants fail under deterministic verifiers. It does not claim a real agent
run, real-model semantic quality, critique completeness or architectural
soundness, cross-harness comparability, held-out generalization, or publication
safety.
