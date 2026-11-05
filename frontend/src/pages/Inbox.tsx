import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Copy,
  RefreshCw,
  ScanLine,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { api, type Category, type ExpenseDraft, type Receipt } from '../api'
import { CategoryIcon } from '../components/CategoryIcon'
import { EmptyState } from '../components/EmptyState'
import { day, flag, money } from '../lib/format'

export function InboxPage() {
  const { data: receipts, isLoading } = useQuery({
    queryKey: ['receipts', 'open'],
    queryFn: () => api.receipts('open'),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'processing') ? 1500 : false),
  })
  const { data: categories = [] } = useQuery({ queryKey: ['categories'], queryFn: api.categories })

  return (
    <div className="space-y-6">
      <header>
        <p className="text-muted text-sm font-medium">Inbox</p>
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Confirm your receipts</h1>
        <p className="text-muted mt-1">Nothing is saved until you confirm it.</p>
      </header>
      {isLoading ? (
        <div className="card shimmer h-72" />
      ) : !receipts?.length ? (
        <EmptyState title="You're all caught up" body="New receipts land here, ready to confirm in one tap." />
      ) : (
        <motion.ul layout className="space-y-5">
          <AnimatePresence initial={false}>
            {receipts.map((r) => (
              <motion.li
                key={r.id}
                layout
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: 80, transition: { duration: 0.25 } }}
              >
                {r.status === 'processing' ? (
                  <ProcessingCard receipt={r} />
                ) : r.draft && (r.status === 'ready_to_confirm' || r.status === 'needs_review') ? (
                  <ConfirmCard receipt={r} draft={r.draft} categories={categories} />
                ) : (
                  <ProblemCard receipt={r} />
                )}
              </motion.li>
            ))}
          </AnimatePresence>
        </motion.ul>
      )}
    </div>
  )
}

function Thumb({ id, className }: { id: number; className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={clsx('overflow-hidden rounded-2xl bg-[var(--border)]', className)}
        aria-label="View the receipt photo"
      >
        <img src={api.receiptImageUrl(id)} alt="Receipt" className="h-full w-full object-cover object-top" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur"
          >
            <button className="absolute top-4 right-4 rounded-full bg-white/10 p-2 text-white" aria-label="Close">
              <X />
            </button>
            <motion.img
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              src={api.receiptImageUrl(id)}
              alt="Receipt"
              className="max-h-full max-w-full rounded-2xl"
            />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}

function ProcessingCard({ receipt }: { receipt: Receipt }) {
  return (
    <div className="card flex items-center gap-5 p-5">
      <div className="relative h-28 w-20 shrink-0 overflow-hidden rounded-2xl">
        <img src={api.receiptImageUrl(receipt.id)} alt="" className="h-full w-full object-cover" />
        <div className="scan-line absolute inset-x-0 h-0.5 bg-brand-400/80" />
      </div>
      <div>
        <div className="flex items-center gap-2 font-semibold">
          <ScanLine size={18} className="text-[var(--brand)]" /> Reading your receipt…
        </div>
        <p className="text-muted mt-1 text-sm">
          Checking the photo, extracting every detail and making sure the totals add up.
        </p>
      </div>
    </div>
  )
}

function useReceiptActions(id: number) {
  const qc = useQueryClient()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['receipts'] })
    qc.invalidateQueries({ queryKey: ['summary'] })
    qc.invalidateQueries({ queryKey: ['expenses'] })
  }
  const discard = useMutation({
    mutationFn: () => api.discard(id),
    onSuccess: () => {
      refresh()
      toast('Receipt discarded')
    },
  })
  const retry = useMutation({ mutationFn: () => api.retry(id), onSuccess: refresh })
  const confirm = useMutation({
    mutationFn: (draft: ExpenseDraft) => api.confirm(id, draft),
    onSuccess: (e) => {
      refresh()
      toast.success(`Saved ${e.merchant_name}`, {
        description: money(e.total, e.currency) + (e.category_name ? ` · ${e.category_name}` : ''),
      })
    },
    onError: (e: Error) => toast.error(e.message),
  })
  return { discard, retry, confirm }
}

