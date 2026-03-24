import { useState } from 'react'
import { X, Download, Loader } from 'lucide-react'
import { useToast } from './Toast'
import { API_URL } from '../lib/api'

interface ClientExportModalProps {
  filters: Record<string, string | boolean | number>
  leadsCount: number
  creditBalance: number | null
  onClose: () => void
  onInsufficientCredits: () => void
  onExportSuccess: (exportedCount: number, remainingBalance: number) => void
}

export default function ClientExportModal({
  filters,
  leadsCount,
  creditBalance,
  onClose,
  onInsufficientCredits,
  onExportSuccess,
}: ClientExportModalProps) {
  const { addToast } = useToast()
  const [format, setFormat] = useState<'csv' | 'json'>('csv')
  const [exporting, setExporting] = useState(false)

  const balance = creditBalance ?? 0
  const exportCount = Math.min(leadsCount, balance)
  const canExport = exportCount > 0

  const handleExport = async () => {
    setExporting(true)
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('token') : ''
      const params = new URLSearchParams()
      params.set('format', format)
      Object.entries(filters).forEach(([k, v]) => {
        if (v !== '' && v !== false && v !== undefined && v !== null) {
          params.set(k, String(v))
        }
      })

      const resp = await fetch(`${API_URL}/api/client/leads/export?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      })

      if (resp.status === 402) {
        onClose()
        onInsufficientCredits()
        return
      }

      if (!resp.ok) {
        const errText = await resp.text().catch(() => 'Erro desconhecido')
        console.error('Export error response:', errText)
        addToast('Erro ao exportar. Tente novamente ou fale com o suporte.', 'error')
        return
      }

      // Trigger file download
      const blob = await resp.blob()
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, '')
      const filename = `leads_${today}.${format}`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)

      // Estimate remaining balance (exact count from CSV is complex)
      const remainingEstimate = Math.max(0, balance - exportCount)
      addToast(
        `${exportCount} leads exportados com sucesso. Saldo restante: ${remainingEstimate} créditos.`,
        'success'
      )
      onExportSuccess(exportCount, remainingEstimate)
      onClose()
    } catch (e) {
      console.error('Export error', e)
      addToast('Erro ao exportar. Tente novamente ou fale com o suporte.', 'error')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-xl w-full max-w-md">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Exportar Leads</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
            disabled={exporting}
          >
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4">
          {/* Credit warning */}
          {canExport ? (
            <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 p-4">
              <p className="text-sm text-blue-800 dark:text-blue-300">
                Esta exportação debitará{' '}
                <span className="font-bold">{exportCount} crédito{exportCount !== 1 ? 's' : ''}</span>{' '}
                do seu saldo.
              </p>
              {leadsCount > balance && (
                <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
                  Seu saldo ({balance} créditos) limita esta exportação a {exportCount} leads.
                </p>
              )}
            </div>
          ) : (
            <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-4">
              <p className="text-sm text-amber-800 dark:text-amber-300">
                Você não tem créditos suficientes. Faça upgrade para continuar.
              </p>
            </div>
          )}

          {/* Format selector */}
          <div>
            <p className="text-xs font-bold text-gray-700 dark:text-gray-300 mb-2 uppercase tracking-wide">
              Formato
            </p>
            <div className="flex gap-3">
              {(['csv', 'json'] as const).map((f) => (
                <label
                  key={f}
                  className={`flex items-center gap-2 cursor-pointer px-4 py-2 rounded-lg border text-sm font-bold transition-colors ${
                    format === f
                      ? 'border-blue-600 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                      : 'border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-500'
                  }`}
                >
                  <input
                    type="radio"
                    name="format"
                    value={f}
                    checked={format === f}
                    onChange={() => setFormat(f)}
                    className="sr-only"
                  />
                  {f.toUpperCase()}
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-6 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={onClose}
            disabled={exporting}
            className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={handleExport}
            disabled={!canExport || exporting}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-bold rounded-lg transition-colors"
          >
            {exporting ? (
              <>
                <Loader className="w-4 h-4 animate-spin" />
                Exportando...
              </>
            ) : (
              <>
                <Download className="w-4 h-4" />
                Exportar {format.toUpperCase()}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
