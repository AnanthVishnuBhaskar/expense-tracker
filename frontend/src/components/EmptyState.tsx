import { motion } from 'framer-motion'
import { Camera, ImagePlus } from 'lucide-react'

import { pickFiles, useUpload } from '../lib/useUpload'

export function EmptyState({ title, body }: { title: string; body: string }) {
  const upload = useUpload()
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      className="card flex flex-col items-center px-6 py-14 text-center"
    >
      <div className="relative mb-6">
        <div className="absolute inset-0 rounded-full bg-brand-200/40 blur-2xl dark:bg-brand-700/20" />
        <div className="relative flex h-20 w-20 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 dark:bg-brand-700/30 dark:text-brand-300">
          <Camera size={34} />
        </div>
      </div>
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="text-muted mt-2 max-w-sm">{body}</p>
      {/* Phones get the camera first. */}
      <div className="mt-6 hidden flex-wrap justify-center gap-3 [@media(pointer:coarse)]:flex">
        <button
          onClick={() => pickFiles((f) => upload.mutate(f), true)}
          className="btn-primary px-5 py-2.5"
        >
          <Camera size={18} /> Take a photo
        </button>
        <button
          onClick={() => pickFiles((f) => upload.mutate(f))}
          className="card flex items-center gap-2 !rounded-xl px-5 py-2.5 font-semibold"
        >
          <ImagePlus size={18} /> From your library
        </button>
      </div>
      {/* On a computer the sidebar already has Add receipts, so just point to it. */}
      <p className="text-muted mt-4 text-sm [@media(pointer:coarse)]:hidden">
        Use <span className="font-medium text-[var(--text)]">Add receipts</span>, or drop photos
        anywhere on this page.
      </p>
    </motion.div>
  )
}
