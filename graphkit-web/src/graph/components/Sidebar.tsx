import type { User } from 'firebase/auth'
import { useState } from 'react'
import { api, ApiError } from '../api'
import type { Backend } from '../types'
import { SettingsButton } from './SettingsButton'

interface Props {
  name: string
  onNameChange: (n: string) => void
  hasApproved: boolean
  onScanned: (msg: string) => void
  onError: (msg: string) => void
  user: User | null
  onOpenChat?: () => void
}

const SOURCES: { label: string; backend: Backend }[] = [
  { label: 'Demo (SQLite)', backend: 'sqlite' },
  { label: 'BigQuery', backend: 'bigquery' },
  { label: 'Spanner', backend: 'spanner' },
]

export function Sidebar({ name, onNameChange, hasApproved, onScanned, onError, user, onOpenChat }: Props) {
  const [source, setSource] = useState<Backend>('sqlite')
  const [project, setProject] = useState(import.meta.env.VITE_GOOGLE_CLOUD_PROJECT ?? '')
  const [dataset, setDataset] = useState('vehicle_supply_chain')
  const [region, setRegion] = useState('US')
  const [dataProject, setDataProject] = useState('')
  const [instance, setInstance] = useState('')
  const [database, setDatabase] = useState('')
  const [sqlitePath, setSqlitePath] = useState('demo/supply_chain.db')
  const [sampleRows, setSampleRows] = useState(100)
  const [checkValues, setCheckValues] = useState(true)
  const [descFile, setDescFile] = useState('')
  const [useLlm, setUseLlm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [optionsOpen, setOptionsOpen] = useState(false)

  const location = () => {
    if (source === 'bigquery') {
      const loc: Record<string, string> = { project, dataset, region }
      if (dataProject) loc.data_project = dataProject
      return loc
    }
    if (source === 'spanner') return { project, instance, database }
    return { path: sqlitePath }
  }

  const createDemo = async () => {
    try {
      setBusy(true)
      await api.createDemo(sqlitePath)
      onScanned('Demo data created. Press Scan tables.')
    } catch (e) {
      onError(e instanceof ApiError ? e.message : 'Failed to create demo data.')
    } finally {
      setBusy(false)
    }
  }

  const scanTables = async () => {
    try {
      setBusy(true)
      const r = await api.scan({
        name, backend: source, location: location(), sample_rows: sampleRows,
        descriptions_file: descFile || null, check_values: checkValues, use_llm: useLlm,
      })
      onScanned(`Found ${r.nodes} nodes and ${r.edges} edges.`)
    } catch (e) {
      onError(e instanceof ApiError ? e.message : 'Scan failed.')
    } finally {
      setBusy(false)
    }
  }

  const watch = async () => {
    try {
      setBusy(true)
      const r = await api.watch(name, sampleRows, checkValues)
      onScanned(r.new.length ? `${r.new.length} new items to review: ${r.new.join(', ')}` : 'No new tables or links.')
    } catch (e) {
      onError(e instanceof ApiError ? e.message : 'Watch failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="card scrollbar-thin flex h-full w-80 shrink-0 flex-col gap-5 overflow-y-auto p-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <span className="text-xl">🕸️</span> graph<span className="text-accent">kit</span>
        </h1>
        <p className="mt-1 text-xs text-muted">Find links between tables, review them, and turn them into a property graph.</p>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted uppercase tracking-wide">Source</span>
        <div className="flex flex-col gap-1.5">
          {SOURCES.map((s) => (
            <button
              key={s.backend}
              onClick={() => setSource(s.backend)}
              className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                source === s.backend
                  ? 'border-accent/60 bg-accent/10 text-text'
                  : 'border-border text-muted hover:border-accent/30 hover:text-text'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {source === 'bigquery' && (
        <div className="flex flex-col gap-2">
          <Field label="Project (runs queries)" value={project} onChange={setProject} />
          <Field label="Dataset" value={dataset} onChange={setDataset} />
          <Field label="Dataset location" value={region} onChange={setRegion} />
          <Field label="Data project (if different)" value={dataProject} onChange={setDataProject} />
        </div>
      )}
      {source === 'spanner' && (
        <div className="flex flex-col gap-2">
          <Field label="Project" value={project} onChange={setProject} />
          <Field label="Instance" value={instance} onChange={setInstance} />
          <Field label="Database" value={database} onChange={setDatabase} />
        </div>
      )}
      {source === 'sqlite' && (
        <div className="flex flex-col gap-2">
          <Field label="SQLite file" value={sqlitePath} onChange={setSqlitePath} />
          <button
            onClick={createDemo}
            disabled={busy}
            className="rounded-lg border border-border py-1.5 text-xs text-muted hover:border-accent/40 hover:text-text disabled:opacity-50"
          >
            Create demo data
          </button>
        </div>
      )}

      <Field label="Graph name" value={name} onChange={onNameChange} />

      <details open={optionsOpen} onToggle={(e) => setOptionsOpen(e.currentTarget.open)} className="rounded-lg border border-border p-3">
        <summary className="cursor-pointer text-xs font-medium text-muted">Scan options</summary>
        <div className="mt-3 flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-xs text-muted">
            Rows to sample per table: <span className="text-text">{sampleRows}</span>
            <input type="range" min={10} max={1000} step={10} value={sampleRows}
              onChange={(e) => setSampleRows(Number(e.target.value))} className="accent-[color:var(--color-accent)]" />
          </label>
          <Checkbox label="Check guessed links with small queries" checked={checkValues} onChange={setCheckValues} />
          <Field label="Extra descriptions file (JSON, optional)" value={descFile} onChange={setDescFile} />
          <Checkbox label="Ask Gemini to improve names and directions" checked={useLlm} onChange={setUseLlm} />
        </div>
      </details>

      <button
        onClick={scanTables}
        disabled={busy || !name}
        className="rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white shadow-[0_8px_24px_-8px_var(--color-accent)] transition hover:brightness-110 disabled:opacity-50"
      >
        Scan tables
      </button>
      {hasApproved && (
        <button
          onClick={watch}
          disabled={busy}
          className="rounded-lg border border-border px-3 py-2 text-sm text-muted hover:border-accent/40 hover:text-text disabled:opacity-50"
        >
          Look for new tables
        </button>
      )}

      {onOpenChat && <button
        onClick={onOpenChat}
        className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-sm font-medium text-text transition hover:bg-accent/20"
      >
        Open Assistant
      </button>}

      <SettingsButton user={user} authEnabled={!!onOpenChat} />
    </aside>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-ink/40 px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent/60"
      />
    </label>
  )
}

function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="accent-[color:var(--color-accent)]" />
      {label}
    </label>
  )
}
