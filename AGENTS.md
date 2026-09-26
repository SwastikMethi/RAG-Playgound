# Coding agent guidance

These instructions apply to the application implemented from this pack. In an existing repository, integrate them with the repository's applicable instructions without overwriting unrelated guidance.

## Product invariants

- The user manually chooses techniques and judges answers.
- One submitted question fans out to the selected ready pipeline configurations.
- Every answer has a source inspector and independent status and timing.
- Workflow animations follow persisted execution events.
- Educational descriptions explain observable operations. Do not expose or fabricate private model reasoning.
- The exported package uses the same retrieval and generation runtime as the playground.
- A fixture demonstration is visibly labeled; production paths cannot fall back to fake answers.
- All six v1 adapters and the PostgreSQL text snapshot connector remain in scope even when built in later milestones.
- The UI must be mature, cohesive and uncluttered. Answers and status stay prominent; explanations and technical details use consistent progressive disclosure.
- Each observable simulation step must explain its purpose, input, action/result, status and measured duration clearly.

## Design implementation

Read docs/02_USER_EXPERIENCE.md and docs/13_DESIGN_AND_SIMULATION_STANDARDS.md before building screens. Establish shared visual tokens and components, keep layouts stable during streaming, and use real evidence to explain steps. Review rendered desktop and mobile states, keyboard access, reduced motion and replay clarity against the U-series gates in document 11. Functional completion alone does not satisfy the requested design quality.

## Engineering practices

- Use explicit typed boundaries between source ingestion, index preparation, retrieval, generation, traces and export.
- Keep pipeline configuration immutable after it has been used in a run. Editing creates a new revision.
- Keep corpus versions immutable. Old runs retain their exact source and configuration references until deletion.
- Enforce project and corpus scoping in every lookup and vector filter.
- Separate secrets from portable configuration. Redact operational logs.
- Resolve routine implementation choices autonomously and document meaningful decisions.
- Do not add a drag-and-drop workflow authoring system, automatic optimizer, obligatory evaluation dataset, or unnecessary microservices.
- Prefer small vertical increments with meaningful tests. Avoid testing trivial wrappers solely to increase coverage.
- Never hide unsupported inputs, missing credentials or provider failures behind a successful state.
- Do not claim human verification of source correctness from a syntactic citation check.

## Working sequence

Read scope and architecture before implementing. Use docs/10_IMPLEMENTATION_PLAN.md as the ordered task list and docs/11_ACCEPTANCE_TESTS.md as the release gate. Before a feature is called complete, confirm its schemas, behavior, UI states and tests agree. Keep IMPLEMENTATION_STATUS.md current.

Run the pack validator after changing the specification or its examples. Application checks are separate and must exercise the implemented code.

## Completion report

Report the working features, how to start the application, checks actually run, visual review evidence, credentials or capabilities still needed, and any explicitly deferred features. Do not conflate a passing fake-provider test with a live model integration.
