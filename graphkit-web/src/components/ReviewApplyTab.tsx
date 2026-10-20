import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import type { Changes, State, TerraformFiles } from '../types'

interface Props {
  name: string
  state: State
  refreshKey: number
  onConfirmed: () => void
}

const ICON: Record<string, string> = { added: '🟢', changed: '🟡', removed: '🔴' }

export function ReviewApplyTab({ name, state, refreshKey, onConfirmed }: Props) {
  const [changes, setChanges] = useState<Changes | null>(null)
  const [ddl, setDdl] = useState<{ ddl: string | null; problems: string[]; preview: boolean } | null>(null)
  const [tf, setTf] = useState<TerraformFiles | null>(null)
  const [reviewed, setReviewed] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [planLog, setPlanLog] = useState<string | null>(null)
  const [applyLog, setApplyLog] = useState<string | null>(null)
  const [reallyCreate, setReallyCreate] = useState(false)
  const [busy, setBusy] = useState(false)

  const problems = state.problems ?? []

  useEffect(() => {
    api.changes(name).then(setChanges).catch(() => setChanges(null))
    api.ddl(name).then(setDdl).catch(() => setDdl(null))
    api.terraform(name).then(setTf).catch(() => setTf(null))
  }, [name, refreshKey])

  const confirm = async () => {
    setConfirming(true)
    setError(null)
    try {
      await api.confirm(name)
      onConfirmed()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Confirm failed.')
    } finally {
      setConfirming(false)
    }
  }

  const runPlan = async () => {
    setBusy(true)
    try { setPlanLog((await api.terraformPlan(name)).log) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Plan failed.') }
    finally { setBusy(false) }
  }
  const runApply = async () => {
    setBusy(true)
    try {
      const r = await api.terraformApply(name)
      setApplyLog(r.log)
    } catch (e) { setError(e instanceof ApiError ? e.message : 'Apply failed.') }
    finally { setBusy(false) }
  }

  const noChanges = changes && !changes.added.length && !changes.changed.length && !changes.removed.length

  return (
    <div className="flex flex-col gap-6">
      {problems.length > 0 && (
        <div className="card border-red/40 p-4 text-sm text-red">
          <p className="mb-1 font-medium">Fix these in the Edit tab first:</p>
          <ul className="list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">
        <div className="card p-4">
          <h3 className="mb-3 text-sm font-medium text-text">Changes since last approval</h3>
          {noChanges && <p className="text-xs text-muted">No changes.</p>}
          {changes && (
            <ul className="flex flex-col gap-1 text-xs">
              {(['added', 'changed', 'removed'] as const).flatMap((kind) =>
                changes[kind].map((item) => (
                  <li key={`${kind}-${item}`} className="text-muted">
                    {ICON[kind]} {kind}: <code className="text-text">{item}</code>
                  </li>
                )))}
            </ul>
          )}
        </div>

        <div className="card p-4">
          <h3 className="mb-3 text-sm font-medium text-text">Graph DDL</h3>
          {ddl?.preview && (
            <p className="mb-2 text-xs text-muted">Demo source: shown as BigQuery DDL. Scan a BigQuery or Spanner source to apply for real.</p>
          )}
          {ddl?.ddl && (
            <pre className="scrollbar-thin max-h-72 overflow-auto rounded-lg bg-ink/60 p-3 text-xs text-accent-2">{ddl.ddl}</pre>
          )}
        </div>
      </div>

      <div className="card flex items-center justify-between p-4">
        <label className="flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" checked={reviewed} disabled={problems.length > 0}
            onChange={(e) => setReviewed(e.target.checked)} className="accent-[color:var(--color-accent)]" />
          I reviewed the graph and want to approve it
        </label>
        <button onClick={confirm} disabled={!reviewed || confirming}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:brightness-110 disabled:opacity-40">
          {confirming ? 'Confirming...' : 'Confirm and write Terraform'}
        </button>
      </div>

      {error && <div className="card border-red/40 p-3 text-sm text-red">{error}</div>}

      {state.has_approved && (state.backend === 'bigquery' || state.backend === 'spanner') && tf?.available && (
        <div className="card p-4">
          <h3 className="mb-3 text-sm font-medium text-text">Terraform</h3>
          <div className="flex flex-col gap-3">
            {Object.entries(tf.files ?? {}).map(([f, content]) => (
              <details key={f} className="rounded-lg border border-border p-3">
                <summary className="cursor-pointer text-xs text-muted">{f}</summary>
                <pre className="scrollbar-thin mt-2 max-h-72 overflow-auto rounded-lg bg-ink/60 p-3 text-xs text-accent-2">{content}</pre>
              </details>
            ))}
          </div>

          {!tf.terraform_installed ? (
            <p className="mt-3 text-xs text-muted">
              Terraform isn't installed here. Run it yourself from <code>terraform/</code> with{' '}
              <code>terraform init && terraform apply</code>.
            </p>
          ) : (
            <div className="mt-4 grid grid-cols-2 gap-4">
              <div>
                <button onClick={runPlan} disabled={busy}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted hover:border-accent/40 hover:text-text disabled:opacity-50">
                  Terraform plan
                </button>
                {planLog && <pre className="scrollbar-thin mt-2 max-h-56 overflow-auto rounded-lg bg-ink/60 p-3 text-xs text-muted">{planLog.slice(-8000)}</pre>}
              </div>
              <div>
                <label className="flex items-center gap-2 text-xs text-muted">
                  <input type="checkbox" checked={reallyCreate} onChange={(e) => setReallyCreate(e.target.checked)}
                    className="accent-[color:var(--color-accent)]" />
                  Create the graph in {state.location?.project}
                </label>
                <button onClick={runApply} disabled={!reallyCreate || busy}
                  className="mt-2 rounded-lg bg-red/80 px-3 py-1.5 text-xs font-medium text-white hover:bg-red disabled:opacity-40">
                  Apply
                </button>
                {applyLog && <pre className="scrollbar-thin mt-2 max-h-56 overflow-auto rounded-lg bg-ink/60 p-3 text-xs text-muted">{applyLog.slice(-8000)}</pre>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
