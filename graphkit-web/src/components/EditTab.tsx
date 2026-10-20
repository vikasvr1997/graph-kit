import { AgGridReact } from 'ag-grid-react'
import type { ColDef } from 'ag-grid-community'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import { gkGridTheme } from '../gridTheme'
import type { DraftResponse, GkEdge, GkNode, Status } from '../types'
import { join, split } from '../util'

const STATUSES: Status[] = ['proposed', 'new', 'approved']

interface NodeRow {
  label: string; table: string; key: string; properties: string; description: string; status: Status
}
interface EdgeRow {
  label: string; table: string; key: string; source: string; source_key: string; dest: string
  dest_key: string; two_way: boolean; reverse_label: string; confidence: number; why: string; status: Status
}

const nodeToRow = (n: GkNode): NodeRow => ({
  label: n.label, table: n.table, key: join(n.key),
  properties: n.properties === null ? '' : join(n.properties), description: n.description, status: n.status,
})
const edgeToRow = (e: GkEdge): EdgeRow => ({
  label: e.label, table: e.table, key: join(e.key), source: e.source, source_key: join(e.source_key),
  dest: e.dest, dest_key: join(e.dest_key), two_way: e.bidirectional, reverse_label: e.reverse_label,
  confidence: e.confidence, why: e.reason, status: e.status,
})

interface Props {
  name: string
  refreshKey: number
  onSaved: (problems: string[]) => void
}

