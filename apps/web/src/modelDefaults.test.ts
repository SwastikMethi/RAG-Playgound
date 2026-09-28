import { expect, it } from "vitest";
import type { Pipeline } from "./api";
import {
  applyModelDefaults,
  chooseModelDefaults,
  modelSelectionReady,
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
