import { useSearchParams } from 'react-router-dom'

import { currentMonth } from './format'

/** The selected month lives in the URL (?month=2026-08), so it survives page switches and reloads. */
export function useMonth() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('month')
  const month = raw && /^\d{4}-\d{2}$/.test(raw) && raw <= currentMonth() ? raw : currentMonth()
  const setMonth = (next: string) =>
    setParams(
      (p) => {
        if (next === currentMonth()) p.delete('month')
        else p.set('month', next)
        p.delete('day') // a picked day belongs to the old month
        p.delete('period') // picking a month means looking at that month
        return p
      },
      { replace: true },
    )
  return [month, setMonth] as const
}

/** Optional single day (?day=2026-08-14) within the selected month. */
export function useDay() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('day')
  const day = raw && /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : null
  const setDay = (next: string | null) =>
    setParams(
      (p) => {
        if (next) {
          p.set('day', next)
          if (next.slice(0, 7) === currentMonth()) p.delete('month')
          else p.set('month', next.slice(0, 7))
          p.delete('period')
        } else p.delete('day')
        return p
      },
      { replace: true },
    )
  return [day, setDay] as const
}

export const PERIODS = [
  { key: 'month', short: 'Month', long: 'This month' },
  { key: '3m', short: '3M', long: 'Last 3 months' },
  { key: 'ytd', short: 'YTD', long: 'Year to date' },
  { key: '1y', short: '1Y', long: 'Last 12 months' },
  { key: 'all', short: 'All', long: 'All time' },
] as const
export type Period = (typeof PERIODS)[number]['key']

/** Month (the picked one) or a longer period ending today (?period=ytd). */
export function usePeriod() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('period')
  const period: Period = PERIODS.some((p) => p.key === raw) ? (raw as Period) : 'month'
  const setPeriod = (next: Period) =>
    setParams(
      (p) => {
        p.delete('day')
        if (next === 'month') p.delete('period')
        else {
          p.set('period', next)
          p.delete('month') // longer periods always end today
        }
        return p
      },
      { replace: true },
    )
  return [period, setPeriod] as const
}
