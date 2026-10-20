import { useState } from 'react'
import type { ChatSession } from '../../types'

interface Props {
  sessions: ChatSession[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
  onBack?: () => void
}

export function HistoryRail({ sessions, activeId, onSelect, onNew, onRename, onDelete, onBack }: Props) {
  const [editing, setEditing] = useState<string | null>(null)
  const [title, setTitle] = useState('')

  return (
    <aside className="scrollbar-thin flex h-full w-64 shrink-0 flex-col gap-3 overflow-y-auto border-r border-border p-4">
      {onBack && <button onClick={onBack} className="self-start text-xs text-muted hover:text-text">&larr; Back to GraphKit</button>}
      <button onClick={onNew}
        className="rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:brightness-110">
        New chat
      </button>
      <nav aria-label="Conversation history" className="flex flex-col gap-1">
        {sessions.map((s) => (
          <div key={s.id}
            className={`group flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm ${s.id === activeId ? 'bg-accent/15 text-text' : 'text-muted hover:bg-panel-2 hover:text-text'}`}>
            {editing === s.id ? (
              <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { onRename(s.id, title); setEditing(null) }
                  if (e.key === 'Escape') setEditing(null)
                }}
                onBlur={() => setEditing(null)}
                className="flex-1 rounded border border-accent/50 bg-ink/40 px-1.5 py-0.5 text-sm text-text outline-none" />
            ) : (
              <button onClick={() => onSelect(s.id)} className="flex-1 truncate text-left">{s.title}</button>
            )}
            <button onClick={() => { setEditing(s.id); setTitle(s.title) }}
              aria-label={`Rename ${s.title}`}
              className="shrink-0 opacity-0 hover:text-text group-hover:opacity-100">✎</button>
            <button onClick={() => onDelete(s.id)} aria-label={`Delete ${s.title}`}
              className="shrink-0 opacity-0 hover:text-red group-hover:opacity-100">✕</button>
          </div>
        ))}
        {sessions.length === 0 && <p className="px-2 py-1.5 text-xs text-muted">No chats yet.</p>}
      </nav>
    </aside>
  )
}
