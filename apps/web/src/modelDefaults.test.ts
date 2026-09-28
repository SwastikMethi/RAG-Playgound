import { expect, it } from "vitest";
import type { Pipeline } from "./api";
import {
  applyModelDefaults,
  chooseModelDefaults,
  modelSelectionReady,
  pipelineUsesModels,
  type ModelOptions,
  type PublicProfile,
} from "./modelDefaults";

const generation: PublicProfile = {
  id: "answer-new",
  label: "New answer",
  models: ["gpt-new"],
  operations: ["generation", "tree_selection", "tree_indexing"],
  available: true,
  unavailable_reason: null,
  max_input_tokens: 100000,
  max_output_tokens: 256,
  dimensions: null,
};
const embedding: PublicProfile = {
  id: "embedding-new",
  label: "New embedding",
  models: ["embed-new"],
  operations: ["embedding"],
  available: true,
  unavailable_reason: null,
  max_input_tokens: 8191,
  max_output_tokens: null,
  dimensions: 3072,
};

it("applies selected models only to a cloned new pipeline configuration", () => {
  const original = {
    generation: { profile_id: "old", model: "old", max_output_tokens: 512 },
    embedding: { profile_id: "old-embed", model: "old-embed", dimensions: 1536 },
    tree: {
      index_profile_id: "old",
      index_model: "old",
      selection_profile_id: "old",
      selection_model: "old",
    },
  } as Pipeline;

  const changed = applyModelDefaults(original, { generation, embedding });

  expect(changed).not.toBe(original);
  expect(changed.generation).toMatchObject({
    profile_id: "answer-new",
    model: "gpt-new",
    max_output_tokens: 256,
  });
  expect(changed.embedding).toMatchObject({
    profile_id: "embedding-new",
    model: "embed-new",
    dimensions: 3072,
  });
  expect(changed.tree).toMatchObject({
    index_profile_id: "answer-new",
    index_model: "gpt-new",
    selection_profile_id: "answer-new",
    selection_model: "gpt-new",
  });
  expect(original.generation.profile_id).toBe("old");
});

it("resets answer controls only when the selected answer model changes", () => {
  const original = {
    generation: {
      profile_id: "old",
      model: "gpt-old",
      max_output_tokens: 512,
      seed: 42,
      temperature: 0.8,
    },
    embedding: null,
    tree: null,
  } as Pipeline;

  expect(applyModelDefaults(original, { generation })).toMatchObject({
    generation: {
      profile_id: "answer-new",
      model: "gpt-new",
      max_output_tokens: 256,
      seed: null,
      temperature: 0,
    },
  });
  expect(
    applyModelDefaults(
      { ...original, generation: { ...original.generation, model: "gpt-new" } },
      { generation },
    ).generation,
  ).toMatchObject({ seed: 42, temperature: 0.8 });
});

it("requires revisions for actual model or dimension changes, not historical profile ids", () => {
  const matching = {
    generation: { profile_id: "historical-answer", model: "gpt-new" },
    embedding: {
      profile_id: "historical-embedding",
      model: "embed-new",
      dimensions: 3072,
    },
    tree: {
      index_profile_id: "historical-answer",
      index_model: "gpt-new",
      selection_profile_id: "historical-answer",
      selection_model: "gpt-new",
    },
  } as Pipeline;

  expect(pipelineUsesModels(matching, { generation, embedding })).toBe(true);
  expect(
    pipelineUsesModels(
      { ...matching, embedding: { ...matching.embedding!, dimensions: 1536 } },
      { generation, embedding },
    ),
  ).toBe(false);
  expect(
    pipelineUsesModels(
      { ...matching, generation: { ...matching.generation, model: "gpt-old" } },
      { generation, embedding },
    ),
  ).toBe(false);
});

it("restores browser defaults only when both profiles are still offered", () => {
  const options: ModelOptions = { generation: [generation], embedding: [embedding] };
  expect(chooseModelDefaults(options, { generation: "answer-new", embedding: "embedding-new" }))
    .toEqual({ generation, embedding });
  expect(chooseModelDefaults(options, { generation: "missing", embedding: "embedding-new" }))
    .toEqual({ generation, embedding });
});

it("requires a compatible answer and embedding model before creating pipelines", () => {
  expect(modelSelectionReady({ generation, embedding })).toBe(true);
  expect(modelSelectionReady({ generation })).toBe(false);
  expect(modelSelectionReady({ embedding })).toBe(false);
  expect(modelSelectionReady({})).toBe(false);
});
