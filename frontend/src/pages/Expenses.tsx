import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { Download, Images, List, ReceiptText, Search, Trash2, X } from 'lucide-react'
import { useDeferredValue, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { api, type Category, type Expense } from '../api'
import { CategoryIcon } from '../components/CategoryIcon'
import { Select } from '../components/Select'
import { EmptyState } from '../components/EmptyState'
import { MonthNav } from '../components/MonthPicker'
import { PeriodTabs } from '../components/PeriodTabs'
import { ReceiptThumb } from '../components/ReceiptThumb'
import { day, flag, money, relativeDay } from '../lib/format'
import { useStoredChoice } from '../lib/startPage'
import { PERIODS, useDay, useMonth, usePeriod } from '../lib/useMonth'

export function Expenses() {
  const [month, setMonth] = useMonth()
  const [pickedDay, setPickedDay] = useDay()
  const [period, setPeriod] = usePeriod()
  const [q, setQ] = useState('')
  const [categoryId, setCategoryId] = useState<number | undefined>()
  const [selected, setSelected] = useState<Expense | null>(null)
  const [view, setView] = useStoredChoice('expenses-view', ['list', 'receipts'] as const, 'list')
  const search = useDeferredValue(q)

  const { data: categories = [] } = useQuery({ queryKey: ['categories'], queryFn: api.categories })
  const { data: monthExpenses, isLoading } = useQuery({
    queryKey: ['expenses', { month, period, search, categoryId }],
    queryFn: () => api.expenses({ month, period, q: search, category_id: categoryId }),
  })
  const expenses = pickedDay ? monthExpenses?.filter((e) => e.purchased_on === pickedDay) : monthExpenses
  const byId = useMemo(() => new Map(categories.map((c) => [c.id, c])), [categories])
  const groups = useMemo(() => {
    const map = new Map<string, Expense[]>()
    expenses?.forEach((e) => map.set(e.purchased_on, [...(map.get(e.purchased_on) ?? []), e]))
    return [...map.entries()]
  }, [expenses])

  return (
    <div className="space-y-6">
      <MonthNav
        eyebrow="Expenses"
        month={month}
        onChange={setMonth}
        day={pickedDay}
        onDay={setPickedDay}
        title={period === 'month' ? undefined : PERIODS.find((p) => p.key === period)!.long}
      >
        <PeriodTabs value={period} onChange={setPeriod} />
        <a
          href={api.exportUrl(month, period)}
          title="Export CSV"
          className="card flex items-center gap-2 !rounded-xl px-4 py-2.5 text-sm font-semibold transition hover:brightness-105"
        >
          <Download size={16} /> <span className="hidden sm:inline">Export CSV</span>
        </a>
      </MonthNav>
      {pickedDay && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted">Showing</span>
          <button
            onClick={() => setPickedDay(null)}
            className="flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 font-medium text-brand-700 transition hover:bg-brand-100 dark:bg-brand-700/30 dark:text-brand-100"
          >
            {day(pickedDay, { weekday: 'long', year: 'numeric' })}
            <X size={14} aria-label="Show the whole month" />
          </button>
        </div>
      )}

      <div className="space-y-3">
        <label className="card flex items-center gap-3 !rounded-2xl px-4 py-3">
          <Search size={18} className="text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search merchants or anything printed on a receipt"
            className="w-full bg-transparent outline-none placeholder:text-[var(--muted)]"
          />
        </label>
        <div className="flex items-center gap-3">
        <div className="flex min-w-0 flex-1 gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
          <Chip active={!categoryId} onClick={() => setCategoryId(undefined)}>All</Chip>
          {categories.map((c) => (
            <Chip key={c.id} active={categoryId === c.id} color={c.color} onClick={() => setCategoryId(c.id)}>
              {c.name}
            </Chip>
          ))}
        </div>
          <div className="card mb-1 flex shrink-0 gap-0.5 !rounded-lg p-0.5" role="tablist" aria-label="View">
            {(
              [
                ['list', List, 'List'],
                ['receipts', Images, 'Receipts'],
              ] as const
            ).map(([key, Icon, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={view === key}
                aria-label={label}
                title={label}
                onClick={() => setView(key)}
                className={clsx(
                  'rounded-md p-1.5 transition',
                  view === key ? 'bg-brand-600 text-white' : 'text-muted hover:text-[var(--text)]',
                )}
              >
                <Icon size={16} />
              </button>
            ))}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="card shimmer h-80" />
      ) : !expenses?.length ? (
        search || categoryId || pickedDay ? (
          <p className="text-muted card p-8 text-center">
            {pickedDay && !search && !categoryId ? 'Nothing spent on this day.' : 'No expenses match those filters.'}
          </p>
        ) : (
          <EmptyState title="Nothing here yet" body={`Confirmed receipts for ${period === 'month' ? 'this month' : 'this period'} will be listed here.`} />
        )
      ) : view === 'receipts' ? (
        <ReceiptGrid expenses={expenses} onOpen={setSelected} />
      ) : (
        <div className="space-y-6">
          {groups.map(([date, items]) => (
            <section key={date}>
              <div className="text-muted mb-2 flex justify-between px-1 text-sm font-semibold">
                <span>{relativeDay(date)}</span>
                <span className="tabular">
                  {money(items.reduce((s, e) => s + Number(e.total_home ?? 0), 0), items[0].home_currency)}
                </span>
              </div>
              <ul className="card divide-y divide-[var(--border)] overflow-hidden">
                {items.map((e) => {
                  const c = e.category_id ? byId.get(e.category_id) : undefined
                  return (
                    <li key={e.id}>
                      <button onClick={() => setSelected(e)} className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition hover:bg-[var(--border)]/40">
                        <CategoryIcon icon={c?.icon} color={c?.color} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5 font-semibold">
                            <span className="truncate">{e.merchant_name}</span>
                            {e.receipt_id && <ReceiptText size={14} className="text-muted shrink-0" aria-label="Has receipt photo" />}
                          </div>
                          <div className="text-muted truncate text-sm">
                            {[c?.name, e.payment_method, e.country && flag(e.country)].filter(Boolean).join(' · ')}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="tabular font-semibold">{money(e.total, e.currency)}</div>
                          {e.currency !== e.home_currency && e.total_home && (
                            <div className="text-muted tabular text-xs">{money(e.total_home, e.home_currency)}</div>
                          )}
                        </div>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
        </div>
      )}

      {/* Wrapped so the parent's space-y margin doesn't offset the fixed overlay. */}
      <div>
        <AnimatePresence>
          {selected && (
            <ExpenseSheet expense={selected} categories={categories} onClose={() => setSelected(null)} />
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function Chip({
  active,
  color,
  onClick,
  children,
}: {
  active: boolean
  color?: string | null
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'shrink-0 rounded-full border px-3.5 py-1.5 text-sm font-semibold transition',
        active ? 'border-transparent text-white' : 'border-subtle text-muted hover:text-[var(--text)]',
      )}
      style={active ? { background: color ?? '#4e7f71' } : undefined}
    >
      {children}
    </button>
  )
}

function ExpenseSheet({
  expense: e,
  categories,
  onClose,
}: {
  expense: Expense
  categories: Category[]
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [categoryId, setCategoryId] = useState(e.category_id)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['expenses'] })
    qc.invalidateQueries({ queryKey: ['summary'] })
  }
  const remove = useMutation({
    mutationFn: () => api.deleteExpense(e.id),
    onSuccess: () => {
      refresh()
      toast('Expense deleted')
      onClose()
    },
  })
  const recategorize = useMutation({
    mutationFn: (id: number) => api.setExpenseCategory(e.id, id),
    onSuccess: refresh,
  })

  return (
    <>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" />
      <motion.aside
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 12, scale: 0.98 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        className="bg-surface fixed inset-0 z-50 m-auto flex h-fit max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg flex-col overflow-y-auto rounded-2xl border border-subtle shadow-2xl"
      >
        <div className="flex items-start justify-between gap-3 p-6">
          <div>
            <h2 className="text-2xl font-semibold">{e.merchant_name}</h2>
            <p className="text-muted text-sm">
              {flag(e.country)} {day(e.purchased_on, { year: 'numeric', weekday: 'short' })}
              {e.purchased_at_time && ` · ${e.purchased_at_time}`}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-full p-2 hover:bg-[var(--border)]">
            <X size={20} />
          </button>
        </div>

        <div className="mx-6 flex gap-3">
        {e.receipt_id && <ReceiptThumb id={e.receipt_id} className="w-24 shrink-0 !rounded-2xl border border-subtle" />}
        <div className="flex-1 rounded-2xl bg-brand-600 p-5 text-white">
          <div className="text-sm opacity-80">Total paid</div>
          <div className="tabular text-3xl font-semibold">{money(e.total, e.currency)}</div>
          {e.currency !== e.home_currency && e.total_home && (
            <div className="text-sm opacity-80">
              ≈ {money(e.total_home, e.home_currency)} at {Number(e.fx_rate).toFixed(4)}
            </div>
          )}
        </div>
        </div>

        <div className="space-y-6 p-6">
          <label className="block">
            <span className="text-muted mb-1 block text-xs font-medium">Category</span>
            <Select
              value={categoryId ? String(categoryId) : null}
              onChange={(v) => {
                setCategoryId(Number(v))
                recategorize.mutate(Number(v))
              }}
              ariaLabel="Category"
              options={categories.map((c) => ({
                value: String(c.id),
                label: c.name,
                icon: <CategoryIcon icon={c.icon} color={c.color} size="xs" />,
              }))}
            />
          </label>

          {e.line_items.length > 0 && (
            <Block title="Items">
              {e.line_items.map((li, i) => (
                <Line key={i} label={`${li.quantity && Number(li.quantity) !== 1 ? `${Number(li.quantity)} × ` : ''}${li.description}`} value={money(li.amount, e.currency)} />
              ))}
            </Block>
          )}

          {(e.tax_total || e.payment_method) && (
            <Block title="Payment">
              {e.tax_total && <Line label="Tax included" value={money(e.tax_total, e.currency)} />}
              {e.payment_method && <Line label="Paid with" value={e.payment_method} />}
            </Block>
          )}

          {(e.merchant?.address || e.merchant?.phone || e.merchant?.tax_ids.length || e.receipt_number) && (
            <Block title="Merchant">
              {e.merchant?.address && <Line label="Address" value={e.merchant.address} />}
              {e.merchant?.phone && <Line label="Phone" value={e.merchant.phone} />}
              {e.merchant?.tax_ids.map((t) => <Line key={t.value} label={t.type} value={t.value} mono />)}
              {e.receipt_number && <Line label="Receipt no." value={e.receipt_number} mono />}
            </Block>
          )}

          {Object.values(e.customer).some(Boolean) && (
            <Block title="Customer">
              {e.customer.name && <Line label="Name" value={e.customer.name} />}
              {e.customer.phone && <Line label="Phone" value={e.customer.phone} />}
              {e.customer.email && <Line label="Email" value={e.customer.email} />}
              {e.customer.loyalty_id && <Line label="Loyalty ID" value={e.customer.loyalty_id} mono />}
            </Block>
          )}

          {e.extras.length > 0 && (
            <Block title="Also on the receipt">
              {e.extras.map((x, i) => <Line key={i} label={x.label} value={x.value} />)}
            </Block>
          )}

          {(e.return_by || e.warranty_until) && (
            <Block title="Reminders">
              {e.return_by && <Line label="Return by" value={day(e.return_by, { year: 'numeric' })} />}
              {e.warranty_until && <Line label="Warranty until" value={day(e.warranty_until, { year: 'numeric' })} />}
            </Block>
          )}

          <button
            onClick={() => confirm('Delete this expense?') && remove.mutate()}
            className="flex w-full items-center justify-center gap-2 rounded-2xl py-3 font-semibold text-bad transition hover:bg-bad/10"
          >
            <Trash2 size={17} /> Delete expense
          </button>
        </div>
      </motion.aside>
    </>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-muted mb-2 text-xs font-semibold tracking-wider uppercase">{title}</h3>
      <dl className="space-y-1.5 text-sm">{children}</dl>
    </section>
  )
}

function Line({ label, value, mono, muted }: { label: string; value: string; mono?: boolean; muted?: boolean }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className={clsx('min-w-0', muted ? 'text-muted' : 'font-medium')}>{label}</dt>
      <dd className={clsx('tabular shrink-0 text-right', mono && 'font-mono text-xs', 'max-w-[60%] truncate')}>{value}</dd>
    </div>
  )
}

/** Photo grid of the month's receipts; tap one to open its expense. */
function ReceiptGrid({ expenses, onOpen }: { expenses: Expense[]; onOpen: (e: Expense) => void }) {
  const withPhotos = expenses.filter((e) => e.receipt_id)
  if (!withPhotos.length) {
    return <p className="text-muted card p-8 text-center">No receipt photos for these expenses.</p>
  }
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {withPhotos.map((e) => (
        <li key={e.id}>
          <button onClick={() => onOpen(e)} className="card group block w-full overflow-hidden text-left">
            <div className="bg-sunken aspect-[3/4] overflow-hidden">
              <img
                src={api.receiptImageUrl(e.receipt_id!)}
                alt={`Receipt from ${e.merchant_name}`}
                loading="lazy"
                className="h-full w-full object-contain object-top transition group-hover:scale-[1.02]"
              />
            </div>
            <div className="p-3">
              <div className="truncate text-sm font-semibold">{e.merchant_name}</div>
              <div className="text-muted flex justify-between gap-2 text-xs">
                <span>{day(e.purchased_on)}</span>
                <span className="tabular">{money(e.total, e.currency)}</span>
              </div>
            </div>
          </button>
        </li>
      ))}
    </ul>
  )
}
