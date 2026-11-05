import { useQuery } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'

import { api } from '../api'

// Whether the review panel is open. A tiny shared store so any page (or an upload) can open it.
let open = false
const listeners = new Set<() => void>()

export function setReviewOpen(next: boolean) {
  open = next
  listeners.forEach((l) => l())
}

export function useReviewOpen() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => open,
  )
}

/** Receipts still waiting on you: being read, ready to confirm, or needing a retake. */
export function useOpenReceipts() {
  return useQuery({
    queryKey: ['receipts', 'open'],
    queryFn: () => api.receipts('open'),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'processing') ? 1500 : 15000),
  })
}
