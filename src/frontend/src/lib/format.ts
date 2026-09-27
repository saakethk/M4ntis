// Display formatting shared across pages.

export function money(value: number): string {
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export function signedMoney(value: number): string {
  return `${value > 0 ? '+' : value < 0 ? '-' : ''}${money(Math.abs(value))}`
}

export function pct(value: number): string {
  return `${value.toFixed(2)}%`
}

export function signedPct(value: number): string {
  return `${value > 0 ? '+' : value < 0 ? '-' : ''}${pct(Math.abs(value))}`
}

/** "Mar 4, 2026, 3:15 PM", or the raw text when it is not a date. */
export function dateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** "now", "5m", "3h", "2d", then a short date. */
export function relativeTime(iso: string, now = Date.now()): string {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, Math.round((now - then) / 1000))
  if (seconds < 60) return 'now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d`
  return new Date(then).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** "ada.lovelace@x.com" -> "Ada Lovelace". */
export function displayName(email: string): string {
  const words = (email.split('@')[0] ?? '').split(/[._+-]+/).filter(Boolean)
  if (words.length === 0) return email
  return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
}

export function handleOf(email: string): string {
  return `@${email.split('@')[0]?.trim() || 'user'}`
}

export function initials(email: string): string {
  const letters = displayName(email)
    .split(' ')
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join('')
  return letters || 'M'
}
