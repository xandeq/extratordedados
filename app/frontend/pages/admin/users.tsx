import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/router'
import {
  Users, Search, ChevronDown, RefreshCw,
  CheckCircle2, AlertCircle, MoreHorizontal, Shield
} from 'lucide-react'
import api from '../../lib/api'
import { useToast } from '../../components/Toast'

interface UserUsage {
  leads_viewed: number
  leads_exported: number
  month_year: string
}

interface PlanLimits {
  leads_per_month: number
  exports_per_month: number
  price_monthly: number
}

interface AdminUser {
  id: number
  username: string
  plan: string
  created_at: string
  is_admin: boolean
  usage: UserUsage
  limits: PlanLimits
}

const PLAN_LABELS: Record<string, string> = { free: 'Grátis', pro: 'Pro', enterprise: 'Enterprise' }
const PLAN_BADGE: Record<string, string> = {
  free: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  pro: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  enterprise: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
}

function UsageBar({ used, limit, color }: { used: number; limit: number; color: string }) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0
  const barColor = pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-yellow-400' : color
  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-1.5">
        <div className={`${barColor} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
        {used}/{limit === 999999 ? '∞' : limit}
      </span>
    </div>
  )
}

function ChangePlanModal({
  user,
  plans,
  onConfirm,
  onClose,
}: {
  user: AdminUser
  plans: string[]
  onConfirm: (plan: string) => void
  onClose: () => void
}) {
  const [selected, setSelected] = useState(user.plan)

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm">
        <div className="p-5 border-b border-gray-200 dark:border-gray-700">
          <h2 className="font-semibold text-gray-900 dark:text-white">Alterar Plano</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Usuário: <strong>{user.username}</strong>
          </p>
        </div>
        <div className="p-5 space-y-2">
          {plans.map((p) => (
            <label
              key={p}
              className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                selected === p
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                  : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50'
              }`}
            >
              <input
                type="radio"
                name="plan"
                value={p}
                checked={selected === p}
                onChange={() => setSelected(p)}
                className="accent-blue-600"
              />
              <div className="flex-1">
                <span className="font-medium text-gray-900 dark:text-white">{PLAN_LABELS[p] ?? p}</span>
              </div>
              {selected === p && <CheckCircle2 className="w-4 h-4 text-blue-500" />}
            </label>
          ))}
        </div>
        <div className="px-5 pb-5 flex gap-3 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={() => onConfirm(selected)}
            disabled={selected === user.plan}
            className="px-4 py-2 text-sm font-semibold bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
          >
            Confirmar
          </button>
        </div>
      </div>
    </div>
  )
}

