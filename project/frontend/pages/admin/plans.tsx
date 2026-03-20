import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/router'
import {
  LayoutGrid, RefreshCw, Edit2, CheckCircle2, X, Users,
  TrendingUp, Download, Bookmark, Infinity
} from 'lucide-react'
import api from '../../lib/api'
import { useToast } from '../../components/Toast'

interface PlanStat {
  name: string
  leads_per_month: number
  exports_per_month: number
  price_monthly: number
  features: Record<string, boolean>
  user_count: number
}

const PLAN_LABELS: Record<string, string> = {
  free: 'Grátis',
  pro: 'Pro',
  enterprise: 'Enterprise',
}

const PLAN_COLORS: Record<string, { bg: string; border: string; badge: string; icon: string }> = {
  free: {
    bg: 'bg-gray-50 dark:bg-gray-700/30',
    border: 'border-gray-200 dark:border-gray-700',
    badge: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
    icon: 'text-gray-500',
  },
  pro: {
    bg: 'bg-blue-50 dark:bg-blue-900/10',
    border: 'border-blue-200 dark:border-blue-800',
    badge: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
    icon: 'text-blue-500',
  },
  enterprise: {
    bg: 'bg-purple-50 dark:bg-purple-900/10',
    border: 'border-purple-200 dark:border-purple-800',
    badge: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
    icon: 'text-purple-500',
  },
}

function formatLimit(val: number): string {
  if (val >= 999999) return '∞'
  if (val >= 1000) return `${(val / 1000).toLocaleString('pt-BR')}k`
  return val.toString()
}

