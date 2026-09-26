# Pack validation

Run from the extracted pack root:

    python3 -m pip install -r tools/requirements.txt
    python3 tools/validate_pack.py

The validator checks internal Markdown links, schema references, six configurations, OpenAPI route structure, synthetic source hashes, event ordering, source offsets, citation membership, elapsed-time definitions and the export example.

When installed, jsonschema and openapi-spec-validator add standards-based validation. If they are absent, the script explicitly reports that state and uses a bounded built-in checker for the exact schema keywords used in this pack. That fallback is not a general-purpose JSON Schema or OpenAPI validator.

VALIDATION_REPORT.json records the checks actually performed when the pack was prepared. It does not claim that any application, provider, retrieval implementation or exported app has been run.

Application tests described in docs/11_ACCEPTANCE_TESTS.md must be implemented separately by Codex.
