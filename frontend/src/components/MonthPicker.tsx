import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { currentMonth, money, monthLabel, shiftMonth, todayIso } from '../lib/format'

/** Month title that opens a calendar, plus previous/next month arrows. */
export function MonthNav({
  eyebrow,
  month,
  onChange,
  day = null,
  onDay,
  title,
  children,
}: {
  eyebrow: string
  /** Shown instead of the month (e.g. "Year to date"); also hides the month arrows. */
  title?: string
  month: string
  onChange: (month: string) => void
  day?: string | null
  onDay: (day: string) => void
  children?: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div ref={ref} className="relative">
        <p className="text-muted text-sm font-medium">{eyebrow}</p>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-haspopup="dialog"
          className="-mx-2 flex items-center gap-2 rounded-xl px-2 py-0.5 transition hover:bg-[var(--border)]"
        >
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">{title ?? monthLabel(month)}</h1>
          <ChevronDown size={20} className={clsx('text-muted transition', open && 'rotate-180')} />
        </button>
        <AnimatePresence>
          {open && (
            <Calendar
              key="cal"
              month={month}
              day={day}
              onMonth={onChange}
              onDay={(d) => {
                onDay(d)
                setOpen(false)
              }}
            />
          )}
        </AnimatePresence>
      </div>
      <div className="flex items-center gap-2">
        {!title && (
        <div className="card flex items-center gap-1 !rounded-xl p-1">
          <button
            aria-label="Previous month"
            onClick={() => onChange(shiftMonth(month, -1))}
            className="rounded-lg p-2 transition hover:bg-[var(--border)]"
          >
            <ChevronLeft size={18} />
          </button>
          <button
            aria-label="Next month"
            onClick={() => onChange(shiftMonth(month, 1))}
            disabled={month >= currentMonth()}
            className="rounded-lg p-2 transition hover:bg-[var(--border)] disabled:opacity-30"
          >
            <ChevronRight size={18} />
          </button>
        </div>
        )}
        {children}
      </div>
    </header>
  )
}

type View = 'days' | 'months' | 'years'

const navBtn = 'rounded-md p-1 transition hover:bg-[var(--border)] disabled:opacity-30'
const cellBase = 'relative rounded-md text-[13px] transition disabled:opacity-30'

/**
 * A standard date picker: days for the current month; click the title to zoom out to months,
 * then to years. Picking a month updates the page right away; picking a day narrows to that day.
 */
function Calendar({
  month,
  day,
  onMonth,
  onDay,
}: {
  month: string
  day: string | null
  onMonth: (month: string) => void
  onDay: (day: string) => void
}) {
  const today = currentMonth()
  const thisYear = Number(today.slice(0, 4))
  const [view, setView] = useState<View>('days')
  const [year, setYear] = useState(Number(month.slice(0, 4)))
  const [decadeEnd, setDecadeEnd] = useState(thisYear)

  const title =
    view === 'days' ? monthLabel(month) : view === 'months' ? String(year) : `${decadeEnd - 11} – ${decadeEnd}`
  const prev = () =>
    view === 'days' ? onMonth(shiftMonth(month, -1)) : view === 'months' ? setYear(year - 1) : setDecadeEnd(decadeEnd - 12)
  const next = () =>
    view === 'days' ? onMonth(shiftMonth(month, 1)) : view === 'months' ? setYear(year + 1) : setDecadeEnd(decadeEnd + 12)
  const atEnd =
    view === 'days' ? month >= today : view === 'months' ? year >= thisYear : decadeEnd >= thisYear

  return (
    <motion.div
      role="dialog"
      aria-label="Choose a date"
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -6, scale: 0.98 }}
      transition={{ duration: 0.15 }}
      className="card absolute top-full left-0 z-40 mt-2 w-[min(16.5rem,calc(100vw-2rem))] p-2.5 shadow-lg"
    >
      <div className="mb-1 flex items-center justify-between">
        <button aria-label="Previous" onClick={prev} className={navBtn}>
          <ChevronLeft size={14} />
        </button>
        <button
          onClick={() => {
            if (view === 'days') {
              setYear(Number(month.slice(0, 4)))
              setView('months')
            } else if (view === 'months') {
              setDecadeEnd(Math.min(thisYear, year + 5))
              setView('years')
            }
          }}
          disabled={view === 'years'}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[13px] font-semibold transition hover:bg-[var(--border)] disabled:hover:bg-transparent"
        >
          {title}
          {view !== 'years' && <ChevronDown size={14} className="text-muted" />}
        </button>
        <button aria-label="Next" onClick={next} disabled={atEnd} className={navBtn}>
          <ChevronRight size={14} />
        </button>
      </div>

      {view === 'days' && <DayGrid month={month} day={day} onDay={onDay} />}
      {view === 'months' && (
        <MonthGrid
          year={year}
          month={month}
          onPick={(m) => {
            onMonth(m)
            setView('days')
          }}
        />
      )}
      {view === 'years' && (
        <div className="grid grid-cols-3 gap-1">
          {Array.from({ length: 12 }, (_, i) => decadeEnd - 11 + i).map((y) => (
            <button
              key={y}
              disabled={y > thisYear}
              onClick={() => {
                setYear(y)
                setView('months')
              }}
              className={clsx(
                cellBase,
                'py-2 font-medium',
                y === Number(month.slice(0, 4))
                  ? 'bg-brand-600 text-white'
                  : 'hover:bg-[var(--border)]',
              )}
            >
              {y}
            </button>
          ))}
        </div>
      )}

      <div className="mt-1.5 flex justify-between border-t border-[var(--border)] pt-1.5 text-xs">
        <button
          onClick={() => {
            onMonth(today)
            setView('days')
          }}
          className="rounded-lg px-2 py-1 font-medium text-[var(--brand)] transition hover:bg-[var(--border)]"
        >
          This month
        </button>
        {view !== 'days' && (
          <button onClick={() => setView('days')} className="text-muted rounded-lg px-2 py-1 transition hover:bg-[var(--border)]">
            Back to days
          </button>
        )}
      </div>
    </motion.div>
  )
}

