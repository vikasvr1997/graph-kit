import { currentIdToken } from './firebase'
import type { ChatAttachment, ChatMessage, ChatSession } from './types'

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

async function authedFetch(path: string, init?: RequestInit) {
  const token = await currentIdToken()
  if (!token) throw new Error('Sign in to use the assistant.')
  return fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...init?.headers },
  })
}

async function authedJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authedFetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const chatApi = {
  createSession: (workspace: string, generationModel: string, embeddingModel: string) =>
    authedJson<ChatSession>('/api/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({ workspace, generation_model: generationModel, embedding_model: embeddingModel }),
    }),
  listSessions: () => authedJson<ChatSession[]>('/api/chat/sessions'),
  renameSession: (id: string, title: string) =>
    authedJson<{ ok: boolean }>(`/api/chat/sessions/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  deleteSession: (id: string) =>
    authedJson<{ ok: boolean }>(`/api/chat/sessions/${id}`, { method: 'DELETE' }),
  listMessages: (id: string) => authedJson<ChatMessage[]>(`/api/chat/sessions/${id}/messages`),
}

export interface StreamHandlers {
  onStatus?: (text: string) => void
  onToken?: (text: string) => void
  onError?: (cause: string, recovery: string) => void
  onDone?: (message: ChatMessage) => void
}

/** Parses one SSE frame at a time from the response body as it arrives. */
export async function streamMessage(
  sessionId: string,
  text: string,
  attachments: ChatAttachment[],
  generationModel: string | undefined,
  embeddingModel: string | undefined,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await authedFetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({
      text, attachments, generation_model: generationModel, embedding_model: embeddingModel,
    }),
    signal,
  })
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const eventLine = frame.split('\n').find((l) => l.startsWith('event: '))
      const dataLine = frame.split('\n').find((l) => l.startsWith('data: '))
      if (!eventLine || !dataLine) continue
      const event = eventLine.slice('event: '.length)
      const data = JSON.parse(dataLine.slice('data: '.length))
      if (event === 'status') handlers.onStatus?.(data.text)
      else if (event === 'token') handlers.onToken?.(data.text)
      else if (event === 'error') handlers.onError?.(data.cause, data.recovery)
      else if (event === 'done') handlers.onDone?.(data)
    }
  }
}
