import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  ChevronRight,
  Info,
  ClipboardCheck,
  Sparkles,
} from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts'
import { toast } from 'sonner'

import { api, type MonthSummary } from '../api'
import { CategoryIcon } from '../components/CategoryIcon'
import { HomeCurrencyPill } from '../components/CurrencyPicker'
import { EmptyState } from '../components/EmptyState'
import { MonthNav } from '../components/MonthPicker'
import { PeriodTabs } from '../components/PeriodTabs'
import { day, monthLabel, money } from '../lib/format'
import { setReviewOpen } from '../lib/review'
import { PERIODS, useMonth, usePeriod } from '../lib/useMonth'

const fade = (i: number) => ({
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
  transition: { delay: i * 0.06, duration: 0.4, ease: [0.22, 1, 0.36, 1] as const },
})

export function Dashboard() {
  const [month, setMonth] = useMonth()
  const [period, setPeriod] = usePeriod()
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({
    queryKey: ['summary', month, period],
    queryFn: () => api.summary(month, period),
  })
  const { data: recent } = useQuery({
    queryKey: ['expenses', { month, period }],
    queryFn: () => api.expenses({ month, period }),
  })
  const periodInfo = PERIODS.find((p) => p.key === period)!

  return (
    <div className="space-y-6">
      <MonthNav
        eyebrow="Spending overview"
        month={month}
        onChange={setMonth}
        onDay={(d) => navigate(`/expenses?month=${d.slice(0, 7)}&day=${d}`)}
        title={period === 'month' ? undefined : periodInfo.long}
      >
        <PeriodTabs value={period} onChange={setPeriod} />
      </MonthNav>

      {data && data.pending_receipts > 0 && (
        <motion.div {...fade(0)}>
          <button
            onClick={() => setReviewOpen(true)}
            className="flex w-full items-center gap-3 rounded-2xl border border-brand-200 bg-brand-50 dark:border-brand-700/50 dark:bg-brand-700/20 px-4 py-3 font-semibold text-brand-600 transition hover:bg-brand-100 dark:hover:bg-brand-700/30 dark:text-brand-300"
          >
            <ClipboardCheck size={18} />
            {data.pending_receipts} receipt{data.pending_receipts > 1 ? 's' : ''} ready for review
            <ChevronRight size={18} className="ml-auto" />
          </button>
        </motion.div>
      )}

      {isLoading || !data ? (
        <Skeleton />
      ) : data.count === 0 ? (
        <EmptyState
          title={period === 'month' ? 'No expenses this month yet' : `No expenses in this period yet`}
          body="Snap a receipt and it will show up here once you confirm it."
        />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-5">
            <motion.section {...fade(1)} className="card relative overflow-hidden p-6 lg:col-span-3">
              <Hero
                data={data}
                label={period === 'month' ? 'Spent this month' : `Spent · ${periodInfo.long.toLowerCase()}`}
                onPickMonth={(m) => setMonth(m)}
              />
            </motion.section>
            <motion.section {...fade(2)} className="card p-6 lg:col-span-2">
              <h2 className="mb-4 font-semibold">Insights</h2>
              <Insights data={data} />
            </motion.section>
          </div>

          <div className="grid gap-4 lg:grid-cols-5">
            <motion.section {...fade(3)} className="card p-6 lg:col-span-3">
              <h2 className="mb-5 font-semibold">By category</h2>
              <Categories data={data} />
            </motion.section>
            <motion.section {...fade(4)} className="card p-6 lg:col-span-2">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="font-semibold">Recent</h2>
                <Link to={period === 'month' ? `/expenses?month=${month}` : `/expenses?period=${period}`} className="text-sm font-semibold text-[var(--brand)]">
                  See all
                </Link>
              </div>
              <ul className="space-y-1">
                {recent?.slice(0, 6).map((e) => (
                  <li key={e.id} className="flex items-center gap-3 rounded-xl py-2">
                    <CategoryIcon
                      icon={data.by_category.find((c) => c.category_id === e.category_id)?.icon}
                      color={data.by_category.find((c) => c.category_id === e.category_id)?.color}
                      size="sm"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-semibold">{e.merchant_name}</div>
                      <div className="text-muted text-xs">{day(e.purchased_on)}</div>
                    </div>
                    <div className="tabular text-right font-semibold">
                      {money(e.total_home ?? e.total, e.total_home ? e.home_currency : e.currency)}
                    </div>
                  </li>
                ))}
              </ul>
            </motion.section>
          </div>
        </>
      )}
    </div>
  )
}

