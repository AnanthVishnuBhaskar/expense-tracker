import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Globe2, Lock, Mail, ScanLine, ShieldCheck, User } from 'lucide-react'
import { useEffect, useState } from 'react'

import { api } from '../api'
import { landingPath } from '../lib/startPage'

export function AuthGate({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient()
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['me'],
    queryFn: api.me,
    staleTime: Infinity,
    retry: 1,
  })

  useEffect(() => {
    const onExpired = () => qc.invalidateQueries({ queryKey: ['me'] })
    window.addEventListener('auth:required', onExpired)
    return () => window.removeEventListener('auth:required', onExpired)
  }, [qc])

  if (isError) {
    return (
      <div className="flex min-h-dvh items-center justify-center p-6">
        <div className="card w-full max-w-sm p-8 text-center">
          <h1 className="text-lg font-semibold">Can't reach the server</h1>
          <p className="text-muted mt-2 text-sm">
            Make sure the backend is running (<code>uv run uvicorn app.main:app --port 8001</code> in the
            backend folder), then try again.
          </p>
          <button onClick={() => refetch()} disabled={isFetching} className="btn-primary mx-auto mt-6 px-5 py-2.5">
            {isFetching ? 'Trying…' : 'Try again'}
          </button>
        </div>
      </div>
    )
  }
  if (isLoading || !data) return null
  if (data.authenticated) return <>{children}</>
  return <AuthPage signupOpen={data.signup_open} />
}

function AuthPage({ signupOpen }: { signupOpen: boolean }) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const signingUp = mode === 'signup'
  const submit = useMutation({
    mutationFn: () => (signingUp ? api.signup({ name, email, password }) : api.login({ email, password })),
    onSuccess: (me) => {
      // Drop anything cached from an earlier session, then let the app in.
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' })
      // Open where you left off, or the Overview if that's what you chose in Settings.
      window.history.replaceState(null, '', landingPath(me.email ?? ''))
      qc.setQueryData(['me'], me)
    },
  })
  const ready = email && password && (!signingUp || name)
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-brand-700 p-12 text-brand-50 lg:flex">
        <div className="pointer-events-none absolute -right-24 -bottom-24 h-96 w-96 rounded-full bg-brand-500/40 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <img src="/favicon.svg" className="h-9 w-9 rounded-lg ring-1 ring-white/20" alt="" />
          <span className="text-lg font-semibold tracking-tight">Receipts</span>
        </div>
        <div className="relative max-w-lg">
          <h2 className="text-3xl leading-tight font-semibold tracking-tight text-white">
            Every receipt, read and filed for you.
          </h2>
          <p className="mt-4 text-brand-100/80">
            Snap a photo. Claude reads the merchant, items and taxes in any currency, and you
            confirm before anything is saved.
          </p>
          <ul className="mt-8 space-y-3 text-sm text-brand-100/90">
            {[
              [ScanLine, 'Line items, taxes and payments extracted'],
              [Globe2, 'Any country, any currency'],
              [ShieldCheck, 'Nothing is saved until you confirm it'],
            ].map(([Icon, text]) => {
              const I = Icon as typeof Lock
              return (
                <li key={text as string} className="flex items-center gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10">
                    <I size={16} />
                  </span>
                  {text as string}
                </li>
              )
            })}
          </ul>
        </div>
        <p className="relative text-xs text-brand-100/60">Your receipts are private to your account.</p>
      </aside>

      <main className="flex items-center justify-center p-6">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="w-full max-w-sm"
        >
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <img src="/favicon.svg" className="h-9 w-9" alt="" />
            <span className="text-lg font-semibold tracking-tight">Receipts</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {signingUp ? 'Create your account' : 'Welcome back'}
          </h1>
          <p className="text-muted mt-1.5 text-sm">
            {signingUp ? 'Start tracking your receipts in a minute.' : 'Sign in to review and track your expenses.'}
          </p>
          <form
            className="mt-8 space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (ready) submit.mutate()
            }}
          >
            {signingUp && (
              <Field icon={User} label="Name">
                <input
                  autoFocus
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  className="field !pl-9"
                />
              </Field>
            )}
            <Field icon={Mail} label="Email">
              <input
                type="email"
                autoFocus={!signingUp}
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="field !pl-9"
              />
            </Field>
            <Field icon={Lock} label="Password" hint={signingUp ? 'At least 8 characters' : undefined}>
              <input
                type="password"
                autoComplete={signingUp ? 'new-password' : 'current-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={signingUp ? 'Choose a password' : 'Enter your password'}
                className="field !pl-9"
              />
            </Field>
            {submit.error && <p className="text-bad text-sm font-medium">{submit.error.message}</p>}
            <button disabled={submit.isPending || !ready} className="btn-primary w-full py-2.5">
              {submit.isPending
                ? signingUp
                  ? 'Creating account…'
                  : 'Signing in…'
                : signingUp
                  ? 'Create account'
                  : 'Sign in'}
            </button>
          </form>
          {signupOpen && (
            <p className="text-muted mt-6 text-center text-sm">
              {signingUp ? 'Already have an account?' : 'New here?'}{' '}
              <button
                type="button"
                onClick={() => {
                  setMode(signingUp ? 'signin' : 'signup')
                  submit.reset()
                }}
                className="font-medium text-[var(--brand)] hover:underline"
              >
                {signingUp ? 'Sign in' : 'Create an account'}
              </button>
            </p>
          )}
        </motion.div>
      </main>
    </div>
  )
}

function Field({
  icon: Icon,
  label,
  hint,
  children,
}: {
  icon: typeof Lock
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-baseline justify-between text-sm font-medium">
        {label}
        {hint && <span className="text-muted text-xs font-normal">{hint}</span>}
      </span>
      <div className="relative">
        <Icon size={16} className="text-muted pointer-events-none absolute top-1/2 left-3 -translate-y-1/2" />
        {children}
      </div>
    </label>
  )
}
