import { X, Zap, Check, ArrowRight } from 'lucide-react'
import Link from 'next/link'

interface UpgradeModalProps {
  onClose: () => void
  reason?: 'export' | 'filters' | 'generic'
  currentPlan?: string
}

const REASONS: Record<string, { title: string; description: string }> = {
  export: {
    title: 'Limite de exportações atingido',
    description: 'Você usou todas as exportações do seu plano neste mês.',
  },
  filters: {
    title: 'Filtros salvos disponíveis no Pro',
    description: 'Salve e reutilize filtros personalizados com o plano Pro.',
  },
  generic: {
    title: 'Você atingiu o limite do plano Free',
    description: 'Faça upgrade e tenha acesso a mais recursos.',
  },
}

const PRO_BENEFITS = [
  '5.000 leads por mês',
  '20 exportações por mês',
  'Até 5 filtros salvos',
  'Exportação em todos os formatos',
  'Suporte prioritário',
]

export default function UpgradeModal({ onClose, reason = 'generic', currentPlan = 'free' }: UpgradeModalProps) {
  const info = REASONS[reason] ?? REASONS.generic

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md animate-fade-in">
        {/* Header */}
        <div className="relative p-6 pb-4">
          <button
            onClick={onClose}
            className="absolute top-4 right-4 p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          >
            <X className="w-4 h-4 text-gray-400" />
          </button>

          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center flex-shrink-0">
              <Zap className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-base font-bold text-gray-900 dark:text-white leading-tight">
                {info.title}
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {info.description}
              </p>
            </div>
          </div>
        </div>

        {/* Plan comparison */}
        <div className="px-6 pb-2">
          <div className="grid grid-cols-2 gap-3">
            {/* Free - current */}
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 bg-gray-50 dark:bg-gray-700/30">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                  Plano atual
                </span>
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-gray-200 dark:bg-gray-600 text-gray-600 dark:text-gray-300">
                  Free
                </span>
              </div>
              <p className="text-xl font-bold text-gray-900 dark:text-white mb-3">R$0</p>
              <ul className="space-y-1.5">
                <li className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
                  <span className="w-3.5 h-3.5 rounded-full bg-gray-300 dark:bg-gray-600 flex-shrink-0" />
                  100 leads/mês
                </li>
                <li className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
                  <span className="w-3.5 h-3.5 rounded-full bg-gray-300 dark:bg-gray-600 flex-shrink-0" />
                  1 exportação/mês
                </li>
                <li className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
                  <span className="w-3.5 h-3.5 rounded-full bg-gray-300 dark:bg-gray-600 flex-shrink-0" />
                  Sem filtros salvos
                </li>
              </ul>
            </div>

            {/* Pro - target */}
            <div className="rounded-xl border-2 border-blue-500 p-4 bg-blue-50 dark:bg-blue-900/20 relative">
              <div className="absolute -top-2.5 left-1/2 -translate-x-1/2">
                <span className="text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-blue-600 text-white uppercase tracking-wide">
                  Recomendado
                </span>
              </div>
              <div className="flex items-center justify-between mb-3 mt-1">
                <span className="text-xs font-semibold text-blue-700 dark:text-blue-400 uppercase tracking-wide">
                  Upgrade
                </span>
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300">
                  Pro
                </span>
              </div>
              <p className="text-xl font-bold text-gray-900 dark:text-white mb-3">
                R$99<span className="text-xs font-normal text-gray-500">/mês</span>
              </p>
              <ul className="space-y-1.5">
                {PRO_BENEFITS.slice(0, 3).map((b) => (
                  <li key={b} className="text-xs text-blue-700 dark:text-blue-300 flex items-center gap-1.5 font-medium">
                    <Check className="w-3.5 h-3.5 flex-shrink-0" />
                    {b}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        {/* CTA */}
        <div className="p-6 pt-4 flex flex-col gap-2">
          <Link
            href="/plans"
            onClick={onClose}
            className="flex items-center justify-center gap-2 w-full py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold text-sm transition-colors shadow-sm"
          >
            <Zap className="w-4 h-4" />
            Torne-se Pro
            <ArrowRight className="w-4 h-4" />
          </Link>
          <button
            onClick={onClose}
            className="w-full py-2.5 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
          >
            Talvez depois
          </button>
        </div>
      </div>
    </div>
  )
}
