import type { ModelsResponse } from './types'

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {}

export async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(body.detail || `Request failed: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  capabilities: () => req<{ graphkit: boolean; chat: boolean }>('/api/capabilities'),
  models: () => req<ModelsResponse>('/api/models'),
}
