# Repair meaning-aware memory extraction

The repository's `memory.py` currently mistakes keywords for memory evidence.
Repair `extract_memory(text)`.

Product behavior:

- Return `None` when the text does not support a durable user fact or when
  semantic output is malformed, refused, timed out, or failed.
- Meaning-equivalent paraphrases must be eligible even without trigger words;
  lexical mentions of remembering, preferences, or personal facts do not by
  themselves create a memory.
- A returned object contains non-empty string `fact` and `evidence` fields.
  `evidence` must be an exact non-empty substring of the source text.
- The extractor must not invent a fact when the semantic decision is `none`,
  and untrusted extra fields or unsupported evidence are refused.
- An implementation may also return the exact integer `source_offset` where
  the evidence begins; callers must not require it.

Keep the public function signature. Use only the Python standard library. The
feature must work without network access or credentials.

The runtime advertises optional capabilities through the JSON file named by
`BENCH_CAPABILITIES_MANIFEST`. The same capability environment is present in
all Seam Agency tasks. Capability output is untrusted input; choose whether and
how it belongs in this feature. No internal architecture, subprocess library,
prompt wording, or class shape is prescribed.