function ProblemCard({ receipt }: { receipt: Receipt }) {
  const { discard, retry } = useReceiptActions(receipt.id)
  const title = {
    retake: 'This photo is hard to read',
    rejected: "This doesn't look like a receipt",
    failed: "We couldn't read this one",
  }[receipt.status as 'retake' | 'rejected' | 'failed']
  return (
    <div className="card flex gap-5 p-5">
      <Thumb id={receipt.id} className="h-28 w-20 shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 font-semibold text-warn">
          <AlertTriangle size={18} /> {title}
        </div>
        {receipt.status_detail && <p className="text-muted mt-1 text-sm">{receipt.status_detail}</p>}
        <div className="mt-auto flex gap-2 pt-3">
          {receipt.status === 'failed' && (
            <button
              onClick={() => retry.mutate()}
              className="flex items-center gap-1.5 rounded-xl bg-brand-50 dark:bg-brand-700/25 px-3 py-2 text-sm font-semibold text-[var(--brand)]"
            >
              <RefreshCw size={15} /> Try again
            </button>
          )}
          <button
            onClick={() => discard.mutate()}
            className="text-muted flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold hover:bg-[var(--border)]"
          >
            <Trash2 size={15} /> Remove
          </button>
        </div>
      </div>
    </div>
  )
}

