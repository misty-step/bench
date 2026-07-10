# Misty Step Bench

A public benchmark laboratory. Small, sharp, reproducible benchmarks for
frontier and open language models — every score published with its full
method: exact prompts, model and provider configuration, confidence
intervals, per-task outputs, and cost.

**Site:** rendered from `docs/` (GitHub Pages).

## How it works

- **Definitions live here.** Each benchmark is a
  [Crucible](https://github.com/misty-step/crucible) `EvalSpec` under
  `benchmarks/`, with a clean-room task corpus authored for this repo —
  never proprietary or scraped text. Every task ships with a hand-written
  reference answer that passes its own grader and a near-miss that fails
  it (`benchmarks/<id>/references.json`).
- **Runs happen anywhere.** We run benchmarks locally through the Crucible
  engine with our own API keys. You can reproduce any result with yours:

  ```sh
  OPENROUTER_API_KEY=<your key> \
    crucible run benchmarks/constraint-gauntlet-v0.json --model <slug>
  ```

- **Results are packets.** A published result is a
  `crucible.bench_packet.v1` JSON under `docs/data/packets/` — the full
  run: config identity, score with a Wilson interval, per-task prompts,
  outputs, and verdicts. The site renders packets and nothing else.
- **Commentary is versioned.** Each benchmark carries a `notes.md` —
  analysis and speculation after each round, PR-reviewed like everything
  else.

## Honesty rules

Scores carry 95% Wilson intervals; comparisons are only claimed when they
clear a paired noise floor. We record the `response_model` the provider
actually served (providers silently swap backing models). A truncated
response (token-cap hit, empty output) is a measurement artifact, not a
model failure — token ceilings are set high and truncations are called out
in notes.

## License

MIT. Benchmark specs, fixtures, and reference answers are free to use;
attribution appreciated.
