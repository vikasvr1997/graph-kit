import { useEffect, useRef, useState } from 'react'
import type { ChatAttachment } from '../../types'

interface Props {
  busy: boolean
  onSend: (text: string, attachments: ChatAttachment[]) => void
  onStop: () => void
  suggestions: string[]
  prefill?: string
  onPrefillConsumed?: () => void
}

function fileToAttachment(file: File): Promise<ChatAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      resolve({ mime_type: file.type || 'application/octet-stream', data: result.split(',')[1], name: file.name })
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

export function Composer({ busy, onSend, onStop, suggestions, prefill, onPrefillConsumed }: Props) {
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [dismissedChips, setDismissedChips] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (prefill !== undefined) {
      setText(prefill)
      textarea.current?.focus()
      onPrefillConsumed?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill])

  const send = () => {
    if (!text.trim() || busy) return
    onSend(text.trim(), attachments)
    setText('')
    setAttachments([])
  }

  const onFiles = async (files: FileList | null) => {
    if (!files) return
    const next = await Promise.all(Array.from(files).map(fileToAttachment))
    setAttachments((a) => [...a, ...next])
  }

  return (
    <div className="sticky bottom-0 border-t border-border bg-panel/95 p-4 backdrop-blur">
      {!dismissedChips && suggestions.length > 0 && text === '' && (
        <div className="mb-3 flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <button key={s} onClick={() => setText(s)}
              className="rounded-full border border-border px-3 py-1 text-xs text-muted hover:border-accent/40 hover:text-text">
              {s}
            </button>
          ))}
          <button onClick={() => setDismissedChips(true)} aria-label="Dismiss suggestions"
            className="rounded-full px-2 py-1 text-xs text-muted hover:text-text">✕</button>
        </div>
      )}

      {attachments.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {attachments.map((a, i) => (
            <span key={i} className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted">
              {a.name ?? a.mime_type}
              <button onClick={() => setAttachments((as) => as.filter((_, j) => j !== i))} aria-label="Remove attachment">✕</button>
            </span>
          ))}
        </div>
      )}

      <div className="flex w-full items-end gap-2">
        <button onClick={() => fileInput.current?.click()} aria-label="Attach image or file"
          className="shrink-0 rounded-lg border border-border px-3 py-2.5 text-muted hover:border-accent/40 hover:text-text">
          📎
        </button>
        <input ref={fileInput} type="file" multiple accept="image/*,.pdf,.csv,.txt" className="hidden"
          onChange={(e) => onFiles(e.target.files)} />

        <textarea
          ref={textarea}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); send() }
            if (e.key === 'Escape') setText('')
          }}
          placeholder="Ask about the dataset, or request a chart... (Cmd+Enter to send)"
          rows={1}
          className="flex-1 resize-none rounded-lg border border-border bg-ink/40 px-3 py-2.5 text-sm text-text outline-none focus:border-accent/60"
        />

        {busy ? (
          <button onClick={onStop}
            className="shrink-0 rounded-lg bg-red/80 px-4 py-2.5 text-sm font-medium text-white hover:bg-red">
            Stop generating
          </button>
        ) : (
          <button onClick={send} disabled={!text.trim()}
            className="shrink-0 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:brightness-110 disabled:opacity-40">
            Send
          </button>
        )}
      </div>
    </div>
  )
}
