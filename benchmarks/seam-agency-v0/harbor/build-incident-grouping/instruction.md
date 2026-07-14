# Add meaning-aware incident grouping

The repository contains an `incident_store.py` API. Implement
`IncidentStore(path).ingest(report_id, text)` and `groups()`.

Product behavior:

- Reports describing the same incident belong to one group even when their
  wording has little overlap; reports that share words but describe different
  incidents remain separate.
- Every new group receives a stable repository-generated ID. A semantic label
  or free-form value is never a persistence key.
- Replaying a known `report_id` is idempotent and returns its original group
  without changing storage.
- Unknown group choices, malformed output, refusals, timeouts, and execution
  failures return `None` without modifying the prior file.
- Successful updates atomically persist report membership and evidence text.

Keep the public class and method signatures. Use only the Python standard
library. The feature must work without network access or credentials.

The runtime advertises optional capabilities through the JSON file named by
`BENCH_CAPABILITIES_MANIFEST`. The same capability environment is present in
all Seam Agency tasks. Capability output is untrusted input; choose whether and
how it belongs in this feature. No internal architecture, subprocess library,
prompt wording, or class shape is prescribed.
