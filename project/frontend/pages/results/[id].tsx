import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import { ArrowLeft, Download, Copy, Mail, Globe, Calendar, Hash } from 'lucide-react'
import api from '../../lib/api'
import { formatDate } from '../../lib/formatters'
import StatusBadge from '../../components/StatusBadge'
import StatCard from '../../components/StatCard'
import LoadingSkeleton from '../../components/LoadingSkeleton'
import EmptyState from '../../components/EmptyState'
import { useToast } from '../../components/Toast'

interface Email {
  email: string
  source_url: string
  extracted_at: string
}

interface Result {
  job_id: number
  url: string
  status: string
  results_count: number
  created_at: string
  emails: Email[]
}

export default function Results() {
  const router = useRouter()
  const { addToast } = useToast()
  const [jobId, setJobId] = useState<string | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let id = router.query.id as string
    if (!id && typeof window !== 'undefined') {
      const parts = window.location.pathname.split('/')
      const lastPart = parts.filter(p => p).pop()
      if (lastPart && !isNaN(Number(lastPart))) id = lastPart
    }
    if (id) setJobId(id)
  }, [router.query])

  useEffect(() => {
    if (!jobId) return
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }
    fetchResults(jobId)
  }, [jobId])

  const fetchResults = async (id: string) => {
    try {
      const response = await api.get(`/api/results/${id}`)
      setResult(response.data)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao carregar resultados')
      if (err.response?.status === 401) router.push('/login')
    } finally {
      setLoading(false)
    }
  }

  const downloadCSV = () => {
    if (!result || !result.emails) return
    let csv = 'Email,URL Origem,Data Extracao\n'
    result.emails.forEach((e) => {
      csv += `"${e.email}","${e.source_url}","${e.extracted_at}"\n`
    })
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `emails_${result.job_id}.csv`
    a.click()
    addToast('CSV baixado com sucesso!', 'success')
  }

  const copyToClipboard = () => {
    if (!result || !result.emails) return
    const text = result.emails.map((e) => e.email).join('\n')
    navigator.clipboard.writeText(text)
    addToast('Emails copiados para o clipboard!', 'success')
  }

  if (loading) return <LoadingSkeleton />

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/dashboard">
          <button className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-gray-500" />
          </button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Resultados do Scraping</h1>
          {result && (
            <p className="text-sm text-gray-500 mt-0.5 font-mono truncate max-w-md">{result.url}</p>
          )}
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
          {error}
        </div>
      )}

      {result && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <p className="text-sm font-medium text-gray-500 mb-1">Status</p>
              <StatusBadge status={result.status} size="md" />
            </div>
            <StatCard label="Emails" value={result.results_count} icon={Mail} color="blue" />
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <p className="text-sm font-medium text-gray-500 mb-1">URL</p>
              <p className="text-sm font-mono text-gray-900 break-all leading-relaxed">{result.url}</p>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <p className="text-sm font-medium text-gray-500 mb-1">Data</p>
              <p className="text-lg font-bold text-gray-900">{formatDate(result.created_at)}</p>
            </div>
          </div>

          {/* Actions */}
          {result.emails && result.emails.length > 0 && (
            <div className="flex items-center gap-3 flex-wrap">
              <button
                onClick={downloadCSV}
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
              >
                <Download className="w-4 h-4" />
                Download CSV
              </button>
              <button
                onClick={copyToClipboard}
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 text-sm font-medium rounded-xl transition-colors"
              >
                <Copy className="w-4 h-4" />
                Copiar Emails
              </button>
            </div>
          )}

          {/* Emails Table */}
          {result.emails && result.emails.length > 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100">
                <h2 className="text-base font-semibold text-gray-900">
                  Emails Encontrados ({result.emails.length})
                </h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-gray-50/60">
                      <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Email</th>
                      <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">URL Origem</th>
                      <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Data</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {result.emails.map((email, idx) => (
                      <tr key={idx} className="hover:bg-gray-50/50 transition-colors">
                        <td className="px-5 py-3 text-sm">
                          <a
                            href={`mailto:${email.email}`}
                            className="text-primary-600 hover:text-primary-700 hover:underline flex items-center gap-1.5"
                          >
                            <Mail className="w-3.5 h-3.5 flex-shrink-0" />
                            {email.email}
                          </a>
                        </td>
                        <td className="px-5 py-3 text-sm text-gray-500 max-w-[250px] truncate" title={email.source_url}>
                          {email.source_url}
                        </td>
                        <td className="px-5 py-3 text-sm text-gray-500">
                          {formatDate(email.extracted_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <EmptyState
              icon={Mail}
              title="Nenhum email encontrado"
              description="Nenhum email foi encontrado nesta URL"
            />
          )}
        </>
      )}
    </div>
  )
}
