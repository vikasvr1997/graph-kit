import { DataSet } from 'vis-data'
import { Network, type Edge as VisEdge, type Node as VisNode } from 'vis-network'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { GraphResponse } from '../types'

interface Props {
  name: string
  refreshKey: number
}

export function GraphTab({ name, refreshKey }: Props) {
  const [view, setView] = useState<'Schema' | 'Data preview'>('Schema')
  const [per, setPer] = useState(8)
  const [graph, setGraph] = useState<GraphResponse | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [notesOpen, setNotesOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<Record<string, unknown> | null>(null)
  const container = useRef<HTMLDivElement>(null)
  const networkRef = useRef<Network | null>(null)

  useEffect(() => {
    api.state(name).then((s) => setNotes(s.notes ?? [])).catch(() => {})
  }, [name, refreshKey])

  useEffect(() => {
    let active = true
    api.graph(name, view === 'Data preview' ? 'data' : 'schema', per)
      .then((g) => { if (active) { setGraph(g); setError(null) } })
      .catch((e) => active && setError(e instanceof ApiError ? e.message : 'Failed to load graph.'))
    return () => { active = false }
  }, [name, view, per, refreshKey])

  useEffect(() => {
    if (!container.current || !graph) return
    const big = view === 'Schema'
    const nodeInfo = new Map(graph.nodes.map((n) => [n.id, n.info]))
    const edgeInfo = new Map(graph.edges.map((e, i) => [e.id ?? `e${i}`, (e as { info?: Record<string, unknown> }).info]))

    const nodes = new DataSet<VisNode>(graph.nodes.map((n) => ({
      id: n.id, label: n.label, shape: 'dot', size: big ? 22 : 12,
      color: { background: n.color, border: n.dashed ? '#f5b946' : n.color, highlight: { background: n.color, border: '#e7eaf2' } },
      borderWidth: n.dashed ? 3 : 1,
      shapeProperties: { borderDashes: n.dashed ? [4, 3] : false },
      font: { color: '#e7eaf2', size: 13 },
    })))
    const edges = new DataSet<VisEdge>(graph.edges.map((e, i) => ({
      id: e.id ?? `e${i}`, from: e.from, to: e.to, label: e.label,
      arrows: { to: { enabled: true, scaleFactor: 0.6 }, from: { enabled: !!e.arrows2, scaleFactor: 0.6 } },
      dashes: !!e.dashed,
      color: { color: e.dashed ? '#f5b946' : '#5b6477', highlight: '#e7eaf2' },
      font: { color: '#e7eaf2', size: 10, strokeWidth: 3, strokeColor: '#121722', align: 'middle' },
      smooth: { enabled: true, type: 'dynamic', roundness: 0.5 },
    })))
    const net = new Network(container.current, { nodes, edges }, {
      physics: { solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -60, springLength: big ? 170 : 90 }, stabilization: { iterations: 200 } },
      interaction: { hover: true, tooltipDelay: 150 },
    })
    net.on('click', (p) => {
      if (p.nodes.length) setInfo(nodeInfo.get(p.nodes[0]) ?? null)
      else if (p.edges.length) setInfo(edgeInfo.get(p.edges[0]) ?? null)
      else setInfo(null)
    })
    networkRef.current = net
    return () => net.destroy()
  }, [graph, view])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-1.5 rounded-lg border border-border p-1">
          {(['Schema', 'Data preview'] as const).map((v) => (
            <button key={v} onClick={() => setView(v)}
              className={`rounded-md px-3 py-1 text-xs transition ${view === v ? 'bg-accent text-white' : 'text-muted hover:text-text'}`}>
              {v}
            </button>
          ))}
        </div>
        {view === 'Data preview' && (
          <label className="flex items-center gap-2 text-xs text-muted">
            Rows per node type: <span className="text-text">{per}</span>
            <input type="range" min={3} max={50} value={per} onChange={(e) => setPer(Number(e.target.value))}
              className="accent-[color:var(--color-accent)]" />
          </label>
        )}
      </div>

      {error && <div className="card border-red/40 p-3 text-sm text-red">{error}</div>}

      <div className="card flex h-[600px] overflow-hidden">
        <div ref={container} className="min-w-0 flex-1" />
        <div className="w-64 shrink-0 overflow-y-auto border-l border-border p-4 scrollbar-thin">
          <h4 className="mb-2 text-sm font-medium text-text">Details</h4>
          {info ? (
            <table className="w-full text-xs">
              <tbody>
                {Object.entries(info).filter(([, v]) => v !== null && v !== '').map(([k, v]) => (
                  <tr key={k} className="border-b border-border/60 align-top">
                    <td className="py-1 pr-2 text-muted">{k}</td>
                    <td className="py-1 break-words text-text">{String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-xs text-muted">Click a node or edge to see its properties. Drag to move, scroll to zoom.</p>
          )}
        </div>
      </div>

      {graph && (
        <div className="flex flex-wrap gap-4 text-xs text-muted">
          {Object.entries(graph.colors).map(([label, color]) => (
            <span key={label} className="flex items-center gap-1.5">
              <i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
              {label}
            </span>
          ))}
          <span>Orange dashes: new or low-confidence, needs review</span>
        </div>
      )}

      {notes.length > 0 && (
        <details open={notesOpen} onToggle={(e) => setNotesOpen(e.currentTarget.open)} className="card p-4">
          <summary className="cursor-pointer text-sm text-muted">Scan notes ({notes.length})</summary>
          <ul className="mt-2 list-disc pl-5 text-xs text-muted">
            {notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </details>
      )}
    </div>
  )
}
