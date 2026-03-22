import React from 'react'
import { AlertCircle, TrendingUp, Lock, Unlock } from 'lucide-react'

interface PlanCardProps {
  plan: string
  leadsViewed: number
  leadsLimit: number
  exportsUsed: number
  exportsLimit: number
  onUpgrade?: () => void
}

export const PlanCard: React.FC<PlanCardProps> = ({
  plan,
  leadsViewed,
  leadsLimit,
  exportsUsed,
  exportsLimit,
  onUpgrade,
}) => {
  const leadsPercent = leadsLimit > 0 ? (leadsViewed / leadsLimit) * 100 : 0
  const exportsPercent = exportsLimit > 0 ? (exportsUsed / exportsLimit) * 100 : 0

  const leadsWarning = leadsPercent >= 80
  const exportsWarning = exportsPercent >= 80
  const leadsExceeded = leadsPercent >= 100
  const exportsExceeded = exportsPercent >= 100

  const planDisplayName = {
    free: 'Plano Grátis',
    pro: 'Plano Pro',
    enterprise: 'Plano Enterprise',
  }[plan] || plan

  const planColor = {
    free: 'from-gray-400 to-gray-600',
    pro: 'from-blue-400 to-blue-600',
    enterprise: 'from-purple-400 to-purple-600',
  }[plan] || 'from-gray-400 to-gray-600'

  return (
    <div className={`bg-gradient-to-r ${planColor} rounded-lg p-4 text-white shadow-md`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-bold">{planDisplayName}</h3>
          <p className="text-sm opacity-90">
            {plan === 'enterprise' ? 'Sem limites' : 'Com limites mensais'}
          </p>
        </div>
        {exportsExceeded || leadsExceeded ? (
          <Lock className="w-6 h-6" />
        ) : (
          <Unlock className="w-6 h-6" />
        )}
      </div>

      {/* Leads Usage */}
      <div className="mb-4">
        <div className="flex justify-between items-center mb-1">
          <span className="text-sm font-medium">Leads Visualizados</span>
          <span className="text-sm">
            {leadsViewed} / {leadsLimit === 999999 ? '∞' : leadsLimit}
          </span>
        </div>
        <div className="w-full bg-white/30 rounded-full h-2">
          <div
            className={`h-2 rounded-full transition-all ${
              leadsExceeded ? 'bg-red-500' : leadsWarning ? 'bg-yellow-400' : 'bg-green-400'
            }`}
            style={{ width: `${Math.min(leadsPercent, 100)}%` }}
          />
        </div>
        {leadsWarning && (
          <p className="text-xs mt-1 opacity-90 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            {leadsExceeded ? 'Limite atingido' : 'Próximo do limite'}
          </p>
        )}
      </div>

      {/* Exports Usage */}
      <div className="mb-4">
        <div className="flex justify-between items-center mb-1">
          <span className="text-sm font-medium">Exportações</span>
          <span className="text-sm">
            {exportsUsed} / {exportsLimit === 999999 ? '∞' : exportsLimit}
          </span>
        </div>
        <div className="w-full bg-white/30 rounded-full h-2">
          <div
            className={`h-2 rounded-full transition-all ${
              exportsExceeded ? 'bg-red-500' : exportsWarning ? 'bg-yellow-400' : 'bg-green-400'
            }`}
            style={{ width: `${Math.min(exportsPercent, 100)}%` }}
          />
        </div>
        {exportsWarning && (
          <p className="text-xs mt-1 opacity-90 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            {exportsExceeded ? 'Limite atingido' : 'Próximo do limite'}
          </p>
        )}
      </div>

      {/* CTA Button */}
      {(exportsExceeded || leadsExceeded || (leadsWarning && onUpgrade)) && (
        <button
          onClick={onUpgrade}
          className="w-full mt-2 bg-white text-gray-900 font-semibold py-2 rounded-lg hover:bg-opacity-90 transition-all flex items-center justify-center gap-2"
        >
          <TrendingUp className="w-4 h-4" />
          Fazer Upgrade
        </button>
      )}
    </div>
  )
}
