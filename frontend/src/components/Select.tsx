import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, ChevronDown, Search } from 'lucide-react'
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export interface SelectOption {
  value: string
  label: string
  hint?: string
  icon?: React.ReactNode
}

interface Props {
  value: string | null
  options: SelectOption[]
  onChange: (value: string) => void
  placeholder?: string
  /** Adds a filter box at the top; worth it for long lists like currencies. */
  searchable?: boolean
  ariaLabel?: string
  /** Custom trigger; defaults to a field-style button. */
  trigger?: (selected: SelectOption | undefined, open: boolean) => React.ReactNode
  triggerClassName?: string
  menuWidth?: number
  align?: 'left' | 'right'
  disabled?: boolean
}

const MENU_MAX = 288
const GAP = 6

/**
 * A dropdown that opens just below its button, matching the app's look.
 * Native selects are avoided because macOS draws them as a menu over the button.
 */
export function Select({
  value,
  options,
  onChange,
  placeholder = 'Choose…',
  searchable,
  ariaLabel,
  trigger,
  triggerClassName,
  menuWidth,
  align = 'left',
  disabled,
}: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [pos, setPos] = useState<{ top: number; left: number; width: number; maxHeight: number; up: boolean }>()
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const listId = useId()
  const selected = options.find((o) => o.value === value)

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => o.label.toLowerCase().includes(q) || o.hint?.toLowerCase().includes(q))
  }, [options, query])

  const place = useCallback(() => {
    const r = buttonRef.current?.getBoundingClientRect()
    if (!r) return
    const width = Math.min(Math.max(r.width, menuWidth ?? 0), window.innerWidth - 16)
    const below = window.innerHeight - r.bottom - GAP - 8
    const above = r.top - GAP - 8
    // Drop down unless there's really no room below.
    const up = below < 160 && above > below
    const left = align === 'right' ? r.right - width : r.left
    setPos({
      top: up ? r.top - GAP : r.bottom + GAP,
      left: Math.max(8, Math.min(left, window.innerWidth - width - 8)),
      width,
      maxHeight: Math.min(MENU_MAX, up ? above : below),
      up,
    })
  }, [align, menuWidth])

  const close = useCallback(() => {
    setOpen(false)
    setQuery('')
  }, [])

  useLayoutEffect(() => {
    if (open) place()
  }, [open, place])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!buttonRef.current?.contains(t) && !menuRef.current?.contains(t)) close()
    }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, place, close])

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active, open])

  const openMenu = () => {
    setActive(Math.max(0, options.findIndex((o) => o.value === value)))
    setOpen(true)
  }
  const pick = (o: SelectOption) => {
    close()
    if (o.value !== value) onChange(o.value)
    buttonRef.current?.focus()
  }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') setActive((i) => Math.min(i + 1, shown.length - 1))
    else if (e.key === 'ArrowUp') setActive((i) => Math.max(i - 1, 0))
    else if (e.key === 'Enter' && shown[active]) pick(shown[active])
    else if (e.key === 'Escape') {
      close()
      buttonRef.current?.focus()
    } else if (e.key === 'Tab') close()
    else return
    e.preventDefault()
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={(e) => {
          if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
            e.preventDefault()
            openMenu()
          } else if (open) onKey(e)
        }}
        className={trigger ? triggerClassName : clsx('field flex items-center gap-2 text-left', triggerClassName)}
      >
        {trigger ? (
          trigger(selected, open)
        ) : (
          <>
            {selected?.icon}
            <span className={clsx('min-w-0 flex-1 truncate', !selected && 'text-muted')}>
              {selected?.label ?? placeholder}
            </span>
            <ChevronDown size={16} className={clsx('text-muted shrink-0 transition', open && 'rotate-180')} />
          </>
        )}
      </button>
      {createPortal(
        <AnimatePresence>
          {open && pos && (
            <motion.div
              ref={menuRef}
              initial={{ opacity: 0, y: pos.up ? 4 : -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: pos.up ? 4 : -4 }}
              transition={{ duration: 0.12 }}
              style={{
                position: 'fixed',
                left: pos.left,
                width: pos.width,
                ...(pos.up ? { bottom: window.innerHeight - pos.top } : { top: pos.top }),
              }}
              className="card z-[60] flex flex-col overflow-hidden !rounded-xl p-1 shadow-lg"
              onKeyDown={onKey}
            >
              {searchable && (
                <div className="relative mb-1 border-b border-subtle p-1 pb-2">
                  <Search size={14} className="text-muted pointer-events-none absolute top-[calc(50%-4px)] left-3 -translate-y-1/2" />
                  <input
                    autoFocus
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value)
                      setActive(0)
                    }}
                    placeholder="Search"
                    aria-label="Search"
                    className="field !py-1.5 !pl-8 text-sm"
                  />
                </div>
              )}
              <ul
                ref={listRef}
                id={listId}
                role="listbox"
                style={{ maxHeight: pos.maxHeight - (searchable ? 48 : 0) }}
                className="overflow-y-auto overscroll-contain"
              >
                {shown.length === 0 && <li className="text-muted px-3 py-2 text-sm">No matches</li>}
                {shown.map((o, i) => (
                  <li
                    key={o.value}
                    data-index={i}
                    role="option"
                    aria-selected={o.value === value}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => pick(o)}
                    className={clsx(
                      'flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm',
                      i === active && 'bg-[var(--border)]',
                    )}
                  >
                    {o.icon}
                    <span className="min-w-0 flex-1 truncate">{o.label}</span>
                    {o.hint && <span className="text-muted text-xs">{o.hint}</span>}
                    {o.value === value && <Check size={14} className="shrink-0 text-[var(--brand)]" />}
                  </li>
                ))}
              </ul>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  )
}