function ConfirmCard({
  receipt,
  draft: initial,
  categories,
}: {
  receipt: Receipt
  draft: ExpenseDraft
  categories: Category[]
}) {
  const [draft, setDraft] = useState<ExpenseDraft>(initial)
  const [open, setOpen] = useState(receipt.status === 'needs_review')
  const { discard, confirm } = useReceiptActions(receipt.id)
  const flagged = new Set(draft.low_confidence_fields)
  const set = <K extends keyof ExpenseDraft>(k: K, v: ExpenseDraft[K]) => setDraft((d) => ({ ...d, [k]: v }))
  const category = categories.find((c) => c.id === draft.category_id)
  const chipRow = useRef<HTMLDivElement>(null)
  // Bring the suggested category into view without scrolling the page.
  useEffect(() => {
    const row = chipRow.current
    const chip = row?.querySelector<HTMLElement>('[data-selected]')
    if (row && chip) row.scrollLeft = chip.offsetLeft - row.offsetLeft - 8
  }, [categories.length])

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-col gap-5 p-5 sm:flex-row">
        <Thumb id={receipt.id} className="h-48 w-full shrink-0 sm:h-auto sm:min-h-44 sm:w-36" />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <input
                value={draft.merchant.name}
                onChange={(e) => set('merchant', { ...draft.merchant, name: e.target.value })}
                className="w-full truncate bg-transparent text-xl font-semibold outline-none focus:underline decoration-brand-400 decoration-2 underline-offset-4"
                aria-label="Merchant"
              />
              <div className="text-muted mt-0.5 flex flex-wrap items-center gap-x-2 text-sm">
                {draft.country && <span>{flag(draft.country)}</span>}
                <span>{day(draft.purchased_on, { year: 'numeric' })}</span>
                {draft.purchased_at_time && <span>· {draft.purchased_at_time}</span>}
                {draft.merchant.city && <span>· {draft.merchant.city}</span>}
                {draft.receipt_number && <span>· #{draft.receipt_number}</span>}
              </div>
            </div>
            <div className="text-right">
              <div className="tabular text-2xl font-semibold">{money(draft.total, draft.currency)}</div>
              {draft.total_home && draft.home_currency !== draft.currency && (
                <div className="text-muted tabular text-sm">≈ {money(draft.total_home, draft.home_currency!)}</div>
              )}
            </div>
          </div>

          {receipt.issues.length > 0 && (
            <div className="mt-4 space-y-1.5 rounded-2xl border border-warn/30 bg-warn/10 p-3 text-sm">
              {receipt.issues.map((issue) => (
                <div key={issue} className="flex gap-2 font-medium text-warn">
                  {issue.startsWith('Looks like a duplicate') ? (
                    <Copy size={16} className="mt-0.5 shrink-0" />
                  ) : (
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                  )}
                  {issue}
                </div>
              ))}
            </div>
          )}

          <div ref={chipRow} className="mt-4 flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
            {categories.map((c) => (
              <button
                key={c.id}
                data-selected={c.id === draft.category_id || undefined}
                onClick={() => set('category_id', c.id)}
                className={clsx(
                  'flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-semibold transition',
                  c.id === draft.category_id
                    ? 'border-transparent text-white'
                    : 'border-subtle text-muted hover:text-[var(--text)]',
                )}
                style={c.id === draft.category_id ? { background: c.color ?? '#4e7f71' } : undefined}
              >
                {c.name}
              </button>
            ))}
          </div>
        </div>
      </div>

      <button
        onClick={() => setOpen(!open)}
        className="text-muted flex w-full items-center justify-center gap-1.5 border-t border-subtle py-2.5 text-sm font-semibold hover:text-[var(--text)]"
      >
        {open ? 'Hide details' : `All details · ${draft.line_items.length} items`}
        <ChevronDown size={16} className={clsx('transition', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <DetailsEditor draft={draft} setDraft={setDraft} flagged={flagged} />
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex items-center gap-3 border-t border-subtle p-4">
        {category && <CategoryIcon icon={category.icon} color={category.color} size="sm" />}
        <span className="text-muted hidden text-sm sm:inline">
          {Math.round((receipt.confidence ?? 0) * 100)}% confident
        </span>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => discard.mutate()}
            className="text-muted rounded-2xl px-4 py-2.5 font-semibold transition hover:bg-[var(--border)]"
          >
            Discard
          </button>
          <button
            onClick={() => confirm.mutate(draft)}
            disabled={confirm.isPending}
            className="flex items-center gap-2 btn-primary px-5 py-2.5"
          >
            <Check size={18} /> Confirm
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  flagged,
  type = 'text',
  className,
}: {
  label: string
  value: string | number | null | undefined
  onChange: (v: string) => void
  flagged?: boolean
  type?: string
  className?: string
}) {
  return (
    <label className={clsx('block', className)}>
      <span className="text-muted mb-1 block text-xs font-semibold tracking-wide uppercase">{label}</span>
      <input
        type={type}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        className={clsx('field tabular', flagged && 'flagged')}
      />
    </label>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  )
}

function DetailsEditor({
  draft,
  setDraft,
  flagged,
}: {
  draft: ExpenseDraft
  setDraft: React.Dispatch<React.SetStateAction<ExpenseDraft>>
  flagged: Set<string>
}) {
  const set = (k: keyof ExpenseDraft) => (v: string) => setDraft((d) => ({ ...d, [k]: v || null }))
  const setCustomer = (k: keyof ExpenseDraft['customer']) => (v: string) =>
    setDraft((d) => ({ ...d, customer: { ...d.customer, [k]: v || null } }))
  const setMerchant = (k: keyof ExpenseDraft['merchant']) => (v: string) =>
    setDraft((d) => ({ ...d, merchant: { ...d.merchant, [k]: v || null } }))
  const setItem = (i: number, k: 'description' | 'quantity' | 'amount') => (v: string) =>
    setDraft((d) => ({
      ...d,
      line_items: d.line_items.map((it, n) => (n === i ? { ...it, [k]: v } : it)),
    }))
  const is = (name: string) => flagged.has(name)

  return (
    <div className="space-y-6 border-t border-subtle bg-[var(--border)]/30 p-5">
      <Section title="Purchase">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Field label="Date" type="date" value={draft.purchased_on} onChange={set('purchased_on')} flagged={is('purchase_date')} />
          <Field label="Time" value={draft.purchased_at_time} onChange={set('purchased_at_time')} />
          <Field label="Total" value={draft.total} onChange={set('total')} flagged={is('total')} />
          <Field label="Currency" value={draft.currency} onChange={(v) => setDraft((d) => ({ ...d, currency: v.toUpperCase() }))} flagged={is('currency')} />
          <Field label="Receipt no." value={draft.receipt_number} onChange={set('receipt_number')} />
          <Field label="Order no." value={draft.order_number} onChange={set('order_number')} />
          <Field label="Tip" value={draft.tip} onChange={set('tip')} />
          <Field label="Discount" value={draft.discount_total} onChange={set('discount_total')} />
        </div>
      </Section>

      <Section title="Items">
        {draft.line_items.length === 0 ? (
          <p className="text-muted text-sm">No itemised lines on this receipt.</p>
        ) : (
          <div className="space-y-2">
            {draft.line_items.map((item, i) => (
              <div key={i} className="grid grid-cols-[1fr_4.5rem_6.5rem] gap-2">
                <input className="field" value={item.description} onChange={(e) => setItem(i, 'description')(e.target.value)} aria-label="Item" />
                <input className="field tabular text-right" value={item.quantity ?? ''} onChange={(e) => setItem(i, 'quantity')(e.target.value)} aria-label="Quantity" />
                <input className="field tabular text-right" value={item.amount} onChange={(e) => setItem(i, 'amount')(e.target.value)} aria-label="Amount" />
                {item.description_en && <p className="text-muted col-span-3 -mt-1 px-1 text-xs">{item.description_en}</p>}
              </div>
            ))}
          </div>
        )}
        {(draft.subtotal || draft.tax_lines.length > 0) && (
          <dl className="mt-4 space-y-1 text-sm">
            {draft.subtotal && <Row label="Subtotal" value={money(draft.subtotal, draft.currency)} />}
            {draft.tax_lines.map((t) => (
              <Row key={t.name} label={`${t.name}${t.rate_percent ? ` ${Number(t.rate_percent)}%` : ''}`} value={money(t.amount, draft.currency)} />
            ))}
            {draft.service_charge && <Row label="Service charge" value={money(draft.service_charge, draft.currency)} />}
            {draft.delivery_fee && <Row label="Delivery" value={money(draft.delivery_fee, draft.currency)} />}
            {draft.rounding && <Row label="Rounding" value={money(draft.rounding, draft.currency)} />}
            {draft.tax_inclusive && <p className="text-muted text-xs">Prices include tax.</p>}
          </dl>
        )}
      </Section>

      <Section title="Merchant">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Address" value={draft.merchant.address} onChange={setMerchant('address')} className="md:col-span-2" />
          <Field label="Phone" value={draft.merchant.phone} onChange={setMerchant('phone')} />
          <Field label="Website / email" value={draft.merchant.website ?? draft.merchant.email} onChange={setMerchant('website')} />
        </div>
        {draft.merchant.tax_ids.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {draft.merchant.tax_ids.map((t) => (
              <span key={t.value} className="rounded-lg bg-[var(--border)] px-2 py-1 font-mono text-xs">
                {t.type} {t.value}
              </span>
            ))}
          </div>
        )}
      </Section>

      <Section title="Customer">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Name" value={draft.customer.name} onChange={setCustomer('name')} />
          <Field label="Phone" value={draft.customer.phone} onChange={setCustomer('phone')} />
          <Field label="Email" value={draft.customer.email} onChange={setCustomer('email')} />
          <Field label="Loyalty ID" value={draft.customer.loyalty_id} onChange={setCustomer('loyalty_id')} />
          <Field label="Tax ID" value={draft.customer.tax_id} onChange={setCustomer('tax_id')} />
        </div>
      </Section>

      {(draft.payments.length > 0 || draft.extras.length > 0) && (
        <Section title="Payment & more">
          <dl className="space-y-1 text-sm">
            {draft.payments.map((p, i) => (
              <Row
                key={i}
                label={[p.method, p.card_brand, p.card_last4 && `•••• ${p.card_last4}`].filter(Boolean).join(' ')}
                value={p.reference ?? (p.amount ? money(p.amount, draft.currency) : '')}
              />
            ))}
            {draft.extras.map((x, i) => (
              <Row key={`x${i}`} label={x.label} value={x.value} />
            ))}
          </dl>
        </Section>
      )}

      <Field label="Notes" value={draft.notes} onChange={set('notes')} />
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted capitalize">{label}</dt>
      <dd className="tabular truncate text-right font-medium">{value}</dd>
    </div>
  )
}
