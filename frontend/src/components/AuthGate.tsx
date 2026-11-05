import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Globe2, Lock, Mail, MailCheck, ScanLine, ShieldCheck, User } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { api, type AuthStatus } from '../api'
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
            The app's server isn't answering. Check that it's running, then try again.
          </p>
          <button onClick={() => refetch()} disabled={isFetching} className="btn-primary mx-auto mt-6 px-5 py-2.5">
            {isFetching ? 'Trying…' : 'Try again'}
          </button>
        </div>
      </div>
    )
  }
  if (isLoading || !data) return null
  // Links from our emails open these pages, signed in or not.
  const link = emailLink()
  if (link?.path === '/verify-email') return <VerifyEmail token={link.token} />
  if (link?.path === '/reset-password') return <ResetPassword token={link.token} />
  if (data.authenticated) return <>{children}</>
  return <AuthPage status={data} />
}

function emailLink() {
  const { pathname, search } = window.location
  if (pathname !== '/verify-email' && pathname !== '/reset-password') return null
  return {
    path: pathname,
    token: new URLSearchParams(search).get('token') ?? '',
  }
}

/** Let a newly signed-in account into the app, dropping anything cached from before. */
function useEnter() {
  const qc = useQueryClient()
  return (me: AuthStatus, path?: string) => {
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' })
    // Open where you left off, or the Overview the first time.
    window.history.replaceState(null, '', path ?? landingPath(me.email ?? ''))
    qc.setQueryData(['me'], me)
  }
}

type View = 'signin' | 'signup' | 'forgot' | { sent: 'verify' | 'reset'; to: string }

/** An error the server sent back after a Google/Microsoft/Apple sign-in, shown once. */
const NOTICES: Record<string, string> = {
  'account-deleted': 'Your account and everything in it were deleted.',
}

/** A message handed over in the address, e.g. after a provider sign-in fails or an account is closed. */
function useReturned() {
  const [returned] = useState(() => {
    const q = new URLSearchParams(window.location.search)
    return { error: q.get('auth_error'), notice: NOTICES[q.get('notice') ?? ''] ?? null }
  })
  useEffect(() => {
    if (returned.error || returned.notice) window.history.replaceState(null, '', '/')
  }, [returned])
  return returned
}