function Hero({
  data,
  label,
  onPickMonth,
}: {
  data: MonthSummary
  label: string
  onPickMonth: (month: string) => void
}) {
  const byMonth = data.bucket === 'month'
  const pointLabel = (d: string) =>
    byMonth ? monthLabel(d.slice(0, 7)) : day(d, { weekday: 'short' })
  const total = Number(data.total)
  const prev = Number(data.previous_total)
  const change = prev ? ((total - prev) / prev) * 100 : null
  const budget = data.budget ? Number(data.budget) : null
  const pct = budget ? Math.min(total / budget, 1) : null
  const chart = data.by_day.map((d) => ({ day: d.day, spent: Number(d.spent) }))

  return (
    <>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-muted text-sm font-medium">{label}</p>
            <HomeCurrencyPill currency={data.home_currency} />
          </div>
          <div className="tabular mt-1 text-4xl font-semibold tracking-tight md:text-[2.75rem]">
            {money(data.total, data.home_currency)}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            {change !== null && (
              <span
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold ${
                  change > 0
                    ? 'bg-bad/12 text-bad'
                    : 'bg-good/12 text-good'
                }`}
              >
                {change > 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                {Math.abs(change).toFixed(0)}% vs {data.period === 'month' ? 'last month' : 'previous period'}
              </span>
            )}
            <span className="text-muted">{data.count} expenses</span>
          </div>
          {data.unconverted.length > 0 && <Unconverted items={data.unconverted} />}
        </div>
        {pct !== null && <Ring pct={pct} label={`of ${money(data.budget, data.home_currency, true)}`} />}
      </div>
      <div className="-mx-2 mt-6 h-32">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={chart}
            // On a long period, clicking a month opens that month.
            onClick={(e) => {
              const d = chart[Number(e?.activeTooltipIndex)]?.day
              if (byMonth && d) onPickMonth(d.slice(0, 7))
            }}
            className={byMonth ? 'cursor-pointer' : undefined}
          >
            <defs>
              <linearGradient id="spend" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#4e7f71" stopOpacity={0.45} />
                <stop offset="100%" stopColor="#4e7f71" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="day" hide />
            <Tooltip
              cursor={{ stroke: 'var(--border)' }}
              contentStyle={{
                background: 'var(--surface-solid)',
                border: '1px solid var(--border)',
                borderRadius: 12,
                color: 'var(--text)',
              }}
              labelFormatter={(d) => pointLabel(String(d))}
              formatter={(v) => [money(Number(v), data.home_currency), 'Spent']}
            />
            <Area
              type="monotone"
              dataKey="spent"
              stroke="#4e7f71"
              strokeWidth={2.5}
              fill="url(#spend)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}

function Ring({ pct, label }: { pct: number; label: string }) {
  const r = 34
  const c = 2 * Math.PI * r
  const color = pct >= 1 ? '#c26a68' : pct >= 0.8 ? '#c4a04f' : '#5f9a78'
  return (
    <div className="relative h-24 w-24 shrink-0">
      <svg viewBox="0 0 80 80" className="h-full w-full -rotate-90">
        <circle cx="40" cy="40" r={r} fill="none" stroke="var(--border)" strokeWidth="8" />
        <motion.circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - pct) }}
          transition={{ duration: 1, ease: 'easeOut' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-lg font-semibold">{Math.round(pct * 100)}%</span>
        <span className="text-muted text-[10px] font-medium">{label}</span>
      </div>
    </div>
  )
}

function Insights({ data }: { data: MonthSummary }) {
  if (!data.insights.length) {
    return (
      <div className="text-muted flex items-center gap-3 text-sm">
        <Sparkles size={18} className="text-[var(--brand)]" />
        All calm. Nothing unusual {data.period === 'month' ? 'this month' : 'in this period'}.
      </div>
    )
  }
  return (
    <ul className="space-y-3">
      {data.insights.map((i, n) => (
        <li key={n} className="flex gap-3 text-sm">
          <span
            className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl ${
              i.severity === 'critical'
                ? 'bg-bad/15 text-bad'
                : i.severity === 'warning'
                  ? 'bg-warn/15 text-warn'
                  : 'bg-brand-50 dark:bg-brand-700/25 text-[var(--brand)]'
            }`}
          >
            {i.severity === 'info' ? <Info size={15} /> : <AlertTriangle size={15} />}
          </span>
          <span className="leading-relaxed font-medium">{i.message}</span>
        </li>
      ))}
    </ul>
  )
}

