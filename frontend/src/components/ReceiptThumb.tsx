import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'
import { useState } from 'react'

import { api } from '../api'

/** Receipt photo that opens full screen when tapped. */
export function ReceiptThumb({ id, className }: { id: number; className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={clsx('overflow-hidden rounded-2xl bg-[var(--border)]', className)}
        aria-label="View the receipt photo"
      >
        <img src={api.receiptImageUrl(id)} alt="Receipt" className="h-full w-full object-cover object-top" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur"
          >
            <button className="absolute top-4 right-4 rounded-full bg-white/10 p-2 text-white" aria-label="Close">
              <X />
            </button>
            <motion.img
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              src={api.receiptImageUrl(id)}
              alt="Receipt"
              className="max-h-full max-w-full rounded-2xl"
            />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
