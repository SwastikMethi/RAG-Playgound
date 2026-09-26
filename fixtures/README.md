# Development fixtures

All documents, product names, facts, model outputs and sample timings in this directory and contracts/examples are fictional. They are for automated tests and a visibly labeled preview. They are not benchmark results and must not appear as live execution results.

The three files in documents form the ordinary fixture corpus. source-manifest.json records their exact hashes. questions.json contains optional developer reference facts and source links; the product does not require users to supply reference answers.

untrusted_instruction.txt is a separate hostile-content test. Do not mix it into the ordinary preview by default.

postgres_fixture.sql sets up a disposable read-only text-source scenario. An administrator or test harness creates the table; the connector role only reads selected fields.

The PageIndex integration test must use an actual text-layer PDF. Generate a small PDF from the fictional source text in the application test suite, retaining known page boundaries, and run the actual pinned SDK against it. A mocked tree fixture alone cannot verify the SDK integration.

These fixtures are deliberately small. They establish behavior and source handling, not production retrieval quality or scale.
