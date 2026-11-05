import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, LogOut, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { api, type Budget, type Category } from '../api'
import { CategoryIcon } from '../components/CategoryIcon'
import { Select } from '../components/Select'
import { currencyName, currencyOptions, useChangeHomeCurrency } from '../lib/currency'


export function SettingsPage() {
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const { data: me } = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  const { data: categories = [] } = useQuery({ queryKey: ['categories'], queryFn: api.categories })
  const { data: budgets = [] } = useQuery({ queryKey: ['budgets'], queryFn: api.budgets })
  const [changing, setChanging] = useState(false)
  const [adding, setAdding] = useState<number[]>([])
  const unbudgeted = categories.filter(
    (c) => !budgets.some((b) => b.category_id === c.id) && !adding.includes(c.id),
  )

  const update = useChangeHomeCurrency()

  if (!settings) return <div className="card shimmer h-64" />
  const currency = settings.home_currency

  return (
    <div className="max-w-2xl space-y-6">
      <header>
        <p className="text-muted text-sm font-medium">Settings</p>
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Make it yours</h1>
      </header>

      <section className="card p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-semibold">Home currency</h2>
            <p className="mt-1 text-lg">
              {currencyName.of(currency)} <span className="text-muted">({currency})</span>
            </p>
            <p className="text-muted mt-1 text-sm">
              {settings.home_currency_source === 'user'
                ? 'Chosen by you.'
                : 'Set automatically from where you are.'}{' '}
              Receipts keep their own currency and are converted to this for totals and budgets.
            </p>
          </div>
          {!changing && (
            <button
              onClick={() => setChanging(true)}
              className="shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium text-[var(--brand)] transition hover:bg-[var(--border)]"
            >
              Change
            </button>
          )}
        </div>
        {changing && (
          <div className="mt-4 flex gap-2">
            <div className="min-w-0 flex-1">
              <Select
                value={currency}
                options={currencyOptions(currency)}
                onChange={(c) => {
                  update.mutate(c)
                  setChanging(false)
                }}
                searchable
                ariaLabel="Home currency"
              />
            </div>
            <button
              onClick={() => setChanging(false)}
              className="text-muted rounded-xl px-3 text-sm font-medium hover:bg-[var(--border)]"
            >
              Cancel
            </button>
          </div>
        )}
      </section>

      <section className="card p-6">
        <h2 className="font-semibold">Monthly budgets</h2>
        <p className="text-muted mt-1 mb-5 text-sm">Optional. You'll get a heads-up at 80% and when one is passed.</p>
        <div className="space-y-3">
          <BudgetRow key={`all-${budgets.find((b) => b.category_id === null)?.amount}`} label="Overall" currency={currency} budget={budgets.find((b) => b.category_id === null)} categoryId={null} />
          {/* Only categories you've budgeted (or just added) are listed, to keep this short. */}
          {categories
            .filter((c) => budgets.some((b) => b.category_id === c.id) || adding.includes(c.id))
            .map((c) => (
              <BudgetRow key={`${c.id}-${budgets.find((b) => b.category_id === c.id)?.amount}`} category={c} label={c.name} currency={currency} budget={budgets.find((b) => b.category_id === c.id)} categoryId={c.id} onRemove={() => setAdding((a) => a.filter((id) => id !== c.id))} />
            ))}
        </div>
        {unbudgeted.length > 0 && (
          <div className="mt-4">
            <Select
              value={null}
              onChange={(v) => setAdding((a) => [...a, Number(v)])}
              ariaLabel="Add a budget for a category"
              menuWidth={240}
              triggerClassName="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-[var(--brand)] transition hover:bg-[var(--border)]"
              trigger={() => (
                <>
                  <Plus size={16} /> Add a category budget
                </>
              )}
              options={unbudgeted.map((c) => ({
                value: String(c.id),
                label: c.name,
                icon: <CategoryIcon icon={c.icon} color={c.color} size="xs" />,
              }))}
            />
          </div>
        )}
      </section>

      <section className="card flex items-center justify-between gap-4 p-6">
        <div className="min-w-0">
          <h2 className="font-semibold">Account</h2>
          <p className="mt-1 truncate">{me?.name}</p>
          <p className="text-muted truncate text-sm">{me?.email}</p>
        </div>
        <button
          onClick={() => api.logout().then(() => window.location.reload())}
          className="flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium text-[var(--brand)] transition hover:bg-[var(--border)]"
        >
          <LogOut size={16} /> Sign out
        </button>
      </section>
    </div>
  )
}

function BudgetRow({
  label,
  category,
  categoryId,
  budget,
  currency,
  onRemove,
}: {
  label: string
  category?: Category
  categoryId: number | null
  budget?: Budget
  currency: string
  /** Called when the row goes away (its budget was deleted, or it was never saved). */
  onRemove?: () => void
}) {
  const qc = useQueryClient()
  const [value, setValue] = useState(budget ? String(Number(budget.amount)) : '')
  const save = useMutation({
    mutationFn: async () => {
      if (value) await api.setBudget(categoryId, value)
      else if (budget) await api.deleteBudget(budget.id)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['budgets'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
      toast.success(`${label} budget ${value ? 'saved' : 'removed'}`)
    },
    onError: (e: Error) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: async () => {
      if (budget) await api.deleteBudget(budget.id)
    },
    onSuccess: () => {
      setValue('')
      onRemove?.()
      if (!budget) return
      qc.invalidateQueries({ queryKey: ['budgets'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
      toast.success(`${label} budget deleted`)
    },
    onError: (e: Error) => toast.error(e.message),
  })
  const dirty = value !== (budget ? String(Number(budget.amount)) : '')
  const removable = !dirty && (budget || onRemove)

  return (
    <div className="flex items-center gap-3">
      {category ? <CategoryIcon icon={category.icon} color={category.color} size="sm" /> : <span className="h-8 w-8 rounded-xl bg-brand-100 dark:bg-brand-700/40" />}
      <span className="flex-1 font-semibold">{label}</span>
      <div className="relative w-40">
        <span className="text-muted pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-xs font-semibold">{currency}</span>
        <input
          inputMode="decimal"
          value={value}
          placeholder="No limit"
          onChange={(e) => setValue(e.target.value.replace(/[^\d.]/g, ''))}
          onKeyDown={(e) => e.key === 'Enter' && dirty && save.mutate()}
          className="field tabular !pl-12 text-right"
        />
      </div>
      {removable ? (
        <button
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          aria-label={`Delete ${label} budget`}
          title="Delete budget"
          className="text-muted hover:text-bad rounded-xl p-2.5 transition hover:bg-[var(--border)]"
        >
          <Trash2 size={16} />
        </button>
      ) : (
        <button
          onClick={() => save.mutate()}
          disabled={!dirty || save.isPending}
          aria-label={`Save ${label} budget`}
          className="rounded-xl bg-brand-600 p-2.5 text-white transition disabled:opacity-0"
        >
          <Check size={16} />
        </button>
      )}
    </div>
  )
}
