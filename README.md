# Misty Step Bench

A public benchmark laboratory. Small, sharp, reproducible benchmarks for
frontier and open language models — every score published with its full
method: exact prompts, model and provider configuration, confidence
intervals, per-task outputs, and cost.

For the product boundary, publication standard, and relationship with Crucible,
read [`VISION.md`](VISION.md). Bench is a strict consumer of Crucible’s public
contracts; it has no privileged engine path.

**Site:** rendered from `docs/` (GitHub Pages). Self-contained editorial
design (`docs/bench.css`), light/dark following the system.

## How it works

- **Definitions live here.** Each benchmark has a package under `benchmarks/`
  with a public [Crucible](https://github.com/misty-step/crucible) contract and
  a clean-room corpus authored for this repo — never proprietary or scraped
  text. Prompt benchmarks carry reference/near-miss answer sets; agentic task
  packages carry reference implementations and wrong-seam mutants.
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

## Benchmark families

- **Constraint Gauntlet** is the published deterministic instruction-following
  family rendered by the site.
- **[Seam Agency v0](benchmarks/seam-agency-v0/README.md)** is a Bench-owned
  qualification package for agent placement of semantic judgment, declarative
  structure, and deterministic enforcement. Its matched Build pair uses only
  public Harbor/Crucible contracts. It has gold and mutation proof, but no
  agent ranking or public result claim.

Run the repository-owned qualification gate with:

```sh
./scripts/check.sh
```

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
