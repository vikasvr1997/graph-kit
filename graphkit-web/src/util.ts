export const split = (s: string | null | undefined): string[] =>
  (s ?? '').split(',').map((x) => x.trim()).filter(Boolean)

export const join = (xs: string[] | null | undefined): string => (xs ?? []).join(', ')

export const statusColor: Record<string, string> = {
  proposed: 'bg-amber/15 text-amber border-amber/30',
  new: 'bg-blue/15 text-blue border-blue/30',
  approved: 'bg-green/15 text-green border-green/30',
}