function AuthPage({ status }: { status: AuthStatus }) {
  const enter = useEnter()
  const { error: returnedError, notice: returnedNotice } = useReturned()
  const [view, setView] = useState<View>('signin')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const signingUp = view === 'signup'
  const forgot = view === 'forgot'
  const submit = useMutation({
    mutationFn: async (): Promise<AuthStatus | null> => {
      if (forgot) {
        await api.forgotPassword(email)
        return null
      }
      return signingUp ? api.signup({ name, email, password }) : api.login({ email, password, remember })
    },
    onSuccess: (me) => {
      if (me === null) setView({ sent: 'reset', to: email.trim() })
      else if (me.verification_sent_to) setView({ sent: 'verify', to: me.verification_sent_to })
      else enter(me)
    },
  })
  const go = (next: View) => {
    setView(next)
    submit.reset()
  }

  if (typeof view === 'object') {
    return (
      <AuthShell>
        <CheckInbox kind={view.sent} to={view.to} onBack={() => go('signin')} />
      </AuthShell>
    )
  }
  const ready = forgot ? email : email && password && (!signingUp || name)
  // Email sign-ups are always confirmed by email, so without email only the buttons remain.
  const emailForm = !signingUp || status.email_enabled
  const social = status.social_providers
  const title = signingUp ? 'Create your account' : forgot ? 'Reset your password' : 'Welcome back'
  const subtitle = signingUp
    ? emailForm
      ? "We'll email you a link to confirm your address."
      : 'Pick an account to sign up with.'
    : forgot
      ? "Enter your account's email and we'll send you a link to choose a new password."
      : 'Sign in to review and track your expenses.'
  const action = signingUp ? 'Create account' : forgot ? 'Send reset link' : 'Sign in'
  const busy = signingUp ? 'Creating account…' : forgot ? 'Sending…' : 'Signing in…'
  return (
    <AuthShell>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="text-muted mt-1.5 text-sm">{subtitle}</p>
      {returnedError && !submit.error && <p className="text-bad mt-6 text-sm font-medium">{returnedError}</p>}
      {returnedNotice && !submit.error && <p className="text-muted mt-6 text-sm font-medium">{returnedNotice}</p>}
      {!forgot && social.length > 0 && (
        <div className="mt-8 space-y-2.5">
          {social.map((p) => (
            <a
              key={p}
              href={`/api/auth/${p}/start${remember ? '?remember=true' : ''}`}
              className="btn-secondary w-full gap-2.5 py-2.5"
            >
              <ProviderLogo provider={p} />
              Continue with {PROVIDER_LABEL[p]}
            </a>
          ))}
          {emailForm && (
            <div className="text-muted flex items-center gap-3 pt-3 text-xs">
              <span className="h-px flex-1 bg-[var(--border)]" />
              or with email
              <span className="h-px flex-1 bg-[var(--border)]" />
            </div>
          )}
        </div>
      )}
      {emailForm && (
        <form
          className={social.length > 0 && !forgot ? 'mt-4 space-y-4' : 'mt-8 space-y-4'}
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
              autoComplete={signingUp ? 'email' : 'username'}
              name="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="field !pl-9"
            />
          </Field>
          {!forgot && (
            <Field
              icon={Lock}
              label="Password"
              hint={signingUp ? 'At least 8 characters' : undefined}
              action={
                !signingUp && status.email_enabled ? (
                  <button type="button" onClick={() => go('forgot')} className="link text-xs">
                    Forgot password?
                  </button>
                ) : undefined
              }
            >
              <input
                type="password"
                autoComplete={signingUp ? 'new-password' : 'current-password'}
                name="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={signingUp ? 'Choose a password' : 'Enter your password'}
                className="field !pl-9"
              />
            </Field>
          )}
          {!signingUp && !forgot && (
            <label className="text-muted flex cursor-pointer items-center gap-2 text-sm select-none">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="h-4 w-4 accent-[var(--brand)]"
              />
              Keep me signed in
              <span className="text-xs">(not on shared computers)</span>
            </label>
          )}
          {submit.error && <p className="text-bad text-sm font-medium">{submit.error.message}</p>}
          <button disabled={submit.isPending || !ready} className="btn-primary w-full py-2.5">
            {submit.isPending ? busy : action}
          </button>
        </form>
      )}
      {!emailForm && social.length === 0 && (
        <p className="text-muted mt-8 text-sm">New accounts aren't available yet.</p>
      )}
      {forgot ? (
        <p className="text-muted mt-6 text-center text-sm">
          Remembered it?{' '}
          <button type="button" onClick={() => go('signin')} className="link">
            Sign in
          </button>
        </p>
      ) : (
        status.signup_open && (
          <p className="text-muted mt-6 text-center text-sm">
            {signingUp ? 'Already have an account?' : 'New here?'}{' '}
            <button type="button" onClick={() => go(signingUp ? 'signin' : 'signup')} className="link">
              {signingUp ? 'Sign in' : 'Create an account'}
            </button>
          </p>
        )
      )}
    </AuthShell>
  )
}

const PROVIDER_LABEL = {
  google: 'Google',
  microsoft: 'Microsoft',
  apple: 'Apple',
} as const

function ProviderLogo({ provider }: { provider: keyof typeof PROVIDER_LABEL }) {
  if (provider === 'google') {
    return (
      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
        <path
          fill="#EA4335"
          d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
        />
        <path
          fill="#4285F4"
          d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
        />
        <path
          fill="#FBBC05"
          d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
        />
        <path
          fill="#34A853"
          d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
        />
      </svg>
    )
  }
  if (provider === 'microsoft') {
    return (
      <svg width="16" height="16" viewBox="0 0 21 21" aria-hidden>
        <rect x="1" y="1" width="9" height="9" fill="#F25022" />
        <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
        <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
        <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
      </svg>
    )
  }
  return (
    <svg width="16" height="18" viewBox="0 0 384 512" aria-hidden fill="currentColor">
      <path d="M318.7 268.7c-.2-36.7 16.4-64.4 50-84.8-18.8-26.9-47.2-41.7-84.7-44.6-35.5-2.8-74.3 20.7-88.5 20.7-15 0-49.4-19.7-76.4-19.7C63.3 141.2 4 184.8 4 273.5q0 39.3 14.4 81.2c12.8 36.7 59 126.7 107.2 125.2 25.2-.6 43-17.9 75.8-17.9 31.8 0 48.3 17.9 76.4 17.9 48.6-.7 90.4-82.5 102.6-119.3-65.2-30.7-61.7-90-61.7-91.9zm-56.6-164.2c27.3-32.4 24.8-61.9 24-72.5-24.1 1.4-52 16.4-67.9 34.9-17.5 19.8-27.8 44.3-25.6 71.9 26.1 2 49.9-11.4 69.5-34.3z" />
    </svg>
  )
}

