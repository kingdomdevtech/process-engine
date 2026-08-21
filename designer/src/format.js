/** Shared value formatting, so a duration or a timestamp reads the same everywhere. */

const UNITS = [
  { limit: 60, divisor: 1, suffix: 's' },
  { limit: 3600, divisor: 60, suffix: 'm' },
  { limit: 86400, divisor: 3600, suffix: 'h' },
  { limit: 2592000, divisor: 86400, suffix: 'd' },
]

/** "just now" / "4m ago" — compact enough for a table cell. */
export function relativeTime(iso) {
  if (!iso) return '—'
  const seconds = Math.round((Date.now() - new Date(iso)) / 1000)
  if (Number.isNaN(seconds)) return '—'
  if (seconds < 45) return 'just now'
  const unit = UNITS.find((entry) => seconds < entry.limit) ?? { divisor: 2592000, suffix: 'mo' }
  return `${Math.floor(seconds / unit.divisor)}${unit.suffix} ago`
}

/** Full timestamp for tooltips and detail panes, where precision matters. */
export function absoluteTime(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

/** Sub-second work is common, so keep one decimal below 10ms. */
export function duration(ms) {
  if (ms == null) return ''
  if (ms < 10) return `${ms.toFixed(1)}ms`
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const minutes = Math.floor(ms / 60000)
  return `${minutes}m ${Math.round((ms % 60000) / 1000)}s`
}

export function durationBetween(startIso, endIso) {
  if (!startIso || !endIso) return ''
  return duration(new Date(endIso) - new Date(startIso))
}

/** Short id for display — full ids are kept in title attributes. */
export function shortId(id) {
  return id ? id.slice(0, 8) : ''
}
