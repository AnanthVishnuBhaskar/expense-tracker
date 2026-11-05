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
import { CategoryIcon } from './CategoryIcon'
import { ReceiptThumb as Thumb } from './ReceiptThumb'
import { Select } from './Select'
import { flag, money } from '../lib/format'
import { setReviewOpen, useOpenReceipts, useReviewOpen } from '../lib/review'

/** Slide-in panel where new receipts are checked and saved. Opens by itself after an upload. */
export function ReviewPanel() {
  const open = useReviewOpen()
  const { data: receipts } = useOpenReceipts()
  const { data: categories = [] } = useQuery({ queryKey: ['categories'], queryFn: api.categories })
  const count = receipts?.length ?? 0
  const hadReceipts = useRef(false)

  // Close by itself once the last receipt is saved or removed.
  useEffect(() => {
    if (!open) return
    if (count > 0) hadReceipts.current = true
    else if (hadReceipts.current) {
      hadReceipts.current = false
      setReviewOpen(false)
      toast.success('All caught up')
    }
  }, [open, count])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setReviewOpen(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setReviewOpen(false)}
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
          />
          <motion.aside
            key="panel"
            role="dialog"
            aria-label="Review receipts"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="fixed inset-0 z-50 m-auto flex h-fit max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-xl flex-col overflow-hidden rounded-2xl border border-subtle bg-[var(--bg)] shadow-2xl"
          >
            <header className="flex items-center justify-between border-b border-subtle px-5 py-4">
              <div>
                <h2 className="text-lg font-semibold">Review receipts</h2>
                <p className="text-muted text-sm">
                  {count ? `${count} waiting · nothing is saved until you confirm` : 'Nothing waiting'}
                </p>
              </div>
              <button
                onClick={() => setReviewOpen(false)}
                aria-label="Close"
                className="rounded-lg p-2 transition hover:bg-[var(--border)]"
              >
                <X size={18} />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {!receipts ? (
                <div className="card shimmer h-60" />
              ) : !count ? (
                <p className="text-muted p-10 text-center">You're all caught up.</p>
              ) : (
                <motion.ul layout className="space-y-4">
                  <AnimatePresence initial={false}>
                    {receipts.map((r) => (
                      <motion.li
                        key={r.id}
                        layout
                        initial={{ opacity: 0, y: 16 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, x: 60, transition: { duration: 0.2 } }}
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
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function ProcessingCard({ receipt }: { receipt: Receipt }) {
  const { retry } = useReceiptActions(receipt.id)
  const [started, setStarted] = useState(receipt.uploaded_at)
  const seconds = useSecondsSince(started)
  // The server gives up after ~90s per call; past that, offer a way out instead of waiting.
  const slow = seconds > 120
  return (
    <div className="card flex items-center gap-4 p-4">
      <div className="relative h-24 w-[4.5rem] shrink-0 overflow-hidden rounded-xl">
        <img src={api.receiptImageUrl(receipt.id)} alt="" className="h-full w-full object-cover" />
        {!slow && <div className="scan-line absolute inset-x-0 h-0.5 bg-brand-400/80" />}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2 font-semibold">
          <ScanLine size={18} className="text-[var(--brand)]" />
          {slow ? 'This is taking longer than usual' : (receipt.status_detail ?? 'Reading the receipt…')}
        </div>
        <p className="text-muted tabular mt-1 text-sm">
          {slow
            ? 'Claude may be busy. You can try again.'
            : `${seconds}s · usually 15–40 seconds`}
        </p>
        {slow && (
          <button
            onClick={() => {
              setStarted(new Date().toISOString())
              retry.mutate()
            }}
            className="mt-2 flex items-center gap-1.5 rounded-lg bg-brand-50 px-3 py-1.5 text-sm font-medium text-[var(--brand)] dark:bg-brand-700/25"
          >
            <RefreshCw size={14} /> Try again
          </button>
        )}
      </div>
    </div>
  )
}

function useSecondsSince(iso: string) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  return Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
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
    <div className="card flex gap-4 p-4">
      <Thumb id={receipt.id} className="h-24 w-[4.5rem] shrink-0 !rounded-xl" />
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

// Fields shown up front; everything else waits under "More details".
const ESSENTIAL_FLAGS = new Set(['merchant', 'purchase_date', 'total', 'category'])

function ConfirmCard({
  receipt,
  draft: initial,
  categories,
}: {
  receipt: Receipt
  draft: ExpenseDraft
  categories: Category[]
}) {
  const [draft, setDraft] = useState<ExpenseDraft>(() => ({
    ...initial,
    // Show "2", not "2.0" or "2.000".
    line_items: initial.line_items.map((it) => ({
      ...it,
      quantity: Number.isFinite(Number(it.quantity ?? NaN)) ? String(Number(it.quantity)) : it.quantity,
    })),
  }))
  const [open, setOpen] = useState(false)
  const { discard, confirm } = useReceiptActions(receipt.id)
  const flagged = new Set(draft.low_confidence_fields)
  const hiddenFlags = [...flagged].filter((f) => !ESSENTIAL_FLAGS.has(f)).length
  const set = <K extends keyof ExpenseDraft>(k: K, v: ExpenseDraft[K]) => setDraft((d) => ({ ...d, [k]: v }))

  return (
    <div className="card overflow-hidden">
      <div className="flex gap-4 p-4">
        <Thumb id={receipt.id} className="h-24 w-[4.5rem] shrink-0 !rounded-xl" />
        <div className="min-w-0 flex-1">
          <input
            value={draft.merchant.name}
            onChange={(e) => set('merchant', { ...draft.merchant, name: e.target.value })}
            className={clsx(
              'w-full truncate rounded-md bg-transparent text-lg font-semibold outline-none focus:underline decoration-brand-400 decoration-2 underline-offset-4',
              flagged.has('merchant') && 'text-warn',
            )}
            aria-label="Merchant"
          />
          <div className="text-muted flex flex-wrap items-center gap-x-1.5 text-sm">
            {draft.country && <span>{flag(draft.country)}</span>}
            {draft.merchant.city && <span>{draft.merchant.city}</span>}
            {draft.line_items.length > 0 && (
              <span>
                {draft.merchant.city && '· '}
                {draft.line_items.length} items
              </span>
            )}
          </div>
          {receipt.issues.length > 0 && (
            <div className="mt-2 space-y-1 text-sm">
              {receipt.issues.map((issue) => (
                <div key={issue} className="text-warn flex gap-1.5 font-medium">
                  {issue.startsWith('Looks like a duplicate') ? (
                    <Copy size={15} className="mt-0.5 shrink-0" />
                  ) : (
                    <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                  )}
                  {issue}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 px-4 pb-4 sm:grid-cols-[1fr_1fr_1.3fr]">
        <Field
          label="Date"
          type="date"
          value={draft.purchased_on}
          onChange={(v) => set('purchased_on', v || null)}
          flagged={flagged.has('purchase_date')}
        />
        <label className="block">
          <span className="text-muted mb-1 block text-xs font-medium">Total</span>
          <div className="relative">
            <input
              value={draft.total ?? ''}
              onChange={(e) => set('total', e.target.value || null)}
              inputMode="decimal"
              className={clsx('field tabular !pr-12', flagged.has('total') && 'flagged')}
            />
            {/* Currency comes from the receipt itself; it can be changed under More details. */}
            <span className="text-muted pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs font-medium">
              {draft.currency}
            </span>
          </div>
          {draft.total_home && draft.home_currency && draft.home_currency !== draft.currency && (
            <span className="text-muted tabular mt-1 block text-xs">≈ {money(draft.total_home, draft.home_currency)}</span>
          )}
        </label>
        <label className="col-span-2 block sm:col-span-1">
          <span className="text-muted mb-1 block text-xs font-medium">Category</span>
          <Select
            value={draft.category_id ? String(draft.category_id) : null}
            onChange={(v) => set('category_id', Number(v))}
            ariaLabel="Category"
            options={categories.map((c) => ({
                value: String(c.id),
                label: c.name,
                icon: <CategoryIcon icon={c.icon} color={c.color} size="xs" />,
              }))}
          />
        </label>
      </div>

      <button
        onClick={() => setOpen(!open)}
        className="text-muted flex w-full items-center justify-center gap-1.5 border-t border-subtle py-2 text-sm font-medium hover:text-[var(--text)]"
      >
        {open ? 'Fewer details' : 'More details'}
        {!open && hiddenFlags > 0 && <span className="text-warn">· {hiddenFlags} to check</span>}
        <ChevronDown size={15} className={clsx('transition', open && 'rotate-180')} />
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

      <div className="flex justify-end gap-2 border-t border-subtle p-3">
        <button
          onClick={() => discard.mutate()}
          className="text-muted rounded-xl px-4 py-2 font-medium transition hover:bg-[var(--border)]"
        >
          Discard
        </button>
        <button onClick={() => confirm.mutate(draft)} disabled={confirm.isPending} className="btn-primary px-5 py-2">
          <Check size={17} /> Save
        </button>
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
      <span className="text-muted mb-1 block text-xs font-medium">{label}</span>
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
  // Only show what the receipt actually had (judged once, so fields don't vanish while you type).
  const [initial] = useState(draft)
  const had = (v: unknown) => v !== null && v !== undefined && v !== ''
  const c0 = initial.customer
  const m0 = initial.merchant
  const hasMerchant = [m0.address, m0.phone, m0.website, m0.email].some(had) || m0.tax_ids.length > 0
  const hasCustomer = [c0.name, c0.phone, c0.email, c0.loyalty_id, c0.tax_id].some(had)

  return (
    <div className="bg-sunken space-y-5 border-t border-subtle p-4">
      <Section title="Purchase">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {had(initial.purchased_at_time) && (
            <Field label="Time" value={draft.purchased_at_time} onChange={set('purchased_at_time')} />
          )}
          <Field label="Currency" value={draft.currency} onChange={(v) => setDraft((d) => ({ ...d, currency: v.toUpperCase() }))} flagged={is('currency')} />
          {had(initial.receipt_number) && (
            <Field label="Receipt no." value={draft.receipt_number} onChange={set('receipt_number')} />
          )}
          {had(initial.order_number) && (
            <Field label="Order no." value={draft.order_number} onChange={set('order_number')} />
          )}
          {had(initial.tip) && (
            <Field label="Tip" value={draft.tip} onChange={set('tip')} />
          )}
          {had(initial.discount_total) && (
            <Field label="Discount" value={draft.discount_total} onChange={set('discount_total')} />
          )}
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

      {hasMerchant && (
      <Section title="Merchant">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {had(m0.address) && <Field label="Address" value={draft.merchant.address} onChange={setMerchant('address')} className="sm:col-span-2" />}
          {had(m0.phone) && <Field label="Phone" value={draft.merchant.phone} onChange={setMerchant('phone')} />}
          {(had(m0.website) || had(m0.email)) && (
            <Field label="Website / email" value={draft.merchant.website ?? draft.merchant.email} onChange={setMerchant('website')} />
          )}
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
      )}

      {hasCustomer && (
      <Section title="Customer">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {had(c0.name) && <Field label="Name" value={draft.customer.name} onChange={setCustomer('name')} />}
          {had(c0.phone) && <Field label="Phone" value={draft.customer.phone} onChange={setCustomer('phone')} />}
          {had(c0.email) && <Field label="Email" value={draft.customer.email} onChange={setCustomer('email')} />}
          {had(c0.loyalty_id) && <Field label="Loyalty ID" value={draft.customer.loyalty_id} onChange={setCustomer('loyalty_id')} />}
          {had(c0.tax_id) && <Field label="Tax ID" value={draft.customer.tax_id} onChange={setCustomer('tax_id')} />}
        </div>
      </Section>
      )}

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
