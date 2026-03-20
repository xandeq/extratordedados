import { Info, X } from 'lucide-react'
import { useState } from 'react'

interface InfoBoxProps {
  title: string
  description: string
  steps?: string[]
  storageKey?: string
}

export default function InfoBox({ title, description, steps, storageKey }: InfoBoxProps) {
  const [dismissed, setDismissed] = useState(() => {
    if (!storageKey) return false
    try { return localStorage.getItem(`infobox_${storageKey}`) === '1' } catch { return false }
  })

  if (dismissed) return null

  const handleDismiss = () => {
    setDismissed(true)
    if (storageKey) {
      try { localStorage.setItem(`infobox_${storageKey}`, '1') } catch {}
    }
  }

  return (
    <div className="flex gap-3 px-4 py-3.5 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 rounded-xl text-sm">
      <Info className="w-4 h-4 text-blue-500 dark:text-blue-400 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-blue-800 dark:text-blue-200">{title}</p>
        <p className="text-blue-700 dark:text-blue-300 mt-0.5 leading-relaxed">{description}</p>
        {steps && steps.length > 0 && (
          <ol className="mt-2 space-y-0.5 text-blue-600 dark:text-blue-400">
            {steps.map((step, i) => (
              <li key={i} className="flex gap-1.5">
                <span className="font-bold shrink-0">{i + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        className="text-blue-400 hover:text-blue-600 dark:hover:text-blue-200 transition-colors shrink-0 mt-0.5"
        title="Fechar"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}
