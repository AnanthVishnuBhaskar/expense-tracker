export function money(amount: string | number | null | undefined, currency: string, compact = false) {
  if (amount === null || amount === undefined || amount === '') return '—'
  const value = typeof amount === 'string' ? Number(amount) : amount
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      notation: compact ? 'compact' : 'standard',
      maximumFractionDigits: compact ? 1 : undefined,
    }).format(value)
  } catch {
    return `${currency} ${value.toFixed(2)}`
  }
}

export function day(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = {}) {
  if (!iso) return '—'
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    ...opts,
  })
}

export function relativeDay(iso: string) {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((today.getTime() - d.getTime()) / 86_400_000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })
}

export function currentMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export function shiftMonth(month: string, delta: number) {
  const [y, m] = month.split('-').map(Number)
  const i = y * 12 + (m - 1) + delta
  return `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`
}

export function monthLabel(month: string) {
  const [y, m] = month.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

export function flag(country: string | null | undefined) {
  if (!country || country.length !== 2) return ''
  return String.fromCodePoint(...[...country.toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0)))
}

export function todayIso() {
  return new Date().toLocaleDateString('en-CA') // YYYY-MM-DD in local time
}
