import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { api } from '../api'

export const currencyName = new Intl.DisplayNames(undefined, { type: 'currency' })
export const ALL_CURRENCIES = Intl.supportedValuesOf('currency')

/** Changing the home currency converts every expense and budget, then refreshes everything. */
export function useChangeHomeCurrency() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (home_currency: string) => api.updateSettings({ home_currency }),
    onSuccess: () => {
      qc.invalidateQueries()
      toast.success('Done. Your expenses and budgets were converted.')
    },
    onError: (e) => toast.error(e.message),
  })
}

/** Every currency, with the given one first. */
export function currencyOptions(first?: string) {
  const codes = first ? [first, ...ALL_CURRENCIES.filter((c) => c !== first)] : ALL_CURRENCIES
  return codes.map((c) => ({ value: c, label: currencyName.of(c) ?? c, hint: c }))
}
