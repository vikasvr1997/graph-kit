import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import type { AskResult, SemanticItem, SemanticState } from '../types'
import type { ModelsResponse } from '../../shared/types'

interface Props {
  name: string
}

export function SemanticTab({ name }: Props) {
  const [models, setModels] = useState<ModelsResponse | null>(null)
  const [state, setState] = useState<SemanticState | null>(null)
  const [items, setItems] = useState<SemanticItem[] | null>(null)
  const [which, setWhich] = useState<'draft' | 'approved'>('draft')
  const [useLlm, setUseLlm] = useState(false)
  const [genModel, setGenModel] = useState('')
  const [embModel, setEmbModel] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  const [question, setQuestion] = useState('')
  const [askMode, setAskMode] = useState<'auto' | 'sql' | 'gql'>('auto')
  const [askResult, setAskResult] = useState<AskResult | null>(null)

  const refresh = () => {
    api.semanticState(name).then(setState).catch(() => setState(null))
    api.semanticCatalog(name, which).then((c) => setItems(c.exists ? c.items ?? [] : null)).catch(() => setItems(null))
  }

  useEffect(() => {
    api.models().then((m) => {
      setModels(m)
      setGenModel((g) => g || m.defaults.generation_model)
      setEmbModel((e) => e || m.defaults.embedding_model)
    }).catch(() => {})
  }, [])

  useEffect(refresh, [name, which])

  // Once embeddings exist, asking must use the exact model they were built with.
  useEffect(() => {
    if (state?.embeddings) setEmbModel(state.embeddings.model)
  }, [state?.embeddings])

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label)
    setError(null)
    setInfo(null)
    try {
      await fn()
      refresh()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `${label} failed.`)
    } finally {
      setBusy(null)
    }
  }

  const propose = () => act('propose', async () => {
    const r = await api.semanticPropose(name, useLlm, genModel)
    setInfo(`Proposed ${r.items.length} catalog items.`)
    setWhich('draft')
  })

  const updateItem = (id: string, patch: Partial<SemanticItem>) =>
    setItems((rows) => rows?.map((r) => (r.id === id ? { ...r, ...patch } : r)) ?? rows)

  const saveDraft = () => act('save', async () => {
    if (!items) return
    await api.saveSemanticDraft(name, items)
    setInfo('Draft saved.')
  })

  const approve = () => act('approve', async () => {
    const r = await api.semanticApprove(name)
    setInfo(`Approved ${r.items} items. Terraform written to terraform/semantic.sql`)
    setWhich('approved')
  })

  const embed = () => act('embed', async () => {
    const r = await api.semanticEmbed(name, embModel)
    setInfo(`Embedded ${r.count} items with ${r.model} (${r.dimensions} dimensions).`)
  })

  const publish = () => act('publish', async () => {
    const r = await api.semanticPublish(name)
    setInfo(`Published ${r.rows} rows to the semantic catalog table.`)
  })

  const ask = () => act('ask', async () => {
    const r = await api.semanticAsk({ name, question, embedding_model: embModel, generation_model: genModel, mode: askMode, use_embeddings: !!state?.embeddings })
    setAskResult(r)
  })

  return (
    <div className="flex flex-col gap-6">
      <p className="text-xs text-muted">
        Proposes business descriptions and aliases for every table, column, node and edge, then embeds and
        publishes them so an agent can answer questions with proper citations. Confirm the graph first.
      </p>

      {models && (
        <div className="card p-4 text-xs text-muted">{models.note}</div>
      )}

      <div className="card grid grid-cols-2 gap-6 p-4">
        <ModelPicker
          label="Generation model" help="Used to propose descriptions, generate harder test questions, and answer questions."
          value={genModel} onChange={setGenModel} options={models?.generation_models ?? []}
        />
        <ModelPicker
          label="Embedding model" help={state?.embeddings ? 'Locked to the model already used for this catalog’s embeddings.' : 'Used to embed the approved catalog for retrieval.'}
          value={embModel} onChange={setEmbModel} options={models?.embedding_models ?? []}
          disabled={!!state?.embeddings}
        />
      </div>

      <div className="card flex flex-wrap items-center gap-4 p-4">
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} className="accent-[color:var(--color-accent)]" />
          Ask Gemini to suggest descriptions and aliases
        </label>
        <button onClick={propose} disabled={busy !== null}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:brightness-110 disabled:opacity-50">
          {busy === 'propose' ? 'Proposing...' : 'Propose catalog'}
        </button>
        <div className="ml-auto flex gap-1.5 rounded-lg border border-border p-1">
          {(['draft', 'approved'] as const).map((w) => (
            <button key={w} onClick={() => setWhich(w)}
              className={`rounded-md px-3 py-1 text-xs capitalize transition ${which === w ? 'bg-accent text-white' : 'text-muted hover:text-text'}`}>
              {w}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="card border-red/40 p-3 text-sm text-red">{error}</div>}
      {info && <div className="card border-accent-2/30 p-3 text-sm text-accent-2">{info}</div>}

      {items && items.length > 0 ? (
        <div className="card scrollbar-thin max-h-96 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-panel-2 text-muted">
              <tr className="border-b border-border">
                {['kind', 'table', 'name', 'description', 'aliases'].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className="border-b border-border/60 align-top">
                  <td className="px-3 py-2 text-muted">{it.kind}</td>
                  <td className="px-3 py-2 text-muted">{it.table}</td>
                  <td className="px-3 py-2 text-text">{it.name}</td>
                  <td className="px-3 py-2">
                    <input value={it.description} disabled={which === 'approved'}
                      onChange={(e) => updateItem(it.id, { description: e.target.value })}
                      className="w-full min-w-48 rounded-md border border-border bg-ink/40 px-2 py-1 text-text outline-none focus:border-accent/60 disabled:opacity-60" />
                  </td>
                  <td className="px-3 py-2">
                    <input value={it.aliases.join(', ')} disabled={which === 'approved'}
                      onChange={(e) => updateItem(it.id, { aliases: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) })}
                      className="w-full min-w-40 rounded-md border border-border bg-ink/40 px-2 py-1 text-text outline-none focus:border-accent/60 disabled:opacity-60" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="card p-4 text-xs text-muted">No {which} catalog yet.</div>
      )}

      {which === 'draft' && items && items.length > 0 && (
        <div className="flex gap-3">
          <button onClick={saveDraft} disabled={busy !== null}
            className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted hover:border-accent/40 hover:text-text disabled:opacity-50">
            {busy === 'save' ? 'Saving...' : 'Save draft'}
          </button>
          <button onClick={approve} disabled={busy !== null}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:brightness-110 disabled:opacity-50">
            {busy === 'approve' ? 'Approving...' : 'Approve catalog'}
          </button>
        </div>
      )}

      {state?.has_approved && (
        <div className="card flex flex-wrap items-center gap-4 p-4">
          <button onClick={embed} disabled={busy !== null}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:brightness-110 disabled:opacity-50">
            {busy === 'embed' ? 'Embedding...' : `Embed with ${embModel || '...'}`}
          </button>
          {state.embeddings && (
            <span className="text-xs text-muted">
              Current embeddings: <code className="text-text">{state.embeddings.model}</code>, {state.embeddings.count} items, {state.embeddings.dimensions} dims
            </span>
          )}
          <button onClick={publish} disabled={busy !== null || !state.embeddings}
            className="ml-auto rounded-lg border border-border px-3 py-1.5 text-sm text-muted hover:border-accent/40 hover:text-text disabled:opacity-50">
            {busy === 'publish' ? 'Publishing...' : 'Publish to dataset'}
          </button>
        </div>
      )}

      {state?.has_approved && (
        <div className="card flex flex-col gap-3 p-4">
          <h3 className="text-sm font-medium text-text">Try a question</h3>
          <div className="flex gap-3">
            <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask a question about the dataset..."
              className="flex-1 rounded-md border border-border bg-ink/40 px-3 py-2 text-sm text-text outline-none focus:border-accent/60" />
            <select value={askMode} onChange={(e) => setAskMode(e.target.value as typeof askMode)}
              className="rounded-md border border-border bg-ink/40 px-2 py-2 text-sm text-text">
              {(['auto', 'sql', 'gql'] as const).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <button onClick={ask} disabled={busy !== null || !question.trim()}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:brightness-110 disabled:opacity-50">
              {busy === 'ask' ? 'Asking...' : 'Ask'}
            </button>
          </div>
          {askResult && (
            <div className="rounded-lg border border-border bg-ink/40 p-3 text-xs">
              {askResult.status === 'abstained' ? (
                <p className="text-amber">Abstained: {askResult.reason}</p>
              ) : (
                <>
                  <p className="text-text">{askResult.answer}</p>
                  <p className="mt-2 text-muted">Mode: {askResult.mode} · References: {askResult.references?.join(', ')}</p>
                  {askResult.query && <pre className="scrollbar-thin mt-2 max-h-40 overflow-auto rounded-md bg-ink/60 p-2 text-accent-2">{askResult.query}</pre>}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ModelPicker({ label, help, value, onChange, options, disabled }: {
  label: string; help: string; value: string; onChange: (v: string) => void
  options: { id: string; label: string; validated: boolean; notes: string }[]; disabled?: boolean
}) {
  const selected = options.find((o) => o.id === value)
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-muted">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}
        className="rounded-md border border-border bg-ink/40 px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent/60 disabled:opacity-60">
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.label}{o.validated ? ' ✓ validated' : ''}</option>
        ))}
      </select>
      <p className="text-xs text-muted">{help}</p>
      {selected && <p className="text-xs text-muted/80">{selected.notes}</p>}
    </div>
  )
}
