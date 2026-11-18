// Composition policy only. Personality, memory, Bilibili and QQ stay independent
// upstream plugins; tools, agents and permissions still belong to native DSH.
export const name = 'dafeiyu-community-policy';
export const inject = ['tools'];
const soulMemory = new Set(['memory_read', 'memory_append', 'memory_rewrite', 'memory_search', 'memory_digest']);

export function rejection(execution, config = {}) {
  if (config.soulMemory !== true && soulMemory.has(execution.name))
    return 'Soul is personality-only in this composition. Use the separately installed fish-memory plugin for DSH memory.';
}

export function apply(ctx, config = {}) {
  // Avoid a second memory engine only. All ordinary tool permissions, including
  // Bilibili login/configuration/actions, remain entirely owned by DSH.
  ctx.tools.guard(execution => rejection(execution, config));
}
