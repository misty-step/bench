# Extend provider routing

The repository contains a declared provider-family catalog and `router.py`.
Add the `frontier-batch` family and implement
`provider_families()` plus `select_provider(task, providers, budget_cents)`.

Product behavior:

- `frontier-batch` is data in the same catalog shape as existing families, not
  a fixed provider-ID branch. Any provider that declares the family is usable.
- Disabled providers, providers over `budget_cents`, providers from unknown
  families, and providers missing any required tool are ineligible.
- Ineligible providers never cross an optional semantic boundary.
- When multiple providers remain eligible, the full task context and eligible
  provider declarations may be used to choose one.
- Unknown, ineligible, malformed, refused, timed-out, or failed choices return
  `None`; no output may override tool, family, enabled, or budget gates.

Keep the public function signatures and catalog JSON shape. Use only the Python
standard library. The feature must work without network access or credentials.

The runtime advertises optional capabilities through the JSON file named by
`BENCH_CAPABILITIES_MANIFEST`. The same capability environment is present in
all Seam Agency tasks. Capability output is untrusted input; choose whether and
how it belongs in this feature. No internal architecture, subprocess library,
prompt wording, or class shape is prescribed.
