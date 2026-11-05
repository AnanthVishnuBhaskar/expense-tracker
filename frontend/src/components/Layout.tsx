import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { motion } from 'framer-motion'
import {
  Camera,
  ClipboardCheck,
  LayoutDashboard,
  ListOrdered,
  LogOut,
  Moon,
  Settings,
  Sun,
  Upload,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useSearchParams } from 'react-router-dom'

import { api } from '../api'
import { setReviewOpen, useOpenReceipts } from '../lib/review'
import { useRememberView } from '../lib/startPage'
import { useTheme } from '../lib/theme'
import { pickFiles, useUpload } from '../lib/useUpload'
import { ReviewPanel } from './ReviewPanel'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/expenses', label: 'Expenses', icon: ListOrdered },
  { to: '/settings', label: 'Settings', icon: Settings },
]

/** Tell the server where we are, so it can pick a home currency until you choose one yourself. */
function useDetectSettings() {
  const qc = useQueryClient()
  useEffect(() => {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
    api.detectSettings({ timezone, locale: navigator.language }).then((s) => {
      const before = qc.getQueryData<{ home_currency: string }>(['settings'])
      qc.setQueryData(['settings'], s)
      if (before?.home_currency !== s.home_currency) qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'settings' })
    })
  }, [qc])
}

export function Layout() {
  const { theme, toggle } = useTheme()
  const upload = useUpload()
  const { data: waiting } = useOpenReceipts()
  const toReview = waiting?.filter((r) => r.status !== 'processing').length ?? 0
  const [dragging, setDragging] = useState(false)
  useDetectSettings()
  const { data: me } = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  useRememberView(me?.email)
  const [params] = useSearchParams()
  // Overview and Expenses share the picked month or period, so switching between them keeps your place.
  const shared = new URLSearchParams(
    [...params].filter(([k]) => k === 'month' || k === 'period'),
  ).toString()
  const withMonth = (to: string) => (shared && (to === '/' || to === '/expenses') ? `${to}?${shared}` : to)
  const hasFiles = (e: React.DragEvent) => e.dataTransfer.types.includes('Files')

  return (
    <div
      className="mx-auto flex min-h-dvh max-w-7xl"
      onDragOver={(e) => {
        if (!hasFiles(e)) return
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={(e) => {
        if (!e.relatedTarget) setDragging(false)
      }}
      onDrop={(e) => {
        if (!hasFiles(e)) return
        e.preventDefault()
        setDragging(false)
        const files = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith('image/') || /\.hei[cf]$/i.test(f.name))
        if (files.length) upload.mutate(files)
      }}
    >
      {dragging && (
        <div className="pointer-events-none fixed inset-3 z-50 flex items-center justify-center rounded-2xl border-2 border-dashed border-brand-400 bg-brand-50/85 dark:bg-brand-700/40">
          <div className="text-center">
            <Upload size={28} className="mx-auto text-brand-600 dark:text-brand-300" />
            <p className="mt-2 font-semibold text-brand-700 dark:text-brand-100">Drop to add receipts</p>
          </div>
        </div>
      )}
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-2 p-5 md:flex">
        <div className="mb-6 flex items-center gap-3 px-2">
          <img src="/favicon.svg" className="h-9 w-9" alt="" />
          <div>
            <div className="text-lg font-semibold tracking-tight">Receipts</div>
            <div className="text-muted text-xs">Snap. Confirm. Done.</div>
          </div>
        </div>
        <button
          onClick={() => pickFiles((f) => upload.mutate(f))}
          disabled={upload.isPending}
          className="mb-4 flex items-center justify-center gap-2 btn-primary px-4 py-2.5"
        >
          <Upload size={18} /> {upload.isPending ? 'Uploading…' : 'Add receipts'}
        </button>
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={withMonth(to)}
            end
            className={({ isActive }) =>
              clsx(
                'relative flex items-center gap-3 rounded-2xl px-4 py-2.5 font-medium transition',
                isActive ? 'text-[var(--text)]' : 'text-muted hover:text-[var(--text)]',
              )
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span
                    layoutId="nav-pill"
                    className="card absolute inset-0 !rounded-2xl"
                    transition={{ type: 'spring', stiffness: 400, damping: 34 }}
                  />
                )}
                <Icon size={18} className="relative" />
                <span className="relative">{label}</span>
              </>
            )}
          </NavLink>
        ))}
        {me?.name && (
          <div className="mt-auto px-4 pb-2">
            <p className="truncate text-sm font-medium">{me.name}</p>
            <p className="text-muted truncate text-xs">{me.email}</p>
          </div>
        )}
        <button
          onClick={() => api.logout().then(() => window.location.reload())}
          className={clsx(
            'text-muted flex items-center gap-3 rounded-2xl px-4 py-2.5 font-medium transition hover:text-[var(--text)]',
            !me?.name && 'mt-auto',
          )}
        >
          <LogOut size={18} /> Sign out
        </button>
        <button
          onClick={toggle}
          className="text-muted flex items-center gap-3 rounded-2xl px-4 py-2.5 font-medium transition hover:text-[var(--text)]"
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </button>
      </aside>

      <main className="min-w-0 flex-1 px-4 pt-6 pb-32 md:px-8 md:pt-10 md:pb-12">
        <Outlet />
      </main>

      {/* Mobile bottom bar with a floating camera button */}
      <nav className="card fixed inset-x-3 bottom-3 z-40 flex items-center justify-around !rounded-2xl px-2 py-2 md:hidden">
        {NAV.slice(0, 2).map((item) => (
          <MobileLink key={item.to} {...item} to={withMonth(item.to)} />
        ))}
        <button
          aria-label="Take a photo of a receipt"
          onClick={() => pickFiles((f) => upload.mutate(f), true)}
          className="-mt-10 flex h-16 w-16 items-center justify-center rounded-full bg-brand-600 text-white shadow-md ring-4 ring-[var(--bg)] transition active:scale-95"
        >
          <Camera size={26} />
        </button>
        <button
          onClick={() => setReviewOpen(true)}
          className="text-muted relative flex w-16 flex-col items-center gap-0.5 rounded-2xl py-1.5 text-[11px] font-semibold"
        >
          <ClipboardCheck size={20} />
          Review
          {toReview > 0 && (
            <span className="absolute top-0 right-2 rounded-full bg-brand-600 px-1.5 text-[10px] font-semibold text-white">
              {toReview}
            </span>
          )}
        </button>
        {NAV.slice(2).map((item) => (
          <MobileLink key={item.to} {...item} to={withMonth(item.to)} />
        ))}
      </nav>
      <ReviewPanel />
    </div>
  )
}

function MobileLink({
  to,
  label,
  icon: Icon,
}: (typeof NAV)[number]) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        clsx(
          'relative flex w-16 flex-col items-center gap-0.5 rounded-2xl py-1.5 text-[11px] font-semibold transition',
          isActive ? 'text-[var(--brand)]' : 'text-muted',
        )
      }
    >
      <Icon size={20} />
      {label}
    </NavLink>
  )
}
