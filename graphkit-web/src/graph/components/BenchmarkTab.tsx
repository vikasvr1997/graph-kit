import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import type { BenchResponse, State } from '../types'

interface Props {
  name: string
  state: State
}

export function BenchmarkTab({ name, state }: Props) {
  const [hops, setHops] = useState(3)
  const [limit, setLimit] = useState(20)
  const [llmN, setLlmN] = useState(0)
  const [repeat, setRepeat] = useState(3)
  const [bench, setBench] = useState<BenchResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.bench(name).then(setBench).catch(() => {})
  }, [name])

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setBench(await api.runBench({ name, hops, limit, llm_n: llmN, repeat }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Benchmark failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <p className="text-xs text-muted">
        Generates test questions from the graph, runs each as GQL and as plain SQL, checks the answers match, and
        times both. Matching queries are saved as examples an agent can reuse.
      </p>

      <div className="card grid grid-cols-4 gap-4 p-4">
        <NumberField label="Max hops" value={hops} min={1} max={4} onChange={setHops} />
        <NumberField label="Generated queries" value={limit} min={1} max={100} onChange={setLimit} />
        <NumberField label="Extra Gemini questions" value={llmN} min={0} max={30} onChange={setLlmN} />
        <NumberField label="Runs per query" value={repeat} min={1} max={10} onChange={setRepeat} />
      </div>

      <button onClick={run} disabled={busy}
        className="self-start rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:brightness-110 disabled:opacity-50">
        {busy ? 'Running queries...' : 'Run benchmark'}
      </button>

      {error && <div className="card border-red/40 p-3 text-sm text-red">{error}</div>}

      {bench?.available && bench.summary && (
        <>
          <div className="grid grid-cols-5 gap-4">
            <Metric label="Queries" value={bench.summary.queries} />
            <Metric label="Answers match" value={bench.summary.compared ? `${bench.summary.matched}/${bench.summary.compared}` : 'n/a'} />
            <Metric label="GQL median" value={bench.summary.gql_median_ms != null ? `${bench.summary.gql_median_ms} ms` : 'n/a'} />
            <Metric label="SQL median" value={bench.summary.sql_median_ms != null ? `${bench.summary.sql_median_ms} ms` : 'n/a'} />
            <Metric label="Errors" value={bench.summary.errors} />
          </div>

          <div className="card overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted">
                <tr className="border-b border-border">
                  {['Question', 'Match', 'GQL ms', 'SQL ms', 'Faster', 'Rows', 'GQL bytes', 'Error'].map((h) => (
                    <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bench.results?.map((r, i) => (
                  <tr key={i} className="border-b border-border/60">
                    <td className="px-3 py-2">{r.question}</td>
                    <td className={`px-3 py-2 ${r.match === false ? 'text-red' : r.match ? 'text-green' : 'text-muted'}`}>{String(r.match ?? '-')}</td>
                    <td className="px-3 py-2 text-muted">{r.gql_ms ?? '-'}</td>
                    <td className="px-3 py-2 text-muted">{r.sql_ms ?? '-'}</td>
                    <td className="px-3 py-2 text-muted">{r.faster ?? '-'}</td>
                    <td className="px-3 py-2 text-muted">{r.rows ?? '-'}</td>
                    <td className="px-3 py-2 text-muted">{r.gql_bytes ?? '-'}</td>
                    <td className="px-3 py-2 text-red">{r.error ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {state.backend === 'sqlite' && (
            <p className="text-xs text-muted">The demo has no graph engine, so only the SQL side ran. On BigQuery or Spanner both run.</p>
          )}
        </>
      )}
    </div>
  )
}

function NumberField({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      <input type="number" value={value} min={min} max={max} onChange={(e) => onChange(Number(e.target.value))}
        className="rounded-md border border-border bg-ink/40 px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent/60" />
    </label>
  )
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-lg font-semibold text-text">{value}</div>
    </div>
  )
}
