import type { User } from 'firebase/auth'
import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { BenchmarkTab } from './components/BenchmarkTab'
import { ChatView } from './components/chat/ChatView'
import { EditTab } from './components/EditTab'
import { GraphTab } from './components/GraphTab'
import { MetricsBar } from './components/MetricsBar'
import { ReviewApplyTab } from './components/ReviewApplyTab'
import { SemanticTab } from './components/SemanticTab'
import { Sidebar } from './components/Sidebar'
import { onAuthChange } from './firebase'
import type { State } from './types'

const TABS = ['Graph', 'Edit', 'Review and apply', 'Semantic', 'Benchmark'] as const
type Tab = (typeof TABS)[number]

export default function App() {
  const [name, setName] = useState('SupplyChain')
  const [state, setState] = useState<State | null>(null)
  const [tab, setTab] = useState<Tab>('Graph')
  const [refreshKey, setRefreshKey] = useState(0)
  const [toast, setToast] = useState<{ kind: 'info' | 'error'; msg: string } | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [view, setView] = useState<'workflow' | 'chat'>('workflow')

  const refresh = useCallback(() => {
    api.state(name).then(setState).catch(() => setState(null))
  }, [name])

  useEffect(() => { refresh() }, [refresh, refreshKey])
  useEffect(() => onAuthChange(setUser), [])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 5000)
    return () => clearTimeout(t)
  }, [toast])

  const bump = () => setRefreshKey((k) => k + 1)

  if (view === 'chat') {
    return <ChatView workspace={name} user={user} onBack={() => setView('workflow')} />
  }

  return (
    <div className="flex h-screen gap-5 p-5">
      <Sidebar
        name={name}
        onNameChange={setName}
        hasApproved={!!state?.has_approved}
        onScanned={(msg) => { setToast({ kind: 'info', msg }); bump() }}
        onError={(msg) => setToast({ kind: 'error', msg })}
        user={user}
        onOpenChat={() => setView('chat')}
      />

      <main className="scrollbar-thin flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto">
        {toast && (
          <div className={`card p-3 text-sm ${toast.kind === 'error' ? 'border-red/40 text-red' : 'border-accent-2/30 text-accent-2'}`}>
            {toast.msg}
          </div>
        )}

        {!state?.has_draft ? (
          <div className="card p-8">
            <h2 className="text-lg font-semibold text-text">Start with a scan</h2>
            <p className="mt-2 text-sm text-muted">
              Pick a source in the sidebar and press <strong className="text-text">Scan tables</strong>. The demo
              uses a small made-up supply-chain dataset, so it works without a cloud account.
            </p>
          </div>
        ) : (
          <>
            <MetricsBar state={state} />

            <div className="flex gap-1.5 self-start rounded-lg border border-border p-1">
              {TABS.map((t) => (
                <button key={t} onClick={() => setTab(t)}
                  className={`rounded-md px-3.5 py-1.5 text-sm transition ${
                    tab === t ? 'bg-accent text-white' : 'text-muted hover:text-text'
                  }`}>
                  {t}
                </button>
              ))}
            </div>

            {tab === 'Graph' && <GraphTab name={name} refreshKey={refreshKey} />}
            {tab === 'Edit' && (
              <EditTab name={name} refreshKey={refreshKey}
                onSaved={(problems) => {
                  bump()
                  setToast(problems.length
                    ? { kind: 'error', msg: `Saved, but fix these before applying:\n- ${problems.join('\n- ')}` }
                    : { kind: 'info', msg: 'Draft saved.' })
                }}
              />
            )}
            {tab === 'Review and apply' && (
              <ReviewApplyTab name={name} state={state} refreshKey={refreshKey} onConfirmed={bump} />
            )}
            {tab === 'Semantic' && <SemanticTab name={name} />}
            {tab === 'Benchmark' && <BenchmarkTab name={name} state={state} />}
          </>
        )}
      </main>
    </div>
  )
}
