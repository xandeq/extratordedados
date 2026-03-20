import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import {
  Users, MapPin, Tag, TrendingUp, Star, ArrowRight, Building2
} from 'lucide-react'
import api from '../lib/api'
import { formatDate, formatNumber } from '../lib/formatters'
import StatCard from '../components/StatCard'
import LoadingSkeleton from '../components/LoadingSkeleton'
import { PlanCard } from '../components/PlanCard'
import { useClientPlan } from '../lib/useClientPlan'

interface RankItem {
  name: string
  count: number
}

interface LatestLead {
  id: number
  company_name: string
  email: string
  city: string
  state: string
  category: string
  lead_score: number
  extracted_at: string
}

interface Analytics {
  total_leads: number
  avg_score: number
  total_cities: number
  total_categories: number
  leads_this_week: number
  top_cities: RankItem[]
  top_states: RankItem[]
  top_categories: RankItem[]
  latest_leads: LatestLead[]
  score_distribution: { high: number; medium: number; low: number }
}

function RankBlock({ title, icon: Icon, items, color }: {
  title: string
  icon: React.ElementType
  items: RankItem[]
  color: string
}) {
  const max = items[0]?.count || 1
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Icon className={`w-4 h-4 ${color}`} />
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h3>
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-gray-400 dark:text-gray-500">Sem dados ainda</p>
      ) : (
        <div className="space-y-2.5">
          {items.map((item, i) => (
            <div key={item.name} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-700 dark:text-gray-300 font-medium truncate max-w-[160px]" title={item.name}>
                  {i + 1}. {item.name}
                </span>
                <span className="text-gray-500 dark:text-gray-400 tabular-nums ml-2">{formatNumber(item.count)}</span>
              </div>
              <div className="h-1 rounded-full bg-gray-100 dark:bg-gray-700 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${color.replace('text-', 'bg-')}`}
                  style={{ width: `${Math.max(4, (item.count / max) * 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ScoreBar({ label, count, total, color }: {
  label: string
  count: number
  total: number
  color: string
}) {
  const pct = total > 0 ? Math.max(2, (count / total) * 100) : 0
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-gray-600 dark:text-gray-400">{label}</span>
        <span className="font-medium text-gray-700 dark:text-gray-300 tabular-nums">{formatNumber(count)}</span>
      </div>
      <div className="h-2 rounded-full bg-gray-100 dark:bg-gray-700 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function Dashboard() {
  const router = useRouter()
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const { plan, limits, usage, loading: planLoading } = useClientPlan()

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const resp = await api.get('/api/analytics')
      setAnalytics(resp.data)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao carregar dados')
      if (err.response?.status === 401) router.push('/login')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <LoadingSkeleton />

  const scoreTotal = analytics
    ? analytics.score_distribution.high + analytics.score_distribution.medium + analytics.score_distribution.low
    : 0

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Visao geral da base compartilhada de leads
          </p>
        </div>
        <Link href="/leads">
          <button className="flex items-center gap-2 px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors">
            Ver Leads
            <ArrowRight className="w-4 h-4" />
          </button>
        </Link>
      </div>

      {/* Plan Card */}
      {!planLoading && plan && limits && usage && (
        <PlanCard
          plan={plan}
          leadsViewed={usage.leads_viewed}
          leadsLimit={limits.leads_per_month}
          exportsUsed={usage.leads_exported}
          exportsLimit={limits.exports_per_month}
          onUpgrade={() => router.push('/plans')}
        />
      )}

      {error && (
        <div className="px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Stat Cards */}
      {analytics && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Total de Leads"
            value={formatNumber(analytics.total_leads)}
            icon={Users}
            color="blue"
            subtitle={`+${formatNumber(analytics.leads_this_week)} esta semana`}
          />
          <StatCard
            label="Score Medio"
            value={analytics.avg_score > 0 ? analytics.avg_score.toFixed(1) : '—'}
            icon={Star}
            color="amber"
            subtitle="qualidade media dos leads"
          />
          <StatCard
            label="Cidades Cobertas"
            value={formatNumber(analytics.total_cities)}
            icon={MapPin}
            color="green"
            subtitle="municipios com leads"
          />
          <StatCard
            label="Categorias"
            value={formatNumber(analytics.total_categories)}
            icon={Tag}
            color="purple"
            subtitle="segmentos de negocio"
          />
        </div>
      )}

      {/* Ranking Blocks */}
      {analytics && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <RankBlock
            title="Top Cidades"
            icon={MapPin}
            items={analytics.top_cities}
            color="text-blue-500"
          />
          <RankBlock
            title="Top Estados"
            icon={TrendingUp}
            items={analytics.top_states}
            color="text-green-500"
          />
          <RankBlock
            title="Top Categorias"
            icon={Tag}
            items={analytics.top_categories}
            color="text-purple-500"
          />
        </div>
      )}

      {/* Score Distribution + Latest Leads */}
      {analytics && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Score Distribution */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Star className="w-4 h-4 text-amber-500" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Qualidade dos Leads</h3>
            </div>
            <div className="space-y-3">
              <ScoreBar
                label="Alto (70+)"
                count={analytics.score_distribution.high}
                total={scoreTotal}
                color="bg-green-500"
              />
              <ScoreBar
                label="Medio (40–69)"
                count={analytics.score_distribution.medium}
                total={scoreTotal}
                color="bg-yellow-400"
              />
              <ScoreBar
                label="Baixo (0–39)"
                count={analytics.score_distribution.low}
                total={scoreTotal}
                color="bg-red-400"
              />
            </div>
            {scoreTotal > 0 && (
              <p className="text-xs text-gray-400 dark:text-gray-500 pt-1">
                {Math.round((analytics.score_distribution.high / scoreTotal) * 100)}% dos leads com score alto
              </p>
            )}
          </div>

          {/* Latest Leads */}
          <div className="lg:col-span-2 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-gray-700">
              <div className="flex items-center gap-2">
                <Building2 className="w-4 h-4 text-gray-400" />
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Ultimos Leads Adicionados</h3>
              </div>
              <Link href="/leads" className="text-xs text-primary-600 dark:text-primary-400 hover:underline font-medium">
                Ver todos
              </Link>
            </div>
            {analytics.latest_leads.length === 0 ? (
              <div className="px-5 py-8 text-center text-sm text-gray-400 dark:text-gray-500">
                Nenhum lead na base ainda
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-gray-50/60 dark:bg-gray-700/40">
                      <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Empresa</th>
                      <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Cidade/UF</th>
                      <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden sm:table-cell">Categoria</th>
                      <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Score</th>
                      <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden md:table-cell">Data</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                    {analytics.latest_leads.map((lead) => (
                      <tr key={lead.id} className="hover:bg-gray-50/50 dark:hover:bg-gray-700/30 transition-colors">
                        <td className="px-5 py-3 text-sm font-medium text-gray-900 dark:text-gray-100 max-w-[160px] truncate" title={lead.company_name || lead.email}>
                          {lead.company_name || lead.email || '—'}
                        </td>
                        <td className="px-5 py-3 text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
                          {lead.city && lead.state ? `${lead.city}, ${lead.state}` : lead.city || lead.state || '—'}
                        </td>
                        <td className="px-5 py-3 text-sm text-gray-500 dark:text-gray-400 max-w-[120px] truncate hidden sm:table-cell" title={lead.category}>
                          {lead.category || '—'}
                        </td>
                        <td className="px-5 py-3">
                          {lead.lead_score > 0 ? (
                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${
                              lead.lead_score >= 70
                                ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                                : lead.lead_score >= 40
                                ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                                : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                            }`}>
                              {lead.lead_score}
                            </span>
                          ) : (
                            <span className="text-gray-300 dark:text-gray-600 text-xs">—</span>
                          )}
                        </td>
                        <td className="px-5 py-3 text-sm text-gray-400 dark:text-gray-500 hidden md:table-cell whitespace-nowrap">
                          {lead.extracted_at ? formatDate(lead.extracted_at) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Empty state when base is empty */}
      {analytics && analytics.total_leads === 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 px-6 py-12 text-center">
          <Users className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">Base de leads em preparacao</p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
            Os leads serao exibidos aqui assim que a base for populada pelo administrador
          </p>
        </div>
      )}
    </div>
  )
}
