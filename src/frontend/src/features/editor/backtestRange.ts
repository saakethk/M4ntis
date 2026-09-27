/** Helpers for picking backtest calendar windows against server-reported trading days. */

export type BacktestRangeChoice = { start: string; end: string } | null

export function snapToAvailableDay(iso: string, days: string[]): { date: string; hint: string | null } {
  if (days.length === 0) return { date: iso, hint: null }
  if (days.includes(iso)) return { date: iso, hint: null }
  const target = Date.parse(`${iso}T12:00:00Z`)
  let best = days[0]
  let bestDist = Math.abs(Date.parse(`${best}T12:00:00Z`) - target)
  for (const day of days) {
    const dist = Math.abs(Date.parse(`${day}T12:00:00Z`) - target)
    if (dist < bestDist) {
      best = day
      bestDist = dist
    }
  }
  const label = formatShortDate(best)
  const picked = formatShortDate(iso)
  return { date: best, hint: `No data on ${picked}; using ${label}.` }
}

export function isRangeValid(start: string | null, end: string | null, days: string[], useLatest: boolean): boolean {
  if (useLatest) return true
  if (!start || !end || days.length === 0) return false
  if (start > end) return false
  return days.includes(start) && days.includes(end)
}

export function formatShortDate(iso: string): string {
  const date = new Date(`${iso}T12:00:00Z`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatRangeSubtitle(start: string | null, end: string | null): string | null {
  if (!start || !end) return null
  const startDate = new Date(`${start}T12:00:00Z`)
  const endDate = new Date(`${end}T12:00:00Z`)
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return null
  const sameYear = startDate.getUTCFullYear() === endDate.getUTCFullYear()
  const startLabel = startDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric', ...(sameYear ? {} : { year: 'numeric' }) })
  const endLabel = endDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  return `${startLabel} – ${endLabel}`
}