function DayGrid({ month, day, onDay }: { month: string; day: string | null; onDay: (day: string) => void }) {
  const { data } = useQuery({ queryKey: ['summary', month], queryFn: () => api.summary(month) })
  const spent = new Map(data?.by_day.map((d) => [d.day.slice(0, 10), Number(d.spent)]) ?? [])
  const max = Math.max(1, ...spent.values())
  const [y, m] = month.split('-').map(Number)
  const lead = (new Date(y, m - 1, 1).getDay() + 6) % 7 // weeks start on Monday
  const days = new Date(y, m, 0).getDate()
  const todayStr = todayIso()
  const weekdays = Array.from({ length: 7 }, (_, i) =>
    new Date(2024, 0, 1 + i).toLocaleDateString(undefined, { weekday: 'narrow' }),
  )

  return (
    <div>
      <div className="text-muted grid grid-cols-7 text-center text-[11px] font-medium">
        {weekdays.map((w, i) => (
          <span key={i} className="py-1">
            {w}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-0.5">
        {Array.from({ length: lead }, (_, i) => (
          <span key={`pad${i}`} />
        ))}
        {Array.from({ length: days }, (_, i) => {
          const iso = `${month}-${String(i + 1).padStart(2, '0')}`
          const amount = spent.get(iso) ?? 0
          const selected = iso === day
          return (
            <button
              key={iso}
              disabled={iso > todayStr}
              onClick={() => onDay(iso)}
              title={amount ? money(amount, data!.home_currency) : undefined}
              className={clsx(
                cellBase,
                'flex h-8 flex-col items-center justify-center leading-none',
                selected ? 'bg-brand-600 font-semibold text-white' : 'hover:bg-[var(--border)]',
                iso === todayStr && !selected && 'font-semibold text-[var(--brand)] ring-1 ring-brand-300 ring-inset',
              )}
            >
              {i + 1}
              {/* Dot size hints at how much was spent that day. */}
              <span
                className={clsx('mt-0.5 rounded-full', selected ? 'bg-white' : 'bg-brand-400')}
                style={{
                  width: amount ? 3 + (amount / max) * 2 : 0,
                  height: amount ? 3 + (amount / max) * 2 : 0,
                }}
              />
            </button>
          )
        })}
      </div>
      {data && (
        <p className="text-muted tabular mt-1.5 text-center text-[11px]">
          {money(data.total, data.home_currency)} across {data.count} expenses
        </p>
      )}
    </div>
  )
}

function MonthGrid({ year, month, onPick }: { year: number; month: string; onPick: (month: string) => void }) {
  const today = currentMonth()
  const { data } = useQuery({
    queryKey: ['summary', 'months', year],
    queryFn: () => api.yearOverview(year),
  })
  const max = Math.max(1, ...(data?.months.map((m) => Number(m.total)) ?? [0]))
  return (
    <div className="grid grid-cols-3 gap-1">
      {Array.from({ length: 12 }, (_, i) => {
        const key = `${year}-${String(i + 1).padStart(2, '0')}`
        const total = Number(data?.months[i]?.total ?? 0)
        const selected = key === month
        const future = key > today
        return (
          <button
            key={key}
            disabled={future}
            onClick={() => onPick(key)}
            className={clsx(
              cellBase,
              'overflow-hidden px-2 py-1.5 text-left',
              selected ? 'bg-brand-600 text-white' : 'hover:bg-[var(--border)]',
            )}
          >
            {!selected && total > 0 && (
              <span
                className="absolute inset-x-0 bottom-0 bg-brand-100 dark:bg-brand-700/30"
                style={{ height: `${Math.max(8, (total / max) * 100)}%` }}
              />
            )}
            <span className="relative block font-medium">
              {new Date(year, i, 1).toLocaleDateString(undefined, { month: 'short' })}
            </span>
            <span className={clsx('tabular relative block truncate text-[11px]', selected ? 'text-brand-100' : 'text-muted')}>
              {future ? ' ' : total > 0 ? money(total, data!.home_currency, true) : '—'}
            </span>
          </button>
        )
      })}
    </div>
  )
}
