import clsx from 'clsx'
import { ChevronDown } from 'lucide-react'

import { currencyOptions, useChangeHomeCurrency } from '../lib/currency'
import { Select } from './Select'

/** A small pill showing the home currency; picking another one converts everything to it. */
export function HomeCurrencyPill({ currency }: { currency: string }) {
  const change = useChangeHomeCurrency()
  return (
    <Select
      value={currency}
      options={currencyOptions(currency)}
      onChange={(c) => change.mutate(c)}
      searchable
      menuWidth={280}
      disabled={change.isPending}
      ariaLabel="Home currency"
      triggerClassName="inline-flex items-center gap-1 rounded-full border border-subtle px-2 py-0.5 text-xs font-semibold transition hover:bg-[var(--border)]"
      trigger={(_, open) => (
        <>
          {change.isPending ? 'Converting…' : currency}
          <ChevronDown size={12} className={clsx('text-muted transition', open && 'rotate-180')} />
        </>
      )}
    />
  )
}