function Categories({ data }: { data: MonthSummary }) {
  const max = Math.max(...data.by_category.map((c) => Number(c.budget ?? 0)), ...data.by_category.map((c) => Number(c.spent)), 1)
  return (
    <ul className="space-y-4">
      {data.by_category.map((c) => {
        const spent = Number(c.spent)
        const over = c.budget !== null && spent > Number(c.budget)
        return (
          <li key={c.category_id ?? 'none'} className="flex items-center gap-3">
            <CategoryIcon icon={c.icon} color={c.color} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate font-semibold">{c.name}</span>
                <span className="tabular text-sm font-semibold">
                  {money(c.spent, data.home_currency)}
                  {c.budget && (
                    <span className="text-muted font-medium"> / {money(c.budget, data.home_currency, true)}</span>
                  )}
                </span>
              </div>
              <div className="relative mt-2 h-2 overflow-hidden rounded-full bg-[var(--border)]">
                <motion.div
                  className="h-full rounded-full"
                  style={{ background: over ? '#c26a68' : (c.color ?? '#4e7f71') }}
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min((spent / max) * 100, 100)}%` }}
                  transition={{ duration: 0.8, ease: 'easeOut' }}
                />
                {c.budget && (
                  <span
                    className="absolute top-0 h-full w-0.5 bg-[var(--text)] opacity-40"
                    style={{ left: `${Math.min((Number(c.budget) / max) * 100, 100)}%` }}
                  />
                )}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function Skeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <div className="card shimmer h-64 lg:col-span-3" />
      <div className="card shimmer h-64 lg:col-span-2" />
    </div>
  )
}

/** Expenses we couldn't convert are named, not silently left out, with a way to retry. */
function Unconverted({ items }: { items: MonthSummary['unconverted'] }) {
  const qc = useQueryClient()
  const retry = useMutation({
    mutationFn: api.reconvert,
    onSuccess: ({ converted }) => {
      qc.invalidateQueries()
      if (converted) toast.success(`Converted ${converted} expense${converted > 1 ? 's' : ''}.`)
      else toast.error('Still no exchange rate. Try again later.')
    },
  })
  return (
    <p className="text-warn mt-2 text-sm">
      Not included: {items.map((u) => `${money(u.total, u.currency)} (${u.count})`).join(', ')}, as no
      exchange rate was found.{' '}
      <button
        onClick={() => retry.mutate()}
        disabled={retry.isPending}
        className="font-medium underline underline-offset-2 disabled:opacity-50"
      >
        {retry.isPending ? 'Trying…' : 'Try again'}
      </button>
    </p>
  )
}
