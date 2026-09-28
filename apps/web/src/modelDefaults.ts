import type { components } from "./generated/api";
import type { Pipeline } from "./api";

export type PublicProfile = components["schemas"]["Profile"];
export type ModelOptions = {
  generation: PublicProfile[];
  embedding: PublicProfile[];
};
export type ModelSelection = {
  generation?: PublicProfile;
  embedding?: PublicProfile;
};

export function modelSelectionReady(selection: ModelSelection) {
  return Boolean(selection.generation && selection.embedding);
}

export function chooseModelDefaults(
  options: ModelOptions,
  saved: { generation?: string; embedding?: string } | null,
): ModelSelection {
  return {
    generation: options.generation.find((profile) => profile.id === saved?.generation) || options.generation[0],
    embedding: options.embedding.find((profile) => profile.id === saved?.embedding) || options.embedding[0],
  };
}

export function applyModelDefaults(config: Pipeline, selection: ModelSelection): Pipeline {
  const next = structuredClone(config);
  if (selection.generation) {
    const profile = selection.generation;
    next.generation.profile_id = profile.id;
    next.generation.model = profile.models[0];
    if (profile.max_output_tokens != null) {
      next.generation.max_output_tokens = Math.min(
        next.generation.max_output_tokens,
        profile.max_output_tokens,
      );
    }
    if (next.tree) {
      next.tree.index_profile_id = profile.id;
      next.tree.index_model = profile.models[0];
      next.tree.selection_profile_id = profile.id;
      next.tree.selection_model = profile.models[0];
    }
  }
  if (selection.embedding && next.embedding) {
    const profile = selection.embedding;
    next.embedding.profile_id = profile.id;
    next.embedding.model = profile.models[0];
    if (profile.dimensions != null) next.embedding.dimensions = profile.dimensions;
  }
  return next;
}
