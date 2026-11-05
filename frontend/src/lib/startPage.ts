import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null // storage unavailable
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage unavailable */
  }
}

const lastKey = (email: string) => `last-view:${email}`

/** After signing in, reopen the page you were last on (with its month or period), else the Overview. */
export function landingPath(email: string): string {
  const last = read(lastKey(email))
  return last?.startsWith('/') ? last : '/'
}

/** Remembers the current page and its filters (month, day) for this account. */
export function useRememberView(email: string | null | undefined) {
  const { pathname, search } = useLocation()
  useEffect(() => {
    if (email) write(lastKey(email), pathname + search)
  }, [email, pathname, search])
}

/** A choice kept on this device, e.g. the Expenses list/photo toggle. */
export function useStoredChoice<T extends string>(key: string, options: readonly T[], fallback: T) {
  const [value, setValue] = useState<T>(() => {
    const saved = read(key)
    return options.includes(saved as T) ? (saved as T) : fallback
  })
  const set = (next: T) => {
    setValue(next)
    write(key, next)
  }
  return [value, set] as const
}
