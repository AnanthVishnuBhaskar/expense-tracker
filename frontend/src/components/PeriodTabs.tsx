import clsx from 'clsx'
import { motion } from 'framer-motion'

import { PERIODS, type Period } from '../lib/useMonth'

/** Month · 3M · YTD · 1Y · All */
export function PeriodTabs({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  return (
    <div className="card flex gap-0.5 !rounded-xl p-1" role="tablist" aria-label="Time range">
      {PERIODS.map((p) => (
        <button
          key={p.key}
          role="tab"
          aria-selected={value === p.key}
          title={p.long}
          onClick={() => onChange(p.key)}
          className={clsx(
            'relative rounded-lg px-2.5 py-1.5 text-sm font-medium transition',
            value === p.key ? 'text-white' : 'text-muted hover:text-[var(--text)]',
          )}
        >
          {value === p.key && (
            <motion.span
              layoutId="period-pill"
              className="absolute inset-0 rounded-lg bg-brand-600"
              transition={{ type: 'spring', stiffness: 420, damping: 36 }}
            />
          )}
          <span className="relative">{p.short}</span>
        </button>
      ))}
    </div>
  )
}
