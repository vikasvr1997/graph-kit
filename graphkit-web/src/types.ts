export type Status = 'proposed' | 'new' | 'approved'

export interface GkNode {
  label: string
  table: string
  key: string[]
  properties: string[] | null
  description: string
  status: Status
}

export interface GkEdge {
  label: string
  table: string
  key: string[]
  source: string
  source_key: string[]
  dest: string
  dest_key: string[]
  bidirectional: boolean
  reverse_label: string
  properties: string[] | null
  confidence: number
  reason: string
  status: Status
}

export type Backend = 'bigquery' | 'spanner' | 'sqlite'

export interface Location {
  [key: string]: string | undefined
}

export interface State {
  has_draft: boolean
  has_approved: boolean
  nodes?: number
  edges?: number
  waiting?: number
  problems?: string[]
  notes?: string[]
  backend?: Backend
  location?: Location
}

export interface DraftResponse {
  nodes: GkNode[]
  edges: GkEdge[]
  table_names: string[]
  label_opts: string[]
  backend: Backend
  location: Location
}

export interface GraphVizNode {
  id: string
  label: string
  color: string
  dashed?: boolean
  status?: string
  group?: string
  info: Record<string, unknown>
}

export interface GraphVizEdge {
  id?: string
  from: string
  to: string
  label?: string
  dashed?: boolean
  status?: string
  arrows2?: boolean
}

export interface GraphResponse {
  nodes: GraphVizNode[]
  edges: GraphVizEdge[]
  colors: Record<string, string>
}

export interface Changes {
  added: string[]
  removed: string[]
  changed: string[]
}

export interface TerraformFiles {
  available: boolean
  files?: Record<string, string>
  terraform_installed?: boolean
}

export interface BenchResultRow {
  question: string
  match: boolean | null
  gql_ms: number | null
  sql_ms: number | null
  faster: string | null
  rows: number | null
  gql_bytes: number | null
  error: string | null
}

export interface BenchSummary {
  queries: number
  compared: number
  matched: number
  gql_median_ms: number | null
  sql_median_ms: number | null
  errors: number
}

export interface BenchResponse {
  available: boolean
  summary?: BenchSummary
  results?: BenchResultRow[]
}

export interface ModelInfo {
  id: string
  label: string
  validated: boolean
  notes: string
  dimensions?: string
}

export interface ModelsResponse {
  embedding_models: ModelInfo[]
  generation_models: ModelInfo[]
  defaults: { embedding_model: string; generation_model: string }
  note: string
}

export interface SemanticItem {
  id: string
  kind: 'table' | 'column' | 'node' | 'edge'
  table: string
  name: string
  description: string
  aliases: string[]
}

export interface CatalogResponse {
  exists: boolean
  revision?: string
  approved?: boolean
  items?: SemanticItem[]
}

export interface SemanticState {
  has_draft: boolean
  has_approved: boolean
  embeddings: { model: string; count: number; dimensions: number } | null
}

export interface AskResult {
  status: 'success' | 'abstained'
  reason?: string
  answer?: string
  query?: string
  mode?: string
  rows?: Record<string, unknown>[]
  truncated?: boolean
  references?: string[]
  timings_ms?: Record<string, number>
}

export interface ChatSession {
  id: string
  title: string
  workspace: string
  generation_model: string
  embedding_model: string
}

export interface ChartSpec {
  kind: 'bar' | 'line' | 'pie' | 'scatter' | 'table' | 'kpi'
  title: string
  x: string | null
  y: string | null
  series: string | null
  data: Record<string, unknown>[]
}

export interface ChatAttachment {
  mime_type: string
  data: string // base64
  name?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  attachments?: { mime_type: string; size: number }[]
  model?: string
  mode?: string
  query?: string
  references?: string[]
  chart?: ChartSpec | null
  rows?: Record<string, unknown>[] | null
  error?: string
}
