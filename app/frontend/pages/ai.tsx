import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import { ExternalLink, Mail, Clock, CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import api from '../lib/api'
import { formatDate } from '../lib/formatters'
import StatusBadge from '../components/StatusBadge'
import EmptyState from '../components/EmptyState'
import LoadingSkeleton from '../components/LoadingSkeleton'

interface Job {
  id: number
  url: string
  status: string
  results_count: number
  created_at: string
}

export default function AiPage() {
  const router = useRouter()
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }

    api.get('/api/results')
      .then(res => setJobs(res.data.jobs || []))
      .catch(err => {
        if (err.response?.status === 401) router.push('/login')
        else setError(err.response?.data?.error || 'Erro ao carregar histórico')
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSkeleton />

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Histórico de Análises</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
          Extrações de URL única realizadas — clique em "Ver Análise" para ver os emails encontrados
        </p>
      </div>

      {error && (
        <div className="px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-400 text-sm">
          {error}
        </div>
      )}

      {!error && jobs.length === 0 ? (
        <EmptyState
          icon={Mail}
          title="Nenhuma análise encontrada"
          description="Inicie uma extração de URL única na página Nova Extração"
        />
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50/60 dark:bg-gray-700/40">
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">#</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">URL</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Emails</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden sm:table-cell">Data</th>
                  <th className="px-5 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Ação</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {jobs.map(job => (
                  <tr key={job.id} className="hover:bg-gray-50/50 dark:hover:bg-gray-700/30 transition-colors">
                    <td className="px-5 py-3.5 text-sm text-gray-400 dark:text-gray-500 tabular-nums">
                      {job.id}
                    </td>
                    <td className="px-5 py-3.5 text-sm text-gray-700 dark:text-gray-300 max-w-[260px] truncate font-mono" title={job.url}>
                      {job.url}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={job.status} size="sm" />
                    </td>
                    <td className="px-5 py-3.5 text-sm font-semibold text-gray-900 dark:text-white tabular-nums">
                      {job.results_count ?? 0}
                    </td>
                    <td className="px-5 py-3.5 text-sm text-gray-500 dark:text-gray-400 hidden sm:table-cell whitespace-nowrap">
                      {job.created_at ? formatDate(job.created_at) : '—'}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <Link
                        href={`/results/${job.id}`}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-primary-600 dark:text-primary-400 border border-primary-200 dark:border-primary-800 rounded-lg hover:bg-primary-50 dark:hover:bg-primary-900/20 transition-colors whitespace-nowrap"
                      >
                        <ExternalLink className="w-3 h-3" />
                        Ver Análise
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