function EditPlanModal({
  plan,
  onConfirm,
  onClose,
}: {
  plan: PlanStat
  onConfirm: (data: { leads_per_month: number; exports_per_month: number; price_monthly: number }) => void
  onClose: () => void
}) {
  const [leads, setLeads] = useState(plan.leads_per_month.toString())
  const [exports, setExports] = useState(plan.exports_per_month.toString())
  const [price, setPrice] = useState(plan.price_monthly.toString())

  const colors = PLAN_COLORS[plan.name] ?? PLAN_COLORS.free

  const handleConfirm = () => {
    const leadsNum = parseInt(leads, 10)
    const exportsNum = parseInt(exports, 10)
    const priceNum = parseFloat(price)
    if (isNaN(leadsNum) || isNaN(exportsNum) || isNaN(priceNum)) return
    onConfirm({ leads_per_month: leadsNum, exports_per_month: exportsNum, price_monthly: priceNum })
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm">
        <div className="p-5 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
          <div>
            <h2 className="font-semibold text-gray-900 dark:text-white">Editar Plano</h2>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full mt-1 inline-block ${colors.badge}`}>
              {PLAN_LABELS[plan.name] ?? plan.name}
            </span>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Leads por mês
            </label>
            <input
              type="number"
              min={0}
              value={leads}
              onChange={(e) => setLeads(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-400 mt-1">Use 999999 para ilimitado (∞)</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Exportações por mês
            </label>
            <input
              type="number"
              min={0}
              value={exports}
              onChange={(e) => setExports(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Preço mensal (R$)
            </label>
            <input
              type="number"
              min={0}
              step={0.01}
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        <div className="px-5 pb-5 flex gap-3 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={handleConfirm}
            className="px-4 py-2 text-sm font-semibold bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors flex items-center gap-2"
          >
            <CheckCircle2 className="w-4 h-4" />
            Salvar
          </button>
        </div>
      </div>
    </div>
  )
}

export default function AdminPlans() {
  const router = useRouter()
  const { addToast } = useToast()

  const [plans, setPlans] = useState<PlanStat[]>([])
  const [loading, setLoading] = useState(true)
  const [editingPlan, setEditingPlan] = useState<PlanStat | null>(null)
  const [saving, setSaving] = useState(false)

  const fetchPlans = useCallback(async () => {
    try {
      setLoading(true)
      const res = await api.get('/api/admin/plans-stats')
      setPlans(res.data.plans || [])
    } catch (err: unknown) {
      const status = (err as any)?.response?.status
      if (status === 401) router.push('/login')
      else if (status === 403) router.push('/dashboard')
      else addToast('Erro ao carregar planos', 'error')
    } finally {
      setLoading(false)
    }
  }, [router, addToast])

  useEffect(() => {
    fetchPlans()
  }, [fetchPlans])

  const handleSavePlan = async (data: {
    leads_per_month: number
    exports_per_month: number
    price_monthly: number
  }) => {
    if (!editingPlan) return
    setSaving(true)
    try {
      await api.put(`/api/admin/plans/${editingPlan.name}`, data)
      addToast(`Plano ${PLAN_LABELS[editingPlan.name]} atualizado`, 'success')
      setEditingPlan(null)
      fetchPlans()
    } catch {
      addToast('Erro ao atualizar plano', 'error')
    } finally {
      setSaving(false)
    }
  }

  const totalUsers = plans.reduce((sum, p) => sum + p.user_count, 0)

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <LayoutGrid className="w-6 h-6 text-purple-600" />
            Planos & Limites
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            {totalUsers} usuário{totalUsers !== 1 ? 's' : ''} no total
          </p>
        </div>
        <button
          onClick={fetchPlans}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Atualizar
        </button>
      </div>

      {/* Plan Cards */}
      {loading ? (
        <div className="p-8 text-center text-gray-500 dark:text-gray-400">
          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
          Carregando planos...
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {plans.map((plan) => {
            const colors = PLAN_COLORS[plan.name] ?? PLAN_COLORS.free
            const isUnlimited = plan.leads_per_month >= 999999

            return (
              <div
                key={plan.name}
                className={`rounded-xl border p-5 flex flex-col gap-4 ${colors.bg} ${colors.border}`}
              >
                {/* Plan header */}
                <div className="flex items-start justify-between">
                  <div>
                    <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${colors.badge}`}>
                      {PLAN_LABELS[plan.name] ?? plan.name}
                    </span>
                    <div className="flex items-baseline gap-1 mt-2">
                      <span className="text-2xl font-bold text-gray-900 dark:text-white">
                        {plan.price_monthly === 0 ? 'Grátis' : `R$${plan.price_monthly.toFixed(0)}`}
                      </span>
                      {plan.price_monthly > 0 && (
                        <span className="text-sm text-gray-500 dark:text-gray-400">/mês</span>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => setEditingPlan(plan)}
                    className="p-2 rounded-lg hover:bg-white/60 dark:hover:bg-gray-700/60 transition-colors"
                    title="Editar plano"
                  >
                    <Edit2 className={`w-4 h-4 ${colors.icon}`} />
                  </button>
                </div>

                {/* Stats */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-1.5 text-gray-600 dark:text-gray-400">
                      <TrendingUp className="w-3.5 h-3.5" />
                      Leads / mês
                    </span>
                    <span className="font-semibold text-gray-900 dark:text-white flex items-center gap-0.5">
                      {isUnlimited ? <Infinity className="w-4 h-4" /> : formatLimit(plan.leads_per_month)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-1.5 text-gray-600 dark:text-gray-400">
                      <Download className="w-3.5 h-3.5" />
                      Exportações / mês
                    </span>
                    <span className="font-semibold text-gray-900 dark:text-white flex items-center gap-0.5">
                      {plan.exports_per_month >= 999999 ? <Infinity className="w-4 h-4" /> : plan.exports_per_month}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-1.5 text-gray-600 dark:text-gray-400">
                      <Bookmark className="w-3.5 h-3.5" />
                      Filtros salvos
                    </span>
                    <span className="font-semibold text-gray-900 dark:text-white">
                      {plan.name === 'free' ? '0' : plan.name === 'pro' ? '5' : plan.name === 'enterprise' ? '20' : '—'}
                    </span>
                  </div>
                </div>

                {/* Divider */}
                <div className="border-t border-gray-200 dark:border-gray-700" />

                {/* User count */}
                <div className="flex items-center gap-2">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center bg-white dark:bg-gray-800`}>
                    <Users className={`w-4 h-4 ${colors.icon}`} />
                  </div>
                  <div>
                    <p className="text-lg font-bold text-gray-900 dark:text-white leading-none">
                      {plan.user_count}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      usuário{plan.user_count !== 1 ? 's' : ''}
                    </p>
                  </div>
                </div>

                {/* Edit button */}
                <button
                  onClick={() => setEditingPlan(plan)}
                  disabled={saving}
                  className="w-full py-2 text-sm font-medium border border-current rounded-lg transition-colors hover:bg-white/50 dark:hover:bg-gray-700/50 disabled:opacity-50"
                  style={{ color: plan.name === 'enterprise' ? '#9333ea' : plan.name === 'pro' ? '#2563eb' : '#374151' }}
                >
                  Editar limites
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* Info note */}
      {!loading && (
        <p className="text-xs text-gray-400 dark:text-gray-500">
          Alterações nos limites são aplicadas imediatamente para todos os usuários do plano.
        </p>
      )}

      {/* Edit Modal */}
      {editingPlan && (
        <EditPlanModal
          plan={editingPlan}
          onConfirm={handleSavePlan}
          onClose={() => setEditingPlan(null)}
        />
      )}
    </div>
  )
}
