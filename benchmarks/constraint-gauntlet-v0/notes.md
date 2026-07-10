# Notes — The Constraint Gauntlet, edition v0

## Thesis

Counting is not writing. A model can produce beautiful prose and still be
unable to hold "exactly 25 words" or "never the letter e" in its head while
producing it. Constrained generation is a clean window into instruction
fidelity because the grader is mechanical: the constraint either held or it
didn't. Content quality is deliberately unscored — the score says *obedience*,
the outputs say everything else.

## Design notes (2026-07-10, pre-run)

- 20 tasks across nine constraint families: exact word counts (15/25/40),
  lipograms (no *e*, no *a*), acrostics (EMBER, STONE), exact line counts,
  anaphora, alliteration, fixed openings/endings, capitals-only,
  single-sentence, and three combined-constraint tasks.
- Every task has a hand-written reference that passes its own regex and a
  near-miss that fails it — the grader was tested before any model was.
- Grader harshness was tuned on a live smoke run: trailing spaces before a
  newline no longer fail a line-ending constraint (a model that ends a line
  `?␣␣` obeyed the human meaning of "ends with a question mark").
- Token ceiling is 8000: on a 2000 ceiling a reasoning model burned its whole
  budget on hidden reasoning for the sunset lipogram and emitted nothing —
  that's a measurement artifact, not disobedience, so the ceiling is set
  where the score means what it says.
- 20 tasks resolve a minimum effect of ~0.30 at (α=0.05, power=0.8). Gaps
  smaller than that are inside this edition's noise floor by construction;
  v1 should grow the corpus toward ~30+ tasks per family conclusions.

## Round 1 (to be written after the first published runs)
