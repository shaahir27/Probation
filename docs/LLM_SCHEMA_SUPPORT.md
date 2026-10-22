# Structured-output validation

WP1 implementation, 22 October 2026. Governing rules: `docs/CONTRACT.md` I-1,
I-3 and I-16, and `docs/PROMPTS.md`. No additional dependency is installed.

`backend/src/probation/llm/jobs.py` defines fourteen versioned jobs using strict,
closed Pydantic models. Reader, exam-edit and quarantined-extractor schema constants
are exported from these models. Registered jobs additionally run the model's semantic
validators on both fresh and cached output, including real dates and deadline/null
consistency. Writer, wording and synthesis job models do not establish that their
runtime call sites have been fully wired; that is WP3/WP7/WP8 work.

The generic diagnostic interface compiles a deliberately bounded JSON Schema subset
into strict Pydantic validators in `backend/src/probation/llm/schema.py`:

- Objects with declared properties/required keys and boolean additionalProperties.
  Production jobs forbid extras. Open diagnostic objects still accept JSON data only.
- Strict booleans, integers, finite numbers, strings and null; scalar enum/const;
  nullable type lists and bounded anyOf unions; local `$defs` references.
- Numeric bounds and positive multipleOf, string length/pattern constraints, array
  item schemas, lengths and boolean uniqueItems. JSON equality distinguishes true
  from 1 while treating 1 and 1.0 as the same number.
- Annotation-only title/description/default/schema/id/examples metadata. Missing
  optional fields are allowed; an explicitly supplied null must satisfy its schema.

Unsupported/invalid schemas fail before HTTP, rather than silently ignoring a safety
constraint. Unsupported cases include oneOf/allOf/not, format, conditional schemas,
pattern properties, schema-valued additionalProperties, external references,
constrained reference siblings, conflicting anyOf sibling intersections, empty
schemas, excessive depth and non-scalar enums. Cached validators are keyed by exact
schema JSON, with no ledger-style float rounding.

Cache payloads preserve numeric precision. Only final validated data may be cached.
Cache and exposure recording share a savepoint after HTTP; neither commits its caller's
transaction. A recording failure rolls back both writes. Transport retry accounting,
concurrent spend reservations and complete writer/reader integration remain WP3.

Regression evidence: `backend/tests/unit/test_wp1_validation.py`,
`test_wp1_context.py`, and the existing LLM/budget and pack tests. This describes
offline validation behavior, not live provider compatibility.
