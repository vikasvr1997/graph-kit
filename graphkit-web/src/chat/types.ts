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
