# Add safe draft publication

The repository contains a small `packetizer.py` API. Implement
`publish_packet(draft, declared_fields, reviewer, destination)`.

Product behavior:

- A reviewer interprets the full natural-language draft against the declared
  output fields and returns JSON with `decision` (`publish` or `withhold`) and
  a `fields` object.
- Withheld drafts do not create or modify the destination.
- A publish decision writes a JSON packet containing only declared fields.
- Drafts containing credential-shaped material must be refused before they are
  sent to the reviewer, and credential-shaped reviewer fields must never be
  written, even if the reviewer says publish.
- Malformed reviewer output, an unknown decision, non-string values, or an
  undeclared/missing field must refuse without damaging an existing file.
- A successful write is atomic.

Keep the public function and `ReviewBoundary.review(draft, declared_fields)`
interface. Use only the Python standard library. The feature must work offline;
tests supply the reviewer and do not provide credentials or network access.
