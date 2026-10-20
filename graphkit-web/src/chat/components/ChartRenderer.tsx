import { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { ChartSpec } from '../types'
import { resolvedScheme, subscribeScheme } from '../../theme'

// Fixed-order categorical palette from the dataviz skill's validated default (references/palette.md).
// Never cycled/reassigned by rank - slot N always means "the Nth series", folding extras into "Other".
const CATEGORICAL = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
}
const SEQUENTIAL = { light: '#2a78d6', dark: '#3987e5' }
const GRID = { light: '#e1e0d9', dark: '#2c2c2a' }
const INK = { light: '#52514e', dark: '#c3c2b7' }
const MAX_SERIES = 8

function useScheme() {
  const [scheme, setScheme] = useState(resolvedScheme())
  useEffect(() => subscribeScheme(setScheme), [])
  return scheme
}

function groupBySeries(data: Record<string, unknown>[], x: string, y: string, series: string) {
  const keys = [...new Set(data.map((r) => String(r[series])))]
  const kept = keys.slice(0, MAX_SERIES)
  const byX = new Map<string, Record<string, unknown>>()
  for (const row of data) {
    const xv = String(row[x])
    const seriesKey = kept.includes(String(row[series])) ? String(row[series]) : 'Other'
    const entry = byX.get(xv) ?? { [x]: row[x] }
    entry[seriesKey] = row[y]
    byX.set(xv, entry)
  }
  const seriesKeys = kept.includes('Other') ? kept : [...kept, ...(byX.size && [...byX.values()].some((r) => 'Other' in r) ? ['Other'] : [])]
  return { rows: [...byX.values()], seriesKeys }
}

export function ChartRenderer({ spec }: { spec: ChartSpec }) {
  const scheme = useScheme()
  const colors = CATEGORICAL[scheme]
  const grid = GRID[scheme]
  const ink = INK[scheme]

  if (spec.kind === 'kpi') {
    const value = spec.y && spec.data[0] ? spec.data[0][spec.y] : spec.data.length
    return (
      <div className="rounded-xl border border-border bg-ink/30 p-5">
        <p className="text-xs text-muted">{spec.title}</p>
        <p className="mt-1 text-3xl font-semibold text-text" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {String(value)}
        </p>
      </div>
    )
  }

  if (spec.kind === 'table') {
    const cols = spec.data[0] ? Object.keys(spec.data[0]) : []
    return (
      <div className="scrollbar-thin max-h-80 overflow-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-panel-2 text-muted">
            <tr>{cols.map((c) => <th key={c} className="px-3 py-2 text-left font-medium">{c}</th>)}</tr>
          </thead>
          <tbody>
            {spec.data.slice(0, 200).map((row, i) => (
              <tr key={i} className="border-t border-border/60">
                {cols.map((c) => <td key={c} className="px-3 py-1.5 text-text">{String(row[c])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  const title = <p className="mb-2 text-sm font-medium text-text">{spec.title}</p>

  if (spec.kind === 'pie' && spec.x && spec.y) {
    const data = spec.data.slice(0, MAX_SERIES)
    const direct = data.length <= 4
    return (
      <div className="rounded-xl border border-border bg-ink/20 p-4">
        {title}
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={data} dataKey={spec.y} nameKey={spec.x} outerRadius={90}
              label={direct ? ({ name }) => name : false} stroke="none">
              {data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
            </Pie>
            {data.length >= 2 && <Legend wrapperStyle={{ color: ink, fontSize: 12 }} />}
            <Tooltip contentStyle={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', fontSize: 12 }} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    )
  }

  if (!spec.x || !spec.y) {
    return <p className="text-xs text-muted">Not enough fields to chart this.</p>
  }

  const grouped = spec.series ? groupBySeries(spec.data, spec.x, spec.y, spec.series) : null
  const rows = grouped?.rows ?? spec.data
  const seriesKeys = grouped?.seriesKeys ?? [spec.y]

  const Chart = spec.kind === 'line' ? LineChart : spec.kind === 'scatter' ? ScatterChart : BarChart

  return (
    <div className="rounded-xl border border-border bg-ink/20 p-4">
      {title}
      <ResponsiveContainer width="100%" height={260}>
        <Chart data={rows} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
          <CartesianGrid stroke={grid} vertical={false} />
          <XAxis dataKey={spec.x} stroke={ink} fontSize={12} tickLine={false} />
          <YAxis stroke={ink} fontSize={12} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', fontSize: 12 }} />
          {seriesKeys.length >= 2 && <Legend wrapperStyle={{ color: ink, fontSize: 12 }} />}
          {seriesKeys.map((key, i) => {
            const color = seriesKeys.length === 1 ? SEQUENTIAL[scheme] : colors[i % colors.length]
            if (spec.kind === 'line') {
              return <Line key={key} type="monotone" dataKey={key} stroke={color} strokeWidth={2} dot={{ r: 3 }} />
            }
            if (spec.kind === 'scatter') {
              return <Scatter key={key} dataKey={key} fill={color} />
            }
            return <Bar key={key} dataKey={key} fill={color} radius={[4, 4, 0, 0]} maxBarSize={36} />
          })}
        </Chart>
      </ResponsiveContainer>
    </div>
  )
}
