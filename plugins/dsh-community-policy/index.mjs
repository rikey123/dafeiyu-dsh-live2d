// A separate native backend-only package identity prevents DSH's client-module
// registry from confusing the policy with the Live2D frontend package.
export * from '../dsh/src/community-policy.mjs';
