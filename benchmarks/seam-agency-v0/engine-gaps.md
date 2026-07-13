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
8. **Qualification corpus is incomplete.** Only the matched Build pair is
   materialized, and each has one reference implementation rather than the two
   structurally different acceptable references required for headline use.
9. **The jobs-root mount constraint is not preflighted.** Running the generic
   spec with `--out /tmp/bench-seam-agency-v0-run` on the Colima host completed
   with process exit 0 but recorded 0/2 and `RewardFileNotFoundError` for both
   tasks because the verifier receipt path was outside the home directory
   Colima mounts. Re-running the identical spec under
   `$HOME/.cache/bench-seam-agency-v0-run` produced 2/2. Crucible currently
   preflights task directories under `$HOME`, but not the jobs/output root, and
   treats the resulting infrastructure errors as a zero score rather than a
   refused run.
10. **Installed import/preflight surfaces drift from executable task support.**
    The installed `crucible import harbor` rejected both Harbor 0.13.1 tasks
    because their current `task.toml` shape has top-level `version` plus
    `[verifier]`, `[agent]`, and `[environment]` instead of legacy `[task]`, even
    though `crucible validate` accepted the hand-authored generic spec and
    `crucible run` executed both directories successfully. Harbor's own
    `harbor tasks check` command reports that it has been removed, while its
    replacement `harbor check` requires `ANTHROPIC_API_KEY`; there is no
    credential-free deterministic task-definition preflight in that surface.

## Reconciliation — 2026-07-13

Items 9 and 10 remain valid receipts for the installed `crucible 0.0.0` used
by this qualification run; they are no longer current Crucible source gaps.
Concurrent, unpushed Crucible commits `baa92e2` (current Harbor import plus
portable task-path rebasing, with green oracle/nop proof) and `10044b5`
(outside-`$HOME` Harbor output preflight) close those two failures in source.
Readers should distinguish the reproducible installed-binary baseline above
from this newer local source truth until those commits are published.

Therefore this package claims only local gold qualification: its references
pass and its named wrong-seam mutants fail under deterministic verifiers. It
does not claim a real agent run, cross-harness comparability, calibrated model
judgment, held-out generalization, or publication safety.
