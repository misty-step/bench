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

## Round 1 (2026-07-10) — four models, one signal

| model | score | 95% CI | failed |
|---|---|---|---|
| deepseek-v4-flash | 19/20 | [76.4, 99.1] | words-40 |
| glm-5.2 | 19/20 | [76.4, 99.1] | combo-words12-noe |
| minimax-m2 | 18/20 | [69.9, 97.2] | lipogram-sunset, acrostic-ember |
| kimi-k2 | 13/20 | [43.3, 81.9] | all three word counts, both lipograms, one-sentence, combo |

**The one defensible claim:** deepseek-v4-flash beats kimi-k2 by 30 points
(paired McNemar, b=6 c=0, p=0.031 — clears the noise floor; this corpus
resolves effects ≥ ~29pp, and this one is exactly that size). Every other
pairwise gap is inside the noise floor at n=20; we say nothing about them.

**Where kimi-k2 loses:** counting and letter bans. It missed all three exact
word counts, and both lipograms — its "no letter e" sunset began "A warm sky
turns gold and pink as daylight fades," which is lovely and contains four e's.
The acrostics, line counts, and anaphora all held; the failures cluster in
constraints that require tracking a global property of the text while
writing it, not in following structure.

**Provider drift, recorded:** the deepseek slug was served by
`deepseek-v4-flash-20260423` and glm by `glm-5.2-20260616` — dated backing
models. If a future run of the same slug scores differently, check the
served model before blaming the benchmark.

**Speculation (unproven):** word-count failures at 15/25/40 words all landed
*short* — models seem to compress toward "enough" rather than count. A v1
family varying target length would test whether error grows with distance
from typical completion length.

**For v1:** grow to ~30+ tasks (resolve ~20pp effects), add a second
lipogram letter, and consider epochs (k=3) once the runner supports them —
one of these scores moving ±1 task between runs would change nothing we
claimed, but pass@k would say so mechanically.