export default function AdminUsers() {
  const router = useRouter()
  const { addToast } = useToast()

  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [planFilter, setPlanFilter] = useState('')
  const [actionUser, setActionUser] = useState<AdminUser | null>(null)
  const [showChangePlan, setShowChangePlan] = useState(false)
  const [openMenu, setOpenMenu] = useState<number | null>(null)
  const [resetting, setResetting] = useState<number | null>(null)

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true)
      const res = await api.get('/api/admin/users')
      setUsers(res.data.users || [])
    } catch (err: unknown) {
      const status = (err as any)?.response?.status
      if (status === 401) router.push('/login')
      else if (status === 403) router.push('/dashboard')
      else addToast('Erro ao carregar usuários', 'error')
    } finally {
      setLoading(false)
    }
  }, [router, addToast])

  useEffect(() => {
    fetchUsers()
  }, [fetchUsers])

  // Close menu on outside click
  useEffect(() => {
    const handler = () => setOpenMenu(null)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [])

  const handleChangePlan = async (newPlan: string) => {
    if (!actionUser) return
    try {
      await api.put(`/api/admin/users/${actionUser.id}/plan`, { plan: newPlan })
      addToast(`Plano de ${actionUser.username} atualizado para ${PLAN_LABELS[newPlan]}`, 'success')
      setShowChangePlan(false)
      setActionUser(null)
      fetchUsers()
    } catch {
      addToast('Erro ao alterar plano', 'error')
    }
  }

  const handleResetUsage = async (user: AdminUser) => {
    setResetting(user.id)
    try {
      await api.post(`/api/admin/users/${user.id}/reset-usage`)
      addToast(`Uso de ${user.username} resetado com sucesso`, 'success')
      fetchUsers()
    } catch {
      addToast('Erro ao resetar uso', 'error')
    } finally {
      setResetting(null)
      setOpenMenu(null)
    }
  }

  const filtered = users.filter((u) => {
    const matchSearch = !search || u.username.toLowerCase().includes(search.toLowerCase())
    const matchPlan = !planFilter || u.plan === planFilter
    return matchSearch && matchPlan
  })

  const planCounts = users.reduce<Record<string, number>>((acc, u) => {
    acc[u.plan] = (acc[u.plan] || 0) + 1
    return acc
  }, {})

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Users className="w-6 h-6 text-blue-600" />
            Gerenciar Usuários
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            {users.length} usuário{users.length !== 1 ? 's' : ''} cadastrado{users.length !== 1 ? 's' : ''}
          </p>
        </div>
        <button
          onClick={fetchUsers}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Atualizar
        </button>
      </div>

      {/* Plan Summary Cards */}
      <div className="grid grid-cols-3 gap-4">
        {['free', 'pro', 'enterprise'].map((p) => (
          <button
            key={p}
            onClick={() => setPlanFilter(planFilter === p ? '' : p)}
            className={`p-4 rounded-xl border text-left transition-all ${
              planFilter === p
                ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-gray-300 dark:hover:border-gray-600'
            }`}
          >
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{planCounts[p] || 0}</p>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full mt-1 inline-block ${PLAN_BADGE[p]}`}>
              {PLAN_LABELS[p]}
            </span>
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Buscar por usuário..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        {planFilter && (
          <button
            onClick={() => setPlanFilter('')}
            className="px-3 py-2 text-sm text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 rounded-lg hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
          >
            Limpar filtro: {PLAN_LABELS[planFilter]}
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500 dark:text-gray-400">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
            Carregando usuários...
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-gray-500 dark:text-gray-400">
            <Users className="w-8 h-8 mx-auto mb-2 opacity-40" />
            Nenhum usuário encontrado
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50">
                <th className="text-left px-5 py-3 font-medium text-gray-600 dark:text-gray-400">Usuário</th>
                <th className="text-left px-5 py-3 font-medium text-gray-600 dark:text-gray-400">Plano</th>
                <th className="text-left px-5 py-3 font-medium text-gray-600 dark:text-gray-400">Leads este mês</th>
                <th className="text-left px-5 py-3 font-medium text-gray-600 dark:text-gray-400">Exportações</th>
                <th className="text-left px-5 py-3 font-medium text-gray-600 dark:text-gray-400">Desde</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {filtered.map((user) => (
                <tr key={user.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors">
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-2">
                      <div className={`w-7 h-7 rounded-full flex items-center justify-center ${
                        user.is_admin
                          ? 'bg-orange-100 dark:bg-orange-900/40'
                          : 'bg-blue-100 dark:bg-blue-900/40'
                      }`}>
                        <span className={`text-xs font-bold uppercase ${
                          user.is_admin
                            ? 'text-orange-600 dark:text-orange-400'
                            : 'text-blue-600 dark:text-blue-400'
                        }`}>
                          {user.username[0]}
                        </span>
                      </div>
                      <span className="font-medium text-gray-900 dark:text-white">{user.username}</span>
                      {user.is_admin && (
                        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400">
                          ADMIN
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-5 py-3.5">
                    <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${PLAN_BADGE[user.plan] ?? PLAN_BADGE.free}`}>
                      {PLAN_LABELS[user.plan] ?? user.plan}
                    </span>
                  </td>
                  <td className="px-5 py-3.5">
                    <UsageBar
                      used={user.usage?.leads_viewed ?? 0}
                      limit={user.limits?.leads_per_month ?? 100}
                      color="bg-blue-500"
                    />
                  </td>
                  <td className="px-5 py-3.5">
                    <UsageBar
                      used={user.usage?.leads_exported ?? 0}
                      limit={user.limits?.exports_per_month ?? 1}
                      color="bg-green-500"
                    />
                  </td>
                  <td className="px-5 py-3.5 text-gray-500 dark:text-gray-400">
                    {user.created_at ? new Date(user.created_at).toLocaleDateString('pt-BR') : '—'}
                  </td>
                  <td className="px-5 py-3.5 relative">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setOpenMenu(openMenu === user.id ? null : user.id)
                      }}
                      className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                    >
                      <MoreHorizontal className="w-4 h-4 text-gray-500" />
                    </button>

                    {openMenu === user.id && (
                      <div className="absolute right-4 top-10 z-20 w-48 bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 py-1">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setActionUser(user)
                            setShowChangePlan(true)
                            setOpenMenu(null)
                          }}
                          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                        >
                          <Shield className="w-4 h-4 text-blue-500" />
                          Alterar Plano
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleResetUsage(user)
                          }}
                          disabled={resetting === user.id}
                          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
                        >
                          <RefreshCw className={`w-4 h-4 text-orange-500 ${resetting === user.id ? 'animate-spin' : ''}`} />
                          {resetting === user.id ? 'Resetando...' : 'Resetar Uso'}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Change Plan Modal */}
      {showChangePlan && actionUser && (
        <ChangePlanModal
          user={actionUser}
          plans={['free', 'pro', 'enterprise']}
          onConfirm={handleChangePlan}
          onClose={() => {
            setShowChangePlan(false)
            setActionUser(null)
          }}
        />
      )}
    </div>
  )
}
