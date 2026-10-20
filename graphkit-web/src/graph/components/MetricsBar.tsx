import type { State } from '../types'

export function MetricsBar({ state }: { state: State }) {
  const items = [
    { label: 'Nodes', value: state.nodes ?? 0 },
    { label: 'Edges', value: state.edges ?? 0 },
    { label: 'Waiting for review', value: state.waiting ?? 0, warn: (state.waiting ?? 0) > 0 },
    { label: 'Problems', value: state.problems?.length ?? 0, bad: (state.problems?.length ?? 0) > 0 },
  ]
  return (
    <div className="grid grid-cols-4 gap-4">
      {items.map((it) => (
        <div key={it.label} className="card p-4">
          <div className="text-xs text-muted">{it.label}</div>
          <div
            className={`mt-1 text-2xl font-semibold ${
              'bad' in it && it.bad ? 'text-red' : 'warn' in it && it.warn ? 'text-amber' : 'text-text'
            }`}
          >
            {it.value}
          </div>
        </div>
      ))}
    </div>
  )
}
