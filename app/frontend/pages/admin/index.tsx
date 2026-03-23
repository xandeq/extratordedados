import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import {
  Users, LayoutGrid, Database, ScrollText, RefreshCw,
  TrendingUp, Shield, UserCheck, ArrowRight, Settings,
  CheckCircle, XCircle, Clock, AlertCircle, Activity
} from 'lucide-react'
import api from '../../lib/api'
import { useToast } from '../../components/Toast'
import { formatNumber, formatDate } from '../../lib/formatters'

interface AdminSummary {
  total_users: number
  total_admins: number
  total_customers: number
  users_by_plan: Record<string, number>
  total_leads: number
  leads_this_week: number
}

interface PipelineHealth {
  last_run: {
    status: string
    started_at: string
    finished_at: string | null
    leads_found: number
    leads_sanitized: number
    leads_synced: number
    error_message: string | null
    region_used: string
    duration_min: number | null
  } | null
  next_scheduled: string
  stats_30d: {
    total: number
    successful: number
    avg_leads: number
    max_leads: number
  }
  scheduler_running: boolean
  config: {
    region: string
    hour: number
    niches: string[]
  }
}

interface PipelineJob {
  id: number
  started_at: string
  finished_at: string | null
  status: string
  leads_found: number
  leads_sanitized: number
  leads_synced: number
  region: string
  niches: string[]
}

const PLAN_LABELS: Record<string, string> = { free: 'Grátis', pro: 'Pro', enterprise: 'Enterprise' }
const PLAN_BADGE: Record<string, string> = {
  free: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
  pro: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  enterprise: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
}
const PLAN_BAR: Record<string, string> = {
  free: 'bg-gray-400',
  pro: 'bg-blue-500',
  enterprise: 'bg-purple-500',
}

const QUICK_LINKS = [
  {
    href: '/admin/users',
    label: 'Gerenciar Usuários',
    description: 'Ver planos, uso e alterar limites',
    icon: Users,
    color: 'text-blue-600 dark:text-blue-400',
    bg: 'bg-blue-50 dark:bg-blue-900/20',
  },
  {
    href: '/admin/plans',
    label: 'Planos & Limites',
    description: 'Editar limites de cada plano',
    icon: LayoutGrid,
    color: 'text-purple-600 dark:text-purple-400',
    bg: 'bg-purple-50 dark:bg-purple-900/20',
  },
  {
    href: '/leads',
    label: 'Base de Leads',
    description: 'Ver e gerenciar a base compartilhada',
    icon: Database,
    color: 'text-green-600 dark:text-green-400',
    bg: 'bg-green-50 dark:bg-green-900/20',
  },
  {
    href: '/app-logs',
    label: 'System Logs',
    description: 'Diagnóstico e logs do sistema',
    icon: ScrollText,
    color: 'text-orange-600 dark:text-orange-400',
    bg: 'bg-orange-50 dark:bg-orange-900/20',
  },
  {
    href: '/admin/pipeline-config',
    label: 'Pipeline Automático',
    description: 'Nichos, região, horário e relatórios',
    icon: Settings,
    color: 'text-orange-600 dark:text-orange-400',
    bg: 'bg-orange-50 dark:bg-orange-900/20',
  },
]

function getStatusBadge(status: string | undefined) {
  if (!status) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
        <AlertCircle className="w-3 h-3" />
        Nunca executou
      </span>
    )
  }
  if (status === 'completed') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300">
        <CheckCircle className="w-3 h-3" />
        Concluído
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300">
        <XCircle className="w-3 h-3" />
        Falhou
      </span>
    )
  }
  if (status === 'running') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300">
        <Clock className="w-3 h-3 animate-spin" />
        Rodando...
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
      {status}
    </span>
  )
}

function computeDuration(startedAt: string, finishedAt: string | null): string {
  if (!finishedAt) return '—'
  const start = new Date(startedAt).getTime()
  const end = new Date(finishedAt).getTime()
  const diffMin = Math.round((end - start) / 60000)
  if (diffMin < 60) return `${diffMin} min`
  const h = Math.floor(diffMin / 60)
  const m = diffMin % 60
  return `${h}h${m > 0 ? ` ${m}m` : ''}`
}

