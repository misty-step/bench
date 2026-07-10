# Notes — The Constraint Gauntlet, edition v1

## What changed from v0

Fourteen new tasks on top of v0's twenty: longer exact word counts (10 and
60), two more banned letters (no *t*, no *o*), an eight-line CRUCIBLE
acrostic, a per-line word grid (4 lines × exactly 5 words), an exact
sentence count, and three harder combinations — the nastiest being a FOG
acrostic that must also contain no letter *e*. Same discipline throughout:
every task's hand-written reference passes its own grader; every near-miss
fails it. At n=34 this edition resolves effects of ~25 points; the noise
floor tightened accordingly.

## Round 1 (2026-07-10) — eleven models

| model | score | 95% CI |
|---|---|---|
| qwen3.7-max | 34/34 · 100% | [89.8, 100.0] |
| claude-sonnet-5 | 31/34 · 91.2% | [77.0, 97.0] |
| deepseek-v4-pro | 31/34 · 91.2% | [77.0, 97.0] |
| grok-4.5 | 30/34 · 88.2% | [73.4, 95.3] |
| glm-5.2 | 29/34 · 85.3% | [69.9, 93.6] |
| gpt-5.4 | 29/34 · 85.3% | [69.9, 93.6] |
| kimi-k2.6 | 29/34 · 85.3% | [69.9, 93.6] |
| gemini-3.5-flash | 29/34 · 85.3% | [69.9, 93.6] |
| minimax-m3 | 28/34 · 82.4% | [66.5, 91.7] |
| deepseek-v4-flash | 27/34 · 79.4% | [63.2, 89.7] |
| minimax-m2 | 25/34 · 73.5% | [56.9, 85.4] |
| kimi-k2 | 23/34 · 67.6% | [50.8, 80.9] |

kimi-k2.6's seat was initially empty: its long reasoning traces exceeded
the runner's old 60-second HTTP timeout eight straight times. We raised the
default to 15 minutes (how long a model will go is data, not infrastructure
residue — packets now carry per-task and total `duration_ms`), and it
completed: **29/34 (85.3%, CI [69.9, 93.6])** — up 6 tasks on kimi-k2.
Tempting headline, but the paired comparison says **inside the noise floor**
(b=9 c=3, p=0.146; k2 beat k2.6 on three tasks): at n=34 we cannot claim
the generational jump. v2's larger corpus can.

## Defensible claims (paired McNemar, noise-floor checked)

- **qwen3.7-max beats kimi-k2** by 32 points (b=11 c=0, p=0.001) — signal.
- **qwen3.7-max beats minimax-m2** by 26 points (b=9 c=0, p=0.004) — signal.
- **qwen3.7-max beats deepseek-v4-flash** by 21 points (b=7 c=0, p=0.016) — signal.
- qwen3.7-max vs claude-sonnet-5 (Δ8.8) and deepseek-pro vs deepseek-flash
  (Δ11.8) are **inside the noise floor** at n=34 — we claim nothing there.

A perfect score deserves suspicion, so we read qwen's outputs: the
60-word eulogy is exactly 60 words, the FOG acrostic contains no letter
*e*, the no-*o* night sky holds. It earned it.

## Where models fail

Failures cluster in constraints that require tracking a **global running
property** while writing — word counts, banned letters, and the
combinations — not in structure (acrostics, line counts, anaphora were
nearly universal passes). The single most discriminating families remain
`word_count` and `lipogram`. Notably, grok-4.5's failures were all three
alliteration tasks plus the all-caps combo: it obeys counts and letter
bans but slips on per-word initial constraints — a different failure
axis than kimi's.

## Method notes

- Reasoning effort is currently the provider default and is not yet a
  declared axis; until it is, treat scores as "default settings" scores
  (tracked: crucible-reasoning-effort-axis).
- Provider drift recorded per packet (`response_model`); deepseek and glm
  slugs are served by dated backing models.
- v0's scores are not comparable to v1's (different corpus, different
  scoring identity); the lineage lives on the v0 page.

## For v2

Vary word-count targets systematically (does error grow with distance
from typical completion length? v1's failures again skew short); add a
length-controlled lipogram family; epochs (k=3) once the runner supports
them; and a kimi-k2.6 seat once the client timeout is configurable.
