import type { User } from 'firebase/auth'
import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { chatApi, streamMessage } from '../../chatApi'
import { signInWithGoogle } from '../../firebase'
import type { ChatAttachment, ChatMessage, ChatSession, ModelsResponse } from '../../types'
import { HistoryRail } from './HistoryRail'
import { MessageBubble } from './MessageBubble'
import { Composer } from './Composer'

const SUGGESTIONS = [
  'What tables and relationships does this graph have?',
  'Show me a chart of parts by supplier',
  'Which recall affected the most vehicle models?',
]

interface Props {
  workspace: string
  user: User | null
  onBack: () => void
}

export function ChatView({ workspace, user, onBack }: Props) {
  const [models, setModels] = useState<ModelsResponse | null>(null)
  const [generationModel, setGenerationModel] = useState('')
  const [embeddingModel, setEmbeddingModel] = useState('')
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [variants, setVariants] = useState<Record<string, ChatMessage[]>>({})
  const [variantIndex, setVariantIndex] = useState<Record<string, number>>({})
  const [streamingText, setStreamingText] = useState('')
  const [streamingStatus, setStreamingStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ cause: string; recovery: string } | null>(null)
  const [prefill, setPrefill] = useState<string | undefined>(undefined)
  const [pinnedToBottom, setPinnedToBottom] = useState(true)

  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.models().then((m) => {
      setModels(m)
      setGenerationModel(m.defaults.generation_model)
      setEmbeddingModel(m.defaults.embedding_model)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!user) return
    chatApi.listSessions().then(setSessions).catch(() => {})
  }, [user])

  // Deliberately not a useEffect keyed on activeId: a brand-new session (created inside
  // ensureSession, just below) already has the right local messages building up turn by
  // turn, and a background GET racing that in-flight stream would clobber it with a stale
  // snapshot. History is only fetched when explicitly switching to an *existing* session.
  const selectSession = (id: string) => {
    setActiveId(id)
    chatApi.listMessages(id).then(setMessages).catch(() => {})
  }

  useEffect(() => {
    if (!pinnedToBottom || !scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, streamingText, pinnedToBottom])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    setPinnedToBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 100)
  }

  const ensureSession = async (): Promise<string> => {
    if (activeId) return activeId
    const session = await chatApi.createSession(workspace, generationModel, embeddingModel)
    setSessions((s) => [session, ...s])
    setActiveId(session.id)
    return session.id
  }

  const send = async (text: string, attachments: ChatAttachment[]) => {
    setError(null)
    const sessionId = await ensureSession()
    const userMsg: ChatMessage = { id: `tmp-${Date.now()}`, role: 'user', text, attachments: attachments.map((a) => ({ mime_type: a.mime_type, size: a.data.length })) }
    setMessages((m) => [...m, userMsg])
    setBusy(true)
    setStreamingText('')
    setStreamingStatus('Sending...')

    const controller = new AbortController()
    abortRef.current = controller
    try {
      await streamMessage(sessionId, text, attachments, generationModel, embeddingModel, {
        onStatus: (s) => setStreamingStatus(s),
        onToken: (t) => { setStreamingStatus(null); setStreamingText((prev) => prev + t) },
        onError: (cause, recovery) => setError({ cause, recovery }),
        onDone: (saved) => {
          setMessages((m) => [...m, saved])
          setStreamingText('')
        },
      }, controller.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setError({ cause: (e as Error).message, recovery: 'Try again.' })
      } else if (streamingText) {
        setMessages((m) => [...m, { id: `stopped-${Date.now()}`, role: 'assistant', text: streamingText, model: generationModel }])
        setStreamingText('')
      }
    } finally {
      setBusy(false)
      setStreamingStatus(null)
      abortRef.current = null
      if (!document.activeElement || document.activeElement === document.body) {
        // Per the a11y checklist: don't steal focus onto the reply when streaming ends.
      }
    }
  }

  const regenerate = async (assistantIndex: number) => {
    const priorUser = messages[assistantIndex - 1]
    if (!priorUser || priorUser.role !== 'user' || !activeId) return
    const id = messages[assistantIndex].id
    setBusy(true)
    setStreamingText('')
    const controller = new AbortController()
    abortRef.current = controller
    try {
      await streamMessage(activeId, priorUser.text, [], generationModel, embeddingModel, {
        onToken: (t) => setStreamingText((p) => p + t),
        onError: (cause, recovery) => setError({ cause, recovery }),
        onDone: (saved) => {
          setVariants((v) => {
            const existing = v[id] ?? [messages[assistantIndex]]
            return { ...v, [id]: [...existing, saved] }
          })
          setVariantIndex((v) => ({ ...v, [id]: (v[id] ?? 0) + 1 }))
          setStreamingText('')
        },
      }, controller.signal)
    } finally {
      setBusy(false)
    }
  }

  const stop = () => abortRef.current?.abort()

  const displayed = (msg: ChatMessage): ChatMessage => {
    const vs = variants[msg.id]
    if (!vs) return msg
    return vs[variantIndex[msg.id] ?? vs.length - 1] ?? msg
  }

  if (!user) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4">
        <p className="text-sm text-muted">Sign in to use the assistant.</p>
        <button onClick={() => signInWithGoogle()} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:brightness-110">
          Sign in with Google
        </button>
        <button onClick={onBack} className="text-xs text-muted hover:text-text">&larr; Back to GraphKit</button>
      </div>
    )
  }

  return (
    <div className="flex h-screen w-full">
      <HistoryRail
        sessions={sessions} activeId={activeId}
        onSelect={selectSession}
        onNew={() => { setActiveId(null); setMessages([]) }}
        onRename={(id, title) => {
          chatApi.renameSession(id, title).catch(() => {})
          setSessions((s) => s.map((x) => (x.id === id ? { ...x, title } : x)))
        }}
        onDelete={(id) => {
          chatApi.deleteSession(id).catch(() => {})
          setSessions((s) => s.filter((x) => x.id !== id))
          if (id === activeId) setActiveId(null)
        }}
        onBack={onBack}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <p className="text-sm text-muted">Workspace: <span className="text-text">{workspace}</span></p>
          {models && (
            <select value={generationModel} onChange={(e) => setGenerationModel(e.target.value)}
              className="rounded-md border border-border bg-ink/40 px-2 py-1 text-xs text-text">
              {models.generation_models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          )}
        </header>

        <div ref={scrollRef} onScroll={onScroll} className="scrollbar-thin flex-1 overflow-y-auto px-5 py-6">
          {messages.length === 0 && !streamingText && (
            <div className="w-full py-16 text-center">
              <h2 className="text-lg font-semibold text-text">Ask anything about this dataset</h2>
              <p className="mt-2 text-sm text-muted">
                Grounded in the approved graph, semantic catalog and embeddings for <strong>{workspace}</strong>.
                AI replies can be wrong - check citations and generated queries before relying on them.
              </p>
            </div>
          )}

          <div className="flex flex-col gap-5">
            {messages.map((m, i) => {
              const shown = displayed(m)
              const vs = variants[m.id]
              return (
                <MessageBubble
                  key={m.id}
                  message={shown}
                  variantCount={vs?.length ?? 1}
                  variantIndex={variantIndex[m.id] ?? (vs ? vs.length - 1 : 0)}
                  onNavigateVariant={(delta) => setVariantIndex((v) => {
                    const count = vs?.length ?? 1
                    const next = Math.min(count - 1, Math.max(0, (v[m.id] ?? count - 1) + delta))
                    return { ...v, [m.id]: next }
                  })}
                  onCopy={() => navigator.clipboard.writeText(shown.text)}
                  onShare={() => navigator.clipboard.writeText(`Q: ${messages[i - 1]?.role === 'user' ? messages[i - 1].text : ''}\nA: ${shown.text}`)}
                  onRegenerate={m.role === 'assistant' ? () => regenerate(i) : undefined}
                  onEdit={m.role === 'user' ? () => setPrefill(m.text) : undefined}
                />
              )
            })}

            {(streamingText || streamingStatus) && (
              <MessageBubble
                message={{ id: 'streaming', role: 'assistant', text: streamingText, model: generationModel }}
                streaming variantCount={1} variantIndex={0} onNavigateVariant={() => {}}
                onCopy={() => {}} onShare={() => {}}
              />
            )}
            {streamingStatus && <p className="w-full text-xs text-muted">{streamingStatus}</p>}

            {error && (
              <div className="w-full rounded-lg border border-red/40 bg-red/5 px-4 py-2 text-sm text-red">
                {error.cause} - {error.recovery}
              </div>
            )}
          </div>
        </div>

        <Composer
          busy={busy} onSend={send} onStop={stop}
          suggestions={messages.length === 0 ? SUGGESTIONS : []}
          prefill={prefill} onPrefillConsumed={() => setPrefill(undefined)}
        />
      </div>
    </div>
  )
}
