import type { User } from 'firebase/auth'
import { useEffect, useRef, useState } from 'react'
import { applyTheme, getStoredTheme, type ThemeChoice } from '../../theme'

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
]

export function SettingsButton({ user, authEnabled = true }: { user: User | null; authEnabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const [theme, setTheme] = useState<ThemeChoice>(getStoredTheme())
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  const pick = (t: ThemeChoice) => {
    setTheme(t)
    applyTheme(t)
  }

  const signIn = async () => {
    setBusy(true)
    try { await (await import('../../chat/firebase')).signInWithGoogle() } finally { setBusy(false) }
  }
  const signOutNow = async () => {
    setBusy(true)
    try { await (await import('../../chat/firebase')).signOutUser() } finally { setBusy(false) }
  }

  return (
    <div ref={ref} className="relative mt-auto pt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Settings"
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-lg border border-border px-3 py-2 text-left text-sm text-muted transition hover:border-accent/40 hover:text-text"
      >
        <GearIcon />
        <span className="flex-1 truncate">{user ? user.displayName ?? user.email : 'Settings'}</span>
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-20 mb-2 w-72 rounded-xl border border-border bg-panel p-3 shadow-xl">
          <p className="mb-2 text-xs font-medium text-muted">Theme</p>
          <div className="mb-3 flex gap-1.5 rounded-lg border border-border p-1">
            {THEMES.map((t) => (
              <button key={t.value} onClick={() => pick(t.value)}
                className={`flex-1 rounded-md px-2 py-1 text-xs transition ${theme === t.value ? 'bg-accent text-white' : 'text-muted hover:text-text'}`}>
                {t.label}
              </button>
            ))}
          </div>

          {authEnabled && <><p className="mb-2 text-xs font-medium text-muted">Account</p>
          {user ? (
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm text-text">{user.email}</span>
              <button onClick={signOutNow} disabled={busy}
                className="shrink-0 rounded-md border border-border px-2.5 py-1 text-xs text-muted hover:border-red/40 hover:text-red disabled:opacity-50">
                Sign out
              </button>
            </div>
          ) : (
            <button onClick={signIn} disabled={busy}
              className="w-full rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:brightness-110 disabled:opacity-50">
              {busy ? 'Signing in...' : 'Sign in with Google'}
            </button>
          )}</>}
        </div>
      )}
    </div>
  )
}

function GearIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}
