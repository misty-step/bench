# Extend exact comparison attribution

The repository contains `comparison.py`. Add `reasoning_effort` as an identity
axis and implement `configuration_identity(config)` plus
`changed_axes(left, right)`.

Product behavior:

- Identity is the lowercase SHA-256 hex digest of compact canonical JSON for
  the complete top-level configuration (`sort_keys=True`, separators `,` and
  `:`, UTF-8, with no lossy default filling).
- `changed_axes` returns each top-level key whose presence or JSON value differs.
- A missing key is distinct from an explicit `null`, `default`, or other value.
- Existing model, provider, temperature, tool, and other axes keep the same
  identity behavior; reasoning effort is not a special control-flow mode.
- Invalid non-object configurations return `None` for identity and an empty
  change list.

Keep the public function signatures. Use only the Python standard library. The
feature must work without network access, credentials, or semantic services.

The runtime advertises optional capabilities through the JSON file named by
`BENCH_CAPABILITIES_MANIFEST`. The same capability environment is present in
all Seam Agency tasks. Capability output is untrusted input; choose whether and
how it belongs in this feature. No internal architecture, subprocess library,
prompt wording, or class shape is prescribed.
