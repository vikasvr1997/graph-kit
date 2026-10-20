export type ThemeChoice = 'light' | 'dark' | 'system'

const KEY = 'graphkit-theme'

function systemPrefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true
}

export function getStoredTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    // localStorage can throw in private mode; fall through to the default.
  }
  return 'system'
}

export function applyTheme(choice: ThemeChoice) {
  const resolved = choice === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : choice
  document.documentElement.setAttribute('data-theme', resolved)
  try {
    localStorage.setItem(KEY, choice)
  } catch {
    // Best-effort persistence only.
  }
}

export function initTheme() {
  applyTheme(getStoredTheme())
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (getStoredTheme() === 'system') applyTheme('system')
  })
}

export function resolvedScheme(): 'light' | 'dark' {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'
}

/** Re-renders a component when the resolved light/dark scheme changes. */
export function subscribeScheme(cb: (scheme: 'light' | 'dark') => void): () => void {
  const observer = new MutationObserver(() => cb(resolvedScheme()))
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  return () => observer.disconnect()
}