export default function AdminHome() {
  const router = useRouter()
  const { addToast } = useToast()
  const [data, setData] = useState<AdminSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [pipelineHealth, setPipelineHealth] = useState<PipelineHealth | null>(null)
  const [pipelineJobs, setPipelineJobs] = useState<PipelineJob[]>([])

  const fetchSummary = useCallback(async () => {
    try {
      setLoading(true)
      const res = await api.get('/api/admin/summary')
      setData(res.data)
    } catch (err: unknown) {
      const status = (err as any)?.response?.status
      if (status === 401) router.push('/login')
      else if (status === 403) router.push('/dashboard')
      else addToast('Erro ao carregar resumo admin', 'error')
    } finally {
      setLoading(false)
    }
  }, [router, addToast])

  useEffect(() => {
    fetchSummary()
    api.get('/api/admin/pipeline/health')
      .then(res => setPipelineHealth(res.data))
      .catch(() => setPipelineHealth(null))
    api.get('/api/admin/daily-job/status')
      .then(res => setPipelineJobs(res.data.jobs || []))
      .catch(() => setPipelineJobs([]))
  }, [fetchSummary])

  const planOrder = ['free', 'pro', 'enterprise']
  const maxPlanCount = data
    ? Math.max(1, ...planOrder.map((p) => data.users_by_plan[p] ?? 0))
    : 1

  const successRate30d = pipelineHealth && pipelineHealth.stats_30d.total > 0
    ? Math.round((pipelineHealth.stats_30d.successful / pipelineHealth.stats_30d.total) * 100)
    : null

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Shield className="w-6 h-6 text-indigo-600" />
            Painel Admin
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Visão operacional do SaaS
          </p>
        </div>
        <button
          onClick={fetchSummary}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Atualizar
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 animate-pulse">
              <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-2/3 mb-3" />
              <div className="h-7 bg-gray-200 dark:bg-gray-700 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : data && (
        <>
          {/* Stat Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <div className="flex items-center gap-2 mb-2">
                <Users className="w-4 h-4 text-blue-500" />
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                  Usuários
                </span>
              </div>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">{formatNumber(data.total_users)}</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">total cadastrados</p>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <div className="flex items-center gap-2 mb-2">
                <UserCheck className="w-4 h-4 text-green-500" />
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                  Clientes
                </span>
              </div>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">{formatNumber(data.total_customers)}</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">assinantes ativos</p>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <div className="flex items-center gap-2 mb-2">
                <Database className="w-4 h-4 text-indigo-500" />
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                  Leads na Base
                </span>
              </div>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">{formatNumber(data.total_leads)}</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                +{formatNumber(data.leads_this_week)} esta semana
              </p>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <div className="flex items-center gap-2 mb-2">
                <Shield className="w-4 h-4 text-orange-500" />
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                  Admins
                </span>
              </div>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">{formatNumber(data.total_admins)}</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">com acesso total</p>
            </div>
          </div>

          {/* Plan Distribution */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <div className="flex items-center gap-2 mb-4">
              <TrendingUp className="w-4 h-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Distribuição por Plano</h3>
            </div>
            <div className="grid grid-cols-3 gap-4">
              {planOrder.map((p) => {
                const count = data.users_by_plan[p] ?? 0
                const pct = Math.max(4, (count / maxPlanCount) * 100)
                return (
                  <div key={p} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${PLAN_BADGE[p]}`}>
                        {PLAN_LABELS[p]}
                      </span>
                      <span className="text-sm font-bold text-gray-900 dark:text-white">{count}</span>
                    </div>
                    <div className="h-2 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${PLAN_BAR[p]}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <p className="text-xs text-gray-400 dark:text-gray-500">
                      {data.total_users > 0
                        ? `${Math.round((count / data.total_users) * 100)}% do total`
                        : '0%'}
                    </p>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}

      {/* Pipeline Health Card */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
        {/* Card Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-orange-500" />
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Pipeline Automático</h3>
            {pipelineHealth?.scheduler_running && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300">
                Agendador ativo
              </span>
            )}
          </div>
          <Link
            href="/admin/pipeline-config"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-orange-600 dark:text-orange-400 border border-orange-200 dark:border-orange-800 rounded-lg hover:bg-orange-50 dark:hover:bg-orange-900/20 transition-colors no-underline"
          >
            <Settings className="w-3.5 h-3.5" />
            Configurar
          </Link>
        </div>

        {/* Status Row */}
        <div className="flex items-center gap-3 mb-5">
          <span className="text-xs text-gray-500 dark:text-gray-400">Último run:</span>
          {getStatusBadge(pipelineHealth?.last_run?.status)}
          {pipelineHealth?.last_run?.started_at && (
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {formatDate(pipelineHealth.last_run.started_at)}
            </span>
          )}
          {pipelineHealth?.last_run?.error_message && (
            <span className="text-xs text-red-500 dark:text-red-400 truncate max-w-xs" title={pipelineHealth.last_run.error_message}>
              {pipelineHealth.last_run.error_message}
            </span>
          )}
        </div>

        {/* Metric Tiles */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Leads ontem</p>
            <p className="text-xl font-bold text-gray-900 dark:text-white">
              {pipelineHealth?.last_run != null
                ? formatNumber(pipelineHealth.last_run.leads_found)
                : '—'}
            </p>
          </div>
          <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Próxima execução</p>
            <p className="text-sm font-semibold text-gray-900 dark:text-white">
              {pipelineHealth?.next_scheduled ?? '—'}
            </p>
          </div>
          <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Taxa 30d</p>
            <p className="text-xl font-bold text-gray-900 dark:text-white">
              {successRate30d != null ? `${successRate30d}%` : '—'}
            </p>
          </div>
          <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Média leads</p>
            <p className="text-xl font-bold text-gray-900 dark:text-white">
              {pipelineHealth?.stats_30d?.avg_leads != null
                ? formatNumber(Math.round(pipelineHealth.stats_30d.avg_leads))
                : '—'}
            </p>
          </div>
        </div>

        {/* 30-day History Table */}
        <div>
          <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
            Histórico (últimas execuções)
          </h4>
          {pipelineJobs.length === 0 ? (
            <p className="text-sm text-gray-400 dark:text-gray-500 py-4 text-center">
              Nenhuma execução registrada
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-100 dark:border-gray-700">
                    <th className="text-left py-2 pr-3 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">Data</th>
                    <th className="text-left py-2 pr-3 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">Região</th>
                    <th className="text-right py-2 pr-3 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">Leads</th>
                    <th className="text-right py-2 pr-3 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">Sanitizados</th>
                    <th className="text-right py-2 pr-3 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">Sincronizados</th>
                    <th className="text-left py-2 pr-3 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">Status</th>
                    <th className="text-right py-2 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">Duração</th>
                  </tr>
                </thead>
                <tbody>
                  {pipelineJobs.slice(0, 10).map((job) => (
                    <tr key={job.id} className="border-b border-gray-50 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors">
                      <td className="py-2 pr-3 text-gray-700 dark:text-gray-300 whitespace-nowrap">
                        {formatDate(job.started_at)}
                      </td>
                      <td className="py-2 pr-3 text-gray-600 dark:text-gray-400 whitespace-nowrap">
                        {job.region ?? '—'}
                      </td>
                      <td className="py-2 pr-3 text-right font-medium text-gray-900 dark:text-white">
                        {formatNumber(job.leads_found)}
                      </td>
                      <td className="py-2 pr-3 text-right text-gray-600 dark:text-gray-400">
                        {formatNumber(job.leads_sanitized)}
                      </td>
                      <td className="py-2 pr-3 text-right text-gray-600 dark:text-gray-400">
                        {formatNumber(job.leads_synced)}
                      </td>
                      <td className="py-2 pr-3">
                        {getStatusBadge(job.status)}
                      </td>
                      <td className="py-2 text-right text-gray-500 dark:text-gray-400 whitespace-nowrap">
                        {computeDuration(job.started_at, job.finished_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Quick Links */}
      <div>
        <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
          Atalhos
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {QUICK_LINKS.map((link) => {
            const Icon = link.icon
            return (
              <Link
                key={link.href}
                href={link.href}
                className="flex items-center gap-4 p-4 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 hover:shadow-sm transition-all no-underline group"
              >
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${link.bg}`}>
                  <Icon className={`w-5 h-5 ${link.color}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">{link.label}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{link.description}</p>
                </div>
                <ArrowRight className="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-gray-500 dark:group-hover:text-gray-400 transition-colors flex-shrink-0" />
              </Link>
            )
          })}
        </div>
      </div>
    </div>
  )
}