function CheckInbox({ kind, to, onBack }: { kind: 'verify' | 'reset'; to: string; onBack: () => void }) {
  const resend = useMutation({
    mutationFn: () => (kind === 'verify' ? api.resendVerification(to) : api.forgotPassword(to)),
  })
  return (
    <div>
      <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-sunken text-[var(--brand)]">
        <MailCheck size={22} />
      </span>
      <h1 className="mt-6 text-2xl font-semibold tracking-tight">Check your inbox</h1>
      <p className="text-muted mt-2 text-sm leading-relaxed">
        {kind === 'verify' ? 'We sent a link to confirm your email to ' : "If there's an account for "}
        <span className="font-medium text-[var(--text)]">{to}</span>
        {kind === 'verify'
          ? '. Open it to finish creating your account.'
          : ", we've sent it a link to choose a new password."}
      </p>
      <p className="text-muted mt-4 text-sm">
        Nothing there? Check your spam folder, or{' '}
        <button
          type="button"
          disabled={resend.isPending || resend.isSuccess}
          onClick={() => resend.mutate()}
          className="link disabled:opacity-60"
        >
          {resend.isSuccess ? 'sent again' : resend.isPending ? 'sending…' : 'send it again'}
        </button>
        .
      </p>
      {resend.error && <p className="text-bad mt-3 text-sm font-medium">{resend.error.message}</p>}
      <button type="button" onClick={onBack} className="btn-secondary mt-8 w-full py-2.5">
        Back to sign in
      </button>
    </div>
  )
}

function VerifyEmail({ token }: { token: string }) {
  const enter = useEnter()
  const verify = useMutation({
    mutationFn: () => api.verifyEmail(token),
    onSuccess: (me) => enter(me, '/'),
  })
  const started = useRef(false)
  useEffect(() => {
    // Links work once, so make sure this only ever runs once (StrictMode mounts twice).
    if (started.current) return
    started.current = true
    verify.mutate()
  }, [verify])
  return (
    <AuthShell>
      {verify.isError ? (
        <LinkProblem message={verify.error.message} />
      ) : (
        <>
          <h1 className="text-2xl font-semibold tracking-tight">Confirming your email…</h1>
          <p className="text-muted mt-2 text-sm">This takes a second.</p>
        </>
      )}
    </AuthShell>
  )
}

function ResetPassword({ token }: { token: string }) {
  const enter = useEnter()
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const reset = useMutation({
    mutationFn: () => api.resetPassword(token, password),
    onSuccess: (me) => enter(me, '/'),
  })
  const mismatch = again.length > 0 && again !== password
  const expired = reset.error?.message.includes('expired')
  if (expired) {
    return (
      <AuthShell>
        <LinkProblem message={reset.error!.message} />
      </AuthShell>
    )
  }
  return (
    <AuthShell>
      <h1 className="text-2xl font-semibold tracking-tight">Choose a new password</h1>
      <p className="text-muted mt-1.5 text-sm">You'll be signed out on your other devices.</p>
      <form
        className="mt-8 space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (password && password === again) reset.mutate()
        }}
      >
        <Field icon={Lock} label="New password" hint="At least 8 characters">
          <input
            type="password"
            autoFocus
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="field !pl-9"
          />
        </Field>
        <Field icon={Lock} label="Type it again">
          <input
            type="password"
            autoComplete="new-password"
            value={again}
            onChange={(e) => setAgain(e.target.value)}
            className="field !pl-9"
          />
        </Field>
        {mismatch && <p className="text-bad text-sm font-medium">The two passwords don't match.</p>}
        {reset.error && <p className="text-bad text-sm font-medium">{reset.error.message}</p>}
        <button disabled={reset.isPending || !password || password !== again} className="btn-primary w-full py-2.5">
          {reset.isPending ? 'Saving…' : 'Save and sign in'}
        </button>
      </form>
    </AuthShell>
  )
}

function LinkProblem({ message }: { message: string }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">That link didn't work</h1>
      <p className="text-muted mt-2 text-sm">{message}</p>
      <a href="/" className="btn-primary mt-8 flex w-full justify-center py-2.5">
        Go to sign in
      </a>
    </div>
  )
}

function AuthShell({ children }: { children: React.ReactNode }) {
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
            Snap a photo. Claude reads the merchant, items and taxes in any currency, and you confirm before anything is
            saved.
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
          {children}
        </motion.div>
      </main>
    </div>
  )
}

function Field({
  icon: Icon,
  label,
  hint,
  action,
  children,
}: {
  icon: typeof Lock
  label: string
  hint?: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between text-sm font-medium">
        <span>{label}</span>
        {hint && <span className="text-muted text-xs font-normal">{hint}</span>}
        {action}
      </div>
      <label className="relative block">
        <span className="sr-only">{label}</span>
        <Icon size={16} className="text-muted pointer-events-none absolute top-1/2 left-3 -translate-y-1/2" />
        {children}
      </label>
    </div>
  )
}
