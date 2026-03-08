import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import {
  Search, ChevronRight, Plus, Layers, Mail, TrendingUp,
  Calendar, CheckCircle2, Globe, Users
} from 'lucide-react'
import api from '../lib/api'
import { formatDate, formatNumber } from '../lib/formatters'
import StatusBadge from '../components/StatusBadge'
import StatCard from '../components/StatCard'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import LeadsTrendChart from '../components/charts/LeadsTrendChart'
import TopBatchesChart from '../components/charts/TopBatchesChart'
import DataQualityPie from '../components/charts/DataQualityPie'
import InfoBox from '../components/InfoBox'
import Tooltip from '../components/Tooltip'

interface Job {
  id: number
  url: string
  status: string
  results_count: number
  created_at: string
}

interface Batch {
  id: number
  name: string
  status: string
  total_urls: number
  processed_urls: number
  total_leads: number
  created_at: string
}

interface Analytics {
  total_leads: number
  total_batches: number
  unique_emails: number
  leads_this_week: number
  leads_this_month: number
  completed_batches: number
  failed_batches: number
  success_rate: number
  leads_by_day: { date: string; leads: number }[]
  top_batches: { name: string; leads: number }[]
  data_quality: { with_phone: number; email_only: number }
}

export default function Dashboard() {
  const router = useRouter()
  const [jobs, setJobs] = useState<Job[]>([])
  const [batches, setBatches] = useState<Batch[]>([])
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const [jobsResp, batchesResp, analyticsResp] = await Promise.all([
        api.get('/api/results'),
        api.get('/api/batch'),
        api.get('/api/analytics'),
      ])
      setJobs(jobsResp.data.jobs || [])
      setBatches(batchesResp.data.batches || [])
      setAnalytics(analyticsResp.data)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao carregar dados')
      if (err.response?.status === 401) router.push('/login')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <LoadingSkeleton />

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">Visao geral das suas extracoes</p>
        </div>
        <Link href="/scrape">
          <button className="flex items-center gap-2 px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors">
            <Plus className="w-4 h-4" />
            Nova Extracao
          </button>
        </Link>
      </div>

      {/* InfoBox */}
      <InfoBox
        storageKey="dashboard"
        title="Bem-vindo ao Dashboard"
        description="Aqui voce acompanha em tempo real todos os seus resultados: total de leads capturados, taxa de sucesso das extracoes e evolucao ao longo do tempo."
        steps={[
          'Clique em "Nova Extracao" para capturar leads de um site ou busca',
          'Use "Busca Massiva" no menu lateral para buscar por nicho e cidade',
          'Acesse "Leads" para visualizar, filtrar e exportar seus contatos',
        ]}
      />

      {error && (
        <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Stats Row */}
      {analytics && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="relative">
            <div className="absolute top-3 right-3 z-10">
              <Tooltip text="Total de contatos (emails, telefones, WhatsApp) extraidos de todos os lotes e jobs." position="bottom" />
            </div>
            <StatCard
              label="Total de Leads"
              value={formatNumber(analytics.total_leads)}
              icon={Users}
              color="blue"
              subtitle={`${formatNumber(analytics.unique_emails)} emails unicos`}
            />
          </div>
          <div className="relative">
            <div className="absolute top-3 right-3 z-10">
              <Tooltip text="Leads capturados nos ultimos 7 dias e no mes atual. Indica o ritmo de crescimento da sua base." position="bottom" />
            </div>
            <StatCard
              label="Esta Semana"
              value={formatNumber(analytics.leads_this_week)}
              icon={TrendingUp}
              color="green"
              subtitle={`${formatNumber(analytics.leads_this_month)} este mes`}
            />
          </div>
          <div className="relative">
            <div className="absolute top-3 right-3 z-10">
              <Tooltip text="Lotes sao grupos de URLs ou buscas processadas em conjunto. Cada busca massiva cria um lote." position="bottom" />
            </div>
            <StatCard
              label="Lotes"
              value={analytics.total_batches}
              icon={Layers}
              color="purple"
              subtitle={`${analytics.completed_batches} completos`}
            />
          </div>
          <div className="relative">
            <div className="absolute top-3 right-3 z-10">
              <Tooltip text="Percentual de lotes que terminaram sem erros graves. Abaixo de 70% pode indicar bloqueios ou sites inacessiveis." position="bottom" />
            </div>
            <StatCard
              label="Taxa de Sucesso"
              value={`${analytics.success_rate}%`}
              icon={CheckCircle2}
              color="amber"
              subtitle={`${analytics.failed_batches} falha${analytics.failed_batches !== 1 ? 's' : ''}`}
            />
          </div>
        </div>
      )}

      {/* Charts Row */}
      {analytics && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <LeadsTrendChart data={analytics.leads_by_day} />
          </div>
          <DataQualityPie
            withPhone={analytics.data_quality.with_phone}
            emailOnly={analytics.data_quality.email_only}
          />
        </div>
      )}

      {/* Top Batches Chart */}
      {analytics && analytics.top_batches.length > 0 && (
        <TopBatchesChart data={analytics.top_batches} />
      )}

      {/* Batches Table */}
      {batches.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">Lotes Recentes</h2>
            <span className="text-xs text-gray-400">{batches.length} lote{batches.length !== 1 ? 's' : ''}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50/60">
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Nome</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Progresso</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Leads</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Data</th>
                  <th className="px-5 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Acao</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {batches.slice(0, 10).map((batch) => (
                  <tr key={`batch-${batch.id}`} className="hover:bg-gray-50/50 transition-colors">
                    <td className="px-5 py-3.5 text-sm font-medium text-gray-900 max-w-[200px] truncate" title={batch.name}>
                      {batch.name}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={batch.status} />
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2">
                        <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary-500 rounded-full progress-bar-animated"
                            style={{ width: `${batch.total_urls > 0 ? (batch.processed_urls / batch.total_urls) * 100 : 0}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-500">{batch.processed_urls}/{batch.total_urls}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-sm text-gray-700 font-medium">{batch.total_leads}</td>
                    <td className="px-5 py-3.5 text-sm text-gray-500">{formatDate(batch.created_at)}</td>
                    <td className="px-5 py-3.5 text-right">
                      <Link href={`/batch/${batch.id}`}>
                        <button className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-primary-700 bg-primary-50 hover:bg-primary-100 rounded-lg transition-colors">
                          Ver <ChevronRight className="w-3 h-3" />
                        </button>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Jobs Table */}
      {jobs.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">Scraping Individual</h2>
            <span className="text-xs text-gray-400">{jobs.length} job{jobs.length !== 1 ? 's' : ''}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50/60">
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">URL</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Resultados</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Data</th>
                  <th className="px-5 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Acao</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {jobs.slice(0, 10).map((job) => (
                  <tr key={job.id} className="hover:bg-gray-50/50 transition-colors">
                    <td className="px-5 py-3.5 text-sm text-gray-700 max-w-[250px] truncate font-mono text-xs" title={job.url}>
                      {job.url}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="px-5 py-3.5 text-sm text-gray-700 font-medium">{job.results_count}</td>
                    <td className="px-5 py-3.5 text-sm text-gray-500">{formatDate(job.created_at)}</td>
                    <td className="px-5 py-3.5 text-right">
                      <Link href={`/results/${job.id}`}>
                        <button className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-primary-700 bg-primary-50 hover:bg-primary-100 rounded-lg transition-colors">
                          Ver <ChevronRight className="w-3 h-3" />
                        </button>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty state */}
      {batches.length === 0 && jobs.length === 0 && (
        <EmptyState
          icon={Search}
          title="Nenhum scraping realizado"
          description="Comece extraindo dados de um site ou importando uma lista de URLs"
          action={
            <Link href="/scrape">
              <button className="mt-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white text-sm font-medium rounded-lg transition-colors">
                Iniciar Extracao
              </button>
            </Link>
          }
        />
      )}
    </div>
  )
}
