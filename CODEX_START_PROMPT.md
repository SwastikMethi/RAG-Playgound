# Prompt for Codex

Implement the RAG Playground described in this repository's implementation pack.

Read README.md, AGENTS.md, docs/01_PRODUCT_REQUIREMENTS.md, docs/02_USER_EXPERIENCE.md, docs/03_ARCHITECTURE.md, docs/13_DESIGN_AND_SIMULATION_STANDARDS.md, docs/10_IMPLEMENTATION_PLAN.md, and docs/11_ACCEPTANCE_TESTS.md first. Then read the remaining relevant specifications and the machine-readable contracts before implementing their features.

The product is an interactive comparison and learning playground. A user uploads documents or imports an approved PostgreSQL text snapshot, selects techniques, asks one question, sees independently streamed answers and timings, inspects the actual evidence and animated execution steps, and exports working code for a preferred configuration. Keep the user in control of judging quality.

Follow these instructions:

1. Inspect the existing repository and applicable instructions. If this is an empty project, use the proposed stack and layout in document 03. Preserve unrelated work.
2. Write a concise implementation plan aligned to milestones M0 through M8. Begin implementation immediately after the plan; do not stop at scaffolding.
3. Build a working vertical slice early, then complete the required v1 features. Do not treat the first slice as the complete product.
4. Use actual retrieval adapters. Never silently replace BM25 with generic SQL full-text search, PageIndex with a hand-written vector retriever, or real execution traces with fabricated animations.
5. Derive API types and validation from the supplied contracts. Use the same pipeline runtime for the web runner and exported packages.
6. Enforce one answer model, prompt revision, output cap, and context budget across lanes within each comparison. Each comparison is an observed run; do not claim that it establishes a universally best technique.
7. Keep all query timing independent from index preparation. Store server timings and replayable events. Support failed lanes, cancellation, reconnect and honest unsupported-capability states.
8. Use the synthetic fixtures only in tests or an explicitly labeled preview. Real product mode must use the user's data and configured provider.
9. Select compatible stable dependencies, record exact versions in lockfiles, and validate PageIndex's installed public APIs before writing its adapter.
10. Add meaningful tests for the acceptance scenarios, focusing on real retrieval behavior, event order, source attribution, cancellation, data scoping, export parity and failures.
11. After each milestone, update IMPLEMENTATION_STATUS.md with completed tasks, verification evidence and limitations. Continue through the plan unless access, a required secret, or a genuine unresolved conflict blocks progress.
12. When external credentials are unavailable, complete local implementation and deterministic tests. State which live provider checks remain unverified and provide the exact setup steps to run them. Do not label an unperformed live check as passed.
13. Do not deploy publicly, create paid infrastructure, publish a repository, or send data to a new provider without the user's applicable authorization. Local implementation and tests are authorized by this request.
14. Treat design quality as required functionality. Build a mature, deliberate interface with shared typography, spacing, components and restrained color. Keep the overview focused on answers and status; reveal explanations and technical detail on demand. Avoid generic dashboard decoration and clutter.
15. Make every observable simulation step clear: concise name, purpose, input, action/result, state and measured duration. Show true parallel branches, preserve evidence identity, and provide readable step-level replay without changing execution timings or fabricating model reasoning.
16. Inspect the rendered application at the viewports and states specified in document 13. Record screenshots and replay review evidence against the U-series acceptance checks. Do not claim visual quality passed solely from unit tests or schema validation.

Deliver the implemented application, setup instructions, lockfiles, migrations, tests, working demo fixture mode, and a clear list of verified and unverified behaviors. The full release gate is in document 11.
