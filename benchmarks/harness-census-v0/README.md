# Harness Census v0

This package qualifies three history-free task images for the model-harness census.

Run the repository-owned qualification command:

```sh
python3 scripts/qualify_harness_census.py
```

The command reads only the pinned local repositories. It exports each pre-fix
SHA without Git history, applies the checked-in reference or mutant patch, and
runs a deterministic grader outside the worker image. It writes one sanitized
JSON qualification receipt per task under `benchmarks/harness-census-v0/receipts/`.

The command also regenerates the deterministic smoke files:

- `smoke/availability.json`;
- `smoke/stage-manifest.json`;
- `smoke/harness-census-v0.json`.

The smoke uses the confirmed Pi route `openrouter/deepseek/deepseek-v4-flash-0731`
at native effort `high`. Gemini-lite rows remain explicit blocked-route
sentinels. No paid model is called by qualification.

Task source bytes, Git history, references, and hidden graders are not checked
in. Harbor templates describe the runtime source export and permitted edits.
