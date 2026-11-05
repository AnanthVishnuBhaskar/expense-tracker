import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { api } from '../api'
import { setReviewOpen } from './review'

export function useUpload() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (files: File[]) => api.uploadReceipts(files),
    onSuccess: (receipts) => {
      qc.invalidateQueries({ queryKey: ['receipts'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
      const repeats = receipts.filter((r) => r.already_uploaded)
      for (const r of repeats) {
        const when = new Date(r.uploaded_at).toLocaleString(undefined, {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
          hour: 'numeric',
          minute: '2-digit',
        })
        const where = r.status === 'saved' ? 'It is already saved as an expense.' : 'It is waiting for your review.'
        toast.warning(`You already uploaded this receipt on ${when}.`, { description: where, duration: 8000 })
      }
      // The panel shows each new receipt being read, then asks you to confirm it.
      if (repeats.length < receipts.length || repeats.some((r) => r.status !== 'saved')) setReviewOpen(true)
    },
    onError: (e: Error) => toast.error(e.message),
  })
}

export function pickFiles(onPick: (files: File[]) => void, camera = false) {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*,.heic,.heif'
  input.multiple = !camera
  if (camera) input.setAttribute('capture', 'environment')
  input.onchange = () => input.files?.length && onPick(Array.from(input.files))
  input.click()
}
