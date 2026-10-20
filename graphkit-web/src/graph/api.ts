import type { AskResult, BenchResponse, CatalogResponse, Changes, DraftResponse, GkEdge, GkNode, GraphResponse, SemanticItem, SemanticState, State, TerraformFiles } from './types'

import { api as sharedApi, req, ApiError } from '../shared/api'

const qs = (params: Record<string, string | number | undefined>) =>
  '?' + new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][],
  ).toString()

export const api = {
  capabilities: sharedApi.capabilities,
  listGraphs: () => req<string[]>('/api/graphs'),
  createDemo: (path: string) => req<{ path: string }>('/api/demo', { method: 'POST', body: JSON.stringify({ path }) }),

  scan: (body: {
    name: string; backend: string; location: Record<string, string>; sample_rows: number
    descriptions_file?: string | null; check_values: boolean; use_llm: boolean
  }) => req<{ nodes: number; edges: number; notes: string[] }>('/api/scan', { method: 'POST', body: JSON.stringify(body) }),

  watch: (name: string, sample_rows: number, check_values: boolean) =>
    req<{ new: string[] }>('/api/watch', { method: 'POST', body: JSON.stringify({ name, sample_rows, check_values }) }),

  state: (name: string) => req<State>(`/api/state${qs({ name })}`),

  draft: (name: string) => req<DraftResponse>(`/api/draft${qs({ name })}`),
  saveDraft: (name: string, nodes: GkNode[], edges: GkEdge[]) =>
    req<{ problems: string[] }>('/api/draft', { method: 'PUT', body: JSON.stringify({ name, nodes, edges }) }),

  graph: (name: string, view: 'schema' | 'data', per: number) =>
    req<GraphResponse>(`/api/graph${qs({ name, view, per })}`),

  changes: (name: string) => req<Changes>(`/api/changes${qs({ name })}`),
  ddl: (name: string) => req<{ ddl: string | null; problems: string[]; preview: boolean }>(`/api/ddl${qs({ name })}`),

  confirm: (name: string) => req<{ path: string }>('/api/confirm', { method: 'POST', body: JSON.stringify({ name }) }),

  terraform: (name: string) => req<TerraformFiles>(`/api/terraform${qs({ name })}`),
  terraformPlan: (name: string) => req<{ code: number; log: string }>('/api/terraform/plan', { method: 'POST', body: JSON.stringify({ name }) }),
  terraformApply: (name: string) => req<{ code: number; log: string }>('/api/terraform/apply', { method: 'POST', body: JSON.stringify({ name }) }),

  runBench: (body: { name: string; hops: number; limit: number; llm_n: number; repeat: number }) =>
    req<BenchResponse>('/api/bench', { method: 'POST', body: JSON.stringify(body) }),
  bench: (name: string) => req<BenchResponse>(`/api/bench${qs({ name })}`),

  models: sharedApi.models,

  semanticState: (name: string) => req<SemanticState>(`/api/semantic/state${qs({ name })}`),
  semanticCatalog: (name: string, which: 'draft' | 'approved') =>
    req<CatalogResponse>(`/api/semantic/catalog${qs({ name, which })}`),
  semanticPropose: (name: string, useLlm: boolean, model?: string) =>
    req<{ revision: string; items: SemanticItem[] }>('/api/semantic/propose', {
      method: 'POST', body: JSON.stringify({ name, use_llm: useLlm, model }),
    }),
  saveSemanticDraft: (name: string, items: SemanticItem[]) =>
    req<{ ok: boolean }>('/api/semantic/draft', { method: 'PUT', body: JSON.stringify({ name, items }) }),
  semanticApprove: (name: string) =>
    req<{ revision: string; approved: boolean; items: number }>('/api/semantic/approve', {
      method: 'POST', body: JSON.stringify({ name }),
    }),
  semanticEmbed: (name: string, embeddingModel: string) =>
    req<{ model: string; count: number; dimensions: number }>('/api/semantic/embed', {
      method: 'POST', body: JSON.stringify({ name, embedding_model: embeddingModel }),
    }),
  semanticPublish: (name: string) =>
    req<{ rows: number }>('/api/semantic/publish', { method: 'POST', body: JSON.stringify({ name }) }),
  semanticAsk: (body: { name: string; question: string; embedding_model: string; generation_model: string; mode: string; use_embeddings?: boolean }) =>
    req<AskResult>('/api/semantic/ask', { method: 'POST', body: JSON.stringify(body) }),
}

export { ApiError }