export function EditTab({ name, refreshKey, onSaved }: Props) {
  const [draft, setDraft] = useState<DraftResponse | null>(null)
  const [nodeRows, setNodeRows] = useState<NodeRow[]>([])
  const [edgeRows, setEdgeRows] = useState<EdgeRow[]>([])
  const [flip, setFlip] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const nodeGrid = useRef<AgGridReact<NodeRow>>(null)
  const edgeGrid = useRef<AgGridReact<EdgeRow>>(null)

  useEffect(() => {
    let active = true
    api.draft(name).then((d) => {
      if (!active) return
      setDraft(d)
      setNodeRows(d.nodes.map(nodeToRow))
      setEdgeRows(d.edges.map(edgeToRow))
      setFlip(new Set())
      setError(null)
    }).catch((e) => active && setError(e instanceof ApiError ? e.message : 'Failed to load draft.'))
    return () => { active = false }
  }, [name, refreshKey])

  const tableNames = draft?.table_names ?? []
  const labelOpts = useMemo(() => Array.from(new Set([...nodeRows.map((r) => r.label).filter(Boolean)])), [nodeRows])

  const nodeCols = useMemo<ColDef<NodeRow>[]>(() => [
    { field: 'label', headerName: 'label', editable: true },
    { field: 'table', headerName: 'table', editable: true, cellEditor: 'agSelectCellEditor', cellEditorParams: { values: tableNames } },
    { field: 'key', headerName: 'key', editable: true },
    { field: 'properties', headerName: 'properties', editable: true, flex: 1.4, headerTooltip: 'Blank = all columns' },
    { field: 'description', headerName: 'description', editable: true, flex: 1.6 },
    { field: 'status', headerName: 'status', editable: true, cellEditor: 'agSelectCellEditor', cellEditorParams: { values: STATUSES } },
  ], [tableNames])

  const edgeCols = useMemo<ColDef<EdgeRow>[]>(() => [
    { field: 'label', headerName: 'label', editable: true },
    { field: 'table', headerName: 'table', editable: true, cellEditor: 'agSelectCellEditor', cellEditorParams: { values: tableNames } },
    { field: 'key', headerName: 'key', editable: true },
    { field: 'source', headerName: 'source', editable: true, cellEditor: 'agSelectCellEditor', cellEditorParams: { values: labelOpts } },
    { field: 'source_key', headerName: 'source_key', editable: true },
    { field: 'dest', headerName: 'dest', editable: true, cellEditor: 'agSelectCellEditor', cellEditorParams: { values: labelOpts } },
    { field: 'dest_key', headerName: 'dest_key', editable: true },
    { field: 'two_way', headerName: 'two_way', editable: true, cellEditor: 'agCheckboxCellEditor', cellRenderer: 'agCheckboxCellRenderer', headerTooltip: 'Also add a reverse edge' },
    { field: 'reverse_label', headerName: 'reverse_label', editable: true },
    { field: 'confidence', headerName: 'confidence', editable: false, valueFormatter: (p) => (p.value != null ? Number(p.value).toFixed(2) : '') },
    { field: 'why', headerName: 'why', editable: false, flex: 2 },
    { field: 'status', headerName: 'status', editable: true, cellEditor: 'agSelectCellEditor', cellEditorParams: { values: STATUSES } },
  ], [tableNames, labelOpts])

  const addNodeRow = () => setNodeRows((rs) => [...rs, { label: '', table: tableNames[0] ?? '', key: '', properties: '', description: '', status: 'proposed' }])
  const addEdgeRow = () => setEdgeRows((rs) => [...rs, { label: '', table: tableNames[0] ?? '', key: '', source: labelOpts[0] ?? '', source_key: '', dest: labelOpts[0] ?? '', dest_key: '', two_way: false, reverse_label: '', confidence: 1, why: 'added in editor', status: 'proposed' }])

  const deleteSelectedNodes = () => {
    const selected = new Set(nodeGrid.current?.api.getSelectedRows())
    setNodeRows((rs) => rs.filter((r) => !selected.has(r)))
  }
  const deleteSelectedEdges = () => {
    const selected = new Set(edgeGrid.current?.api.getSelectedRows())
    setEdgeRows((rs) => rs.filter((r) => !selected.has(r)))
  }

  const save = async () => {
    if (!draft) return
    setSaving(true)
    setError(null)
    try {
      const nodes: GkNode[] = nodeRows.filter((r) => r.label.trim()).map((r) => ({
        label: r.label, table: r.table, key: split(r.key),
        properties: split(r.properties).length ? split(r.properties) : null,
        description: r.description, status: r.status,
      }))
      const edges: GkEdge[] = edgeRows.filter((r) => r.label.trim()).map((r) => {
        let { source, source_key, dest, dest_key } = r
        if (flip.has(r.label)) {
          [source, dest] = [dest, source]
          ;[source_key, dest_key] = [dest_key, source_key]
        }
        return {
          label: r.label, table: r.table, key: split(r.key), source, source_key: split(source_key),
          dest, dest_key: split(dest_key), bidirectional: r.two_way, reverse_label: r.reverse_label,
          properties: null, confidence: r.confidence, reason: r.why, status: r.status,
        }
      })
      const res = await api.saveDraft(name, nodes, edges)
      onSaved(res.problems)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  const toggleFlip = (label: string) => setFlip((f) => {
    const next = new Set(f)
    next.has(label) ? next.delete(label) : next.add(label)
    return next
  })

  if (!draft) return error ? <div className="card border-red/40 p-3 text-sm text-red">{error}</div> : null

  return (
    <div className="flex flex-col gap-6">
      <p className="text-xs text-muted">
        Add a row to create, edit a cell to update, or select rows and press "Delete selected" to remove.
        Keys are comma-separated column names. Nothing is applied until you confirm.
      </p>

      <Section title="Nodes" onAdd={addNodeRow} onDelete={deleteSelectedNodes}>
        <AgGridReact<NodeRow> ref={nodeGrid} theme={gkGridTheme} rowData={nodeRows} columnDefs={nodeCols}
          rowSelection={{ mode: 'multiRow' }}
          onCellValueChanged={(e) => setNodeRows((rows) => rows.map((r, i) => (i === e.rowIndex ? { ...e.data } : r)))}
          domLayout="autoHeight" />
      </Section>

      <Section title="Edges" onAdd={addEdgeRow} onDelete={deleteSelectedEdges}>
        <AgGridReact<EdgeRow> ref={edgeGrid} theme={gkGridTheme} rowData={edgeRows} columnDefs={edgeCols}
          rowSelection={{ mode: 'multiRow' }}
          onCellValueChanged={(e) => setEdgeRows((rows) => rows.map((r, i) => (i === e.rowIndex ? { ...e.data } : r)))}
          domLayout="autoHeight" />
      </Section>

      <div className="card p-4">
        <span className="text-xs text-muted">Flip direction of</span>
        <div className="mt-2 flex flex-wrap gap-2">
          {edgeRows.map((r) => r.label).filter(Boolean).map((label) => (
            <button key={label} onClick={() => toggleFlip(label)}
              className={`rounded-full border px-3 py-1 text-xs transition ${
                flip.has(label) ? 'border-accent bg-accent/15 text-text' : 'border-border text-muted hover:text-text'
              }`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="card border-red/40 p-3 text-sm text-red">{error}</div>}

      <button onClick={save} disabled={saving}
        className="self-start rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white shadow-[0_8px_24px_-8px_var(--color-accent)] hover:brightness-110 disabled:opacity-50">
        {saving ? 'Saving...' : 'Save draft'}
      </button>
    </div>
  )
}

function Section({ title, onAdd, onDelete, children }: { title: string; onAdd: () => void; onDelete: () => void; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-text">{title}</h3>
        <div className="flex gap-2">
          <button onClick={onAdd} className="rounded-md border border-border px-2.5 py-1 text-xs text-muted hover:border-accent/40 hover:text-text">+ Add row</button>
          <button onClick={onDelete} className="rounded-md border border-border px-2.5 py-1 text-xs text-muted hover:border-red/40 hover:text-red">Delete selected</button>
        </div>
      </div>
      <div className="card overflow-hidden">{children}</div>
    </div>
  )
}
