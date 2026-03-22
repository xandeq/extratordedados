import React, { useState } from 'react'
import { ChevronDown, LogOut, Settings, Zap } from 'lucide-react'
import { useClientPlan } from '../lib/useClientPlan'

interface UserMenuProps {
  username: string
  isAdmin: boolean
  onLogout: () => void
  onUpgrade?: () => void
}

export const UserMenu: React.FC<UserMenuProps> = ({
  username,
  isAdmin,
  onLogout,
  onUpgrade,
}) => {
  const [isOpen, setIsOpen] = useState(false)
  const { plan, usage, limits } = useClientPlan()

  const planDisplayName = {
    free: 'Grátis',
    pro: 'Pro',
    enterprise: 'Enterprise',
  }[plan || 'free'] || plan

  const planBadgeColor = {
    free: 'bg-gray-200 text-gray-800',
    pro: 'bg-blue-200 text-blue-800',
    enterprise: 'bg-purple-200 text-purple-800',
  }[plan || 'free'] || 'bg-gray-200 text-gray-800'

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
      >
        <div className="text-right">
          <div className="text-sm font-medium text-gray-900 dark:text-white">{username}</div>
          <div className={`text-xs px-2 py-0.5 rounded-full ${planBadgeColor}`}>{planDisplayName}</div>
        </div>
        <ChevronDown
          className={`w-4 h-4 text-gray-600 dark:text-gray-300 transition-transform ${
            isOpen ? 'rotate-180' : ''
          }`}
        />
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute right-0 mt-2 w-64 bg-white dark:bg-gray-800 rounded-lg shadow-lg z-50 border border-gray-200 dark:border-gray-700">
          {/* Usage Info */}
          {!isAdmin && plan && usage && limits && (
            <div className="border-b border-gray-200 dark:border-gray-700 p-4">
              <p className="text-xs text-gray-600 dark:text-gray-400 mb-2">Uso mensal</p>
              <div className="space-y-2">
                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-700 dark:text-gray-300">Leads</span>
                    <span className="text-gray-600 dark:text-gray-400">
                      {usage.leads_viewed} / {limits.leads_per_month === 999999 ? '∞' : limits.leads_per_month}
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1.5">
                    <div
                      className="bg-blue-500 h-1.5 rounded-full transition-all"
                      style={{
                        width: `${Math.min(
                          (usage.leads_viewed / limits.leads_per_month) * 100,
                          100
                        )}%`,
                      }}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-700 dark:text-gray-300">Exportações</span>
                    <span className="text-gray-600 dark:text-gray-400">
                      {usage.leads_exported} / {limits.exports_per_month === 999999 ? '∞' : limits.exports_per_month}
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1.5">
                    <div
                      className="bg-green-500 h-1.5 rounded-full transition-all"
                      style={{
                        width: `${Math.min(
                          (usage.leads_exported / limits.exports_per_month) * 100,
                          100
                        )}%`,
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Menu Items */}
          <div className="p-2">
            <a
              href="/settings"
              className="flex items-center gap-3 px-4 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              <Settings className="w-4 h-4" />
              Configurações
            </a>

            {!isAdmin && onUpgrade && plan !== 'enterprise' && (
              <button
                onClick={() => {
                  onUpgrade()
                  setIsOpen(false)
                }}
                className="w-full flex items-center gap-3 px-4 py-2 text-sm text-blue-600 dark:text-blue-400 rounded-lg hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
              >
                <Zap className="w-4 h-4" />
                Fazer Upgrade
              </button>
            )}

            <button
              onClick={() => {
                onLogout()
                setIsOpen(false)
              }}
              className="w-full flex items-center gap-3 px-4 py-2 text-sm text-red-600 dark:text-red-400 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              Sair
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
