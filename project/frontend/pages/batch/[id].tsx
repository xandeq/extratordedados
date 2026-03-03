import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import {
  ArrowLeft, Download, FileJson, Copy, Mail, Phone, Globe,
  Building2, Loader2, ExternalLink, Users, MessageCircle,
  Instagram, Facebook, Linkedin, Twitter, Youtube, MapPin, FileText
} from 'lucide-react'
import api from '../../lib/api'
import { formatDate } from '../../lib/formatters'
import StatusBadge from '../../components/StatusBadge'
import StatCard from '../../components/StatCard'
import LoadingSkeleton from '../../components/LoadingSkeleton'
import EmptyState from '../../components/EmptyState'
import { useToast } from '../../components/Toast'
import ExportModal from '../../components/ExportModal'

interface Lead {
  company_name: string | null
  email: string
  phone: string | null
  website: string | null
  source_url: string | null
  city: string | null
  state: string | null
  category: string | null
  extracted_at: string
  instagram: string | null
  facebook: string | null
  linkedin: string | null
  twitter: string | null
  youtube: string | null
  whatsapp: string | null
  cnpj: string | null
  address: string | null
}

interface SearchJob {
  id: number
  city: string
  state: string
  engine: string
  status: string
  total_results: number
  processed_results: number
  total_leads: number
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  enrichment_source: string | null
}

interface SearchLog {
  id: number
  type: string
  url: string | null
  status_code: number | null
  message: string
  duration_ms: number
  created_at: string
  city: string
  state: string
}

interface Batch {
  batch_id: number
  name: string
  status: string
  total_urls: number
  processed_urls: number
  total_leads: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  leads: Lead[]
}

export default function BatchResults() {
  const router = useRouter()
  const { addToast } = useToast()
  const [batchId, setBatchId] = useState<string | null>(null)
  const [batch, setBatch] = useState<Batch | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const pollRef = useRef<NodeJS.Timeout | null>(null)
  const [showExport, setShowExport] = useState(false)
  const [isSearch, setIsSearch] = useState(false)
  const [searchJobs, setSearchJobs] = useState<SearchJob[]>([])
  const [searchLogs, setSearchLogs] = useState<SearchLog[]>([])
  const [showLogs, setShowLogs] = useState(false)

  useEffect(() => {
    let id = router.query.id as string
    if (!id && typeof window !== 'undefined') {
      const parts = window.location.pathname.split('/')
      const lastPart = parts.filter(p => p).pop()
      if (lastPart && !isNaN(Number(lastPart))) id = lastPart
    }
    if (id) setBatchId(id)
  }, [router.query])

  useEffect(() => {
    if (!batchId) return
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }
    fetchBatch(batchId)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [batchId])

  const fetchBatch = async (id: string) => {
    try {
      const response = await api.get(`/api/batch/${id}`)
      setBatch(response.data)
      setLoading(false)

      // Check if this is a search batch
      try {
        const searchResp = await api.get(`/api/search/${id}/progress`)
        if (searchResp.data && searchResp.data.is_search) {
          setIsSearch(true)
          setSearchJobs(searchResp.data.search_jobs || [])
        }
      } catch { /* not a search batch */ }

      if (response.data.status === 'processing' || response.data.status === 'pending') {
        startPolling(id)
      } else if (response.data.status === 'completed') {
        // Fetch logs for completed search batches
        try {
          const logsResp = await api.get(`/api/search/${id}/logs`)
          if (logsResp.data.logs && logsResp.data.logs.length > 0) {
            setSearchLogs(logsResp.data.logs)
            setIsSearch(true)
          }
        } catch { /* ignore */ }
      }
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao carregar batch')
      if (err.response?.status === 401) router.push('/login')
      setLoading(false)
    }
  }

  const startPolling = (id: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        // Try search progress first
        const searchResp = await api.get(`/api/search/${id}/progress`).catch(() => null)
        if (searchResp && searchResp.data && searchResp.data.is_search) {
          const sp = searchResp.data
          setIsSearch(true)
          setSearchJobs(sp.search_jobs || [])
          setBatch(prev => prev ? {
            ...prev,
            status: sp.status,
            total_urls: sp.total_cities,
            processed_urls: sp.processed_cities,
            total_leads: sp.total_leads,
            name: sp.name || prev.name,
          } : prev)

          if (sp.status === 'completed' || sp.status === 'failed') {
            if (pollRef.current) clearInterval(pollRef.current)
            const full = await api.get(`/api/batch/${id}`)
            setBatch(full.data)
            // Fetch logs
            try {
              const logsResp = await api.get(`/api/search/${id}/logs`)
              setSearchLogs(logsResp.data.logs || [])
            } catch { /* ignore */ }
          }
          return
        }

        // Fallback to regular batch progress
        const resp = await api.get(`/api/batch/${id}/progress`)
        const progress = resp.data
        setBatch(prev => prev ? { ...prev, ...progress } : prev)
        if (progress.status === 'completed' || progress.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current)
          const full = await api.get(`/api/batch/${id}`)
          setBatch(full.data)
        }
      } catch { /* ignore poll errors */ }
    }, 3000)
  }

  const downloadCSV = () => {
    if (!batch || !batch.leads) return
    let csv = 'Empresa,Email,Telefone,WhatsApp,CNPJ,Instagram,Facebook,LinkedIn,Twitter,YouTube,Endereco,Cidade,Estado,Website,Origem,Tags\n'
    batch.leads.forEach((l) => {
      csv += `"${l.company_name || ''}","${l.email}","${l.phone || ''}","${l.whatsapp || ''}","${l.cnpj || ''}","${l.instagram || ''}","${l.facebook || ''}","${l.linkedin || ''}","${l.twitter || ''}","${l.youtube || ''}","${l.address || ''}","${l.city || ''}","${l.state || ''}","${l.website || ''}","${l.source_url || ''}","${l.category || ''}"\n`
    })
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${batch.name || 'batch'}_leads.csv`
    a.click()
    addToast('CSV baixado com sucesso!', 'success')
  }

  const downloadJSON = () => {
    if (!batch || !batch.leads) return
    const data = batch.leads.map(l => ({
      company_name: l.company_name || '',
      email: l.email,
      phone: l.phone || '',
      whatsapp: l.whatsapp || '',
      cnpj: l.cnpj || '',
      instagram: l.instagram || '',
      facebook: l.facebook || '',
      linkedin: l.linkedin || '',
      twitter: l.twitter || '',
      youtube: l.youtube || '',
      website: l.website || '',
      address: l.address || '',
      city: l.city || '',
      state: l.state || '',
    }))
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${batch.name || 'batch'}_leads.json`
    a.click()
    addToast('JSON baixado com sucesso!', 'success')
  }

  const copyText = () => {
    if (!batch || !batch.leads) return
    const text = batch.leads
      .map(l => [l.email, l.phone, l.company_name].filter(Boolean).join(' | '))
      .join('\n')
    navigator.clipboard.writeText(text)
    addToast('Leads copiados para o clipboard!', 'success')
  }

  const progressPct = batch
    ? batch.total_urls > 0 ? Math.round((batch.processed_urls / batch.total_urls) * 100) : 0
    : 0

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
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900">Resultados do Lote</h1>
          {batch && <p className="text-sm text-gray-500 mt-0.5">{batch.name}</p>}
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
          {error}
        </div>
      )}

      {batch && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <p className="text-sm font-medium text-gray-500 mb-1">Status</p>
              <StatusBadge status={batch.status} size="md" />
            </div>
            <StatCard label="Progresso" value={`${batch.processed_urls}/${batch.total_urls}`} icon={Globe} color="blue" subtitle="URLs processadas" />
            <StatCard label="Leads" value={batch.total_leads} icon={Users} color="green" subtitle="encontrados" />
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <p className="text-sm font-medium text-gray-500 mb-1">Data</p>
              <p className="text-lg font-bold text-gray-900">{formatDate(batch.created_at)}</p>
            </div>
          </div>

          {/* Progress Bar */}
          {(batch.status === 'processing' || batch.status === 'pending') && (
            <div className="relative h-3 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="absolute inset-y-0 left-0 bg-gradient-to-r from-primary-500 to-primary-400 rounded-full progress-bar-animated"
                style={{ width: `${progressPct}%` }}
              />
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-[10px] font-bold text-gray-700">{progressPct}%</span>
              </div>
            </div>
          )}

          {/* Processing indicator */}
          {batch.status === 'processing' && (
            <div className="flex items-center gap-2 px-4 py-3 bg-blue-50 border border-blue-100 rounded-xl text-blue-700 text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              Processando... Atualizacao automatica a cada 3 segundos
            </div>
          )}

          {/* Search Sub-Jobs by City */}
          {isSearch && searchJobs.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="text-sm font-semibold text-gray-900 mb-3">
                Progresso por Cidade ({searchJobs.filter(j => j.status === 'completed').length}/{searchJobs.length})
              </h2>
              <div className="space-y-2">
                {searchJobs.map((job) => {
                  const pct = job.total_results > 0
                    ? Math.round((job.processed_results / job.total_results) * 100)
                    : job.status === 'completed' ? 100 : 0
                  return (
                    <div key={job.id} className="flex items-center gap-3 text-sm">
                      {/* Status indicator */}
                      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        job.status === 'completed' ? 'bg-green-500' :
                        job.status === 'processing' ? 'bg-blue-500 animate-pulse' :
                        job.status === 'failed' ? 'bg-red-500' :
                        job.status === 'paused' ? 'bg-amber-500' :
                        'bg-gray-300'
                      }`} />
                      {/* City */}
                      <span className="w-32 font-medium text-gray-800 truncate">{job.city}/{job.state}</span>
                      {/* Engine badge */}
                      {job.engine && (
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          job.engine === 'duckduckgo'
                            ? 'bg-orange-50 text-orange-600 border border-orange-200'
                            : 'bg-sky-50 text-sky-600 border border-sky-200'
                        }`}>
                          {job.engine === 'duckduckgo' ? 'DDG' : 'Bing'}
                        </span>
                      )}
                      {/* Enrichment source badge */}
                      {job.enrichment_source && job.enrichment_source !== 'scraping' && (
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          job.enrichment_source === 'api_hunter'
                            ? 'bg-green-50 text-green-600 border border-green-200'
                            : job.enrichment_source === 'api_snov'
                            ? 'bg-blue-50 text-blue-600 border border-blue-200'
                            : job.enrichment_source === 'api_mixed'
                            ? 'bg-purple-50 text-purple-600 border border-purple-200'
                            : 'bg-gray-50 text-gray-600 border border-gray-200'
                        }`}>
                          {job.enrichment_source === 'api_hunter' ? 'API Hunter' :
                           job.enrichment_source === 'api_snov' ? 'API Snov' :
                           job.enrichment_source === 'api_mixed' ? 'API Mix' :
                           job.enrichment_source}
                        </span>
                      )}
                      {/* Progress bar */}
                      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            job.status === 'completed' ? 'bg-green-500' :
                            job.status === 'processing' ? 'bg-blue-500' :
                            job.status === 'failed' ? 'bg-red-500' :
                            'bg-gray-300'
                          }`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      {/* Stats */}
                      <span className="text-xs text-gray-500 whitespace-nowrap">
                        {job.total_results} resultados, {job.total_leads} leads
                      </span>
                      {/* Error */}
                      {job.error_message && (
                        <span className="text-xs text-red-500 truncate max-w-[120px]" title={job.error_message}>
                          {job.error_message}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Search Logs (collapsible) */}
          {isSearch && searchLogs.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200">
              <button
                onClick={() => setShowLogs(!showLogs)}
                className="w-full flex items-center justify-between px-5 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors rounded-xl"
              >
                <span>Logs de Execucao ({searchLogs.length})</span>
                <span className="text-gray-400">{showLogs ? '▲' : '▼'}</span>
              </button>
              {showLogs && (
                <div className="border-t border-gray-200 max-h-64 overflow-y-auto">
                  <div className="divide-y divide-gray-50">
                    {searchLogs.slice(0, 100).map((log) => (
                      <div key={log.id} className="px-5 py-2 text-xs">
                        <div className="flex items-center gap-2">
                          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                            log.type === 'error' || log.type === 'crawl_error' ? 'bg-red-500' :
                            log.type === 'safety_pause' ? 'bg-amber-500' :
                            log.type === 'complete' || log.type === 'crawl_complete' ? 'bg-green-500' :
                            'bg-gray-400'
                          }`} />
                          <span className="text-gray-400 w-24 flex-shrink-0">
                            {log.city}/{log.state}
                          </span>
                          <span className="text-gray-600 flex-1 truncate">{log.message}</span>
                          {log.duration_ms > 0 && (
                            <span className="text-gray-400 flex-shrink-0">{log.duration_ms}ms</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Export Actions */}
          {batch.status === 'completed' && batch.leads && batch.leads.length > 0 && (
            <div className="flex items-center gap-3 flex-wrap">
              <button
                onClick={downloadCSV}
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
              >
                <Download className="w-4 h-4" />
                CSV CRM
              </button>
              <button
                onClick={downloadJSON}
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 text-sm font-medium rounded-xl transition-colors"
              >
                <FileJson className="w-4 h-4" />
                JSON
              </button>
              <button
                onClick={copyText}
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 text-sm font-medium rounded-xl transition-colors"
              >
                <Copy className="w-4 h-4" />
                Copiar Texto
              </button>
              <button
                onClick={() => setShowExport(true)}
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
              >
                <FileText className="w-4 h-4" />
                Exportar Marketing
              </button>
            </div>
          )}

          {/* Leads Cards */}
          {batch.leads && batch.leads.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-base font-semibold text-gray-900">
                Leads Encontrados ({batch.leads.length})
              </h2>
              {batch.leads.map((lead, idx) => (
                <div key={idx} className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-sm transition-shadow">
                  {/* Lead header */}
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center">
                        <Building2 className="w-4.5 h-4.5 text-primary-600" />
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-gray-900">{lead.company_name || 'Sem nome'}</h3>
                        {lead.cnpj && (
                          <p className="text-xs text-gray-400 font-mono">{lead.cnpj}</p>
                        )}
                      </div>
                    </div>
                    {lead.website && (
                      <a href={lead.website} target="_blank" rel="noopener noreferrer"
                         className="text-xs text-primary-600 hover:underline flex items-center gap-1">
                        <ExternalLink className="w-3 h-3" />
                        {lead.website.replace(/^https?:\/\/(www\.)?/, '').substring(0, 25)}
                      </a>
                    )}
                  </div>

                  {/* Contact info grid */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 mb-3">
                    <a href={`mailto:${lead.email}`} className="flex items-center gap-2 text-sm text-primary-600 hover:text-primary-700 hover:underline">
                      <Mail className="w-3.5 h-3.5 flex-shrink-0" />
                      <span className="truncate">{lead.email}</span>
                    </a>
                    {lead.phone && (
                      <span className="flex items-center gap-2 text-sm text-gray-700">
                        <Phone className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                        {lead.phone}
                      </span>
                    )}
                    {lead.whatsapp && (
                      <a href={`https://wa.me/${lead.whatsapp.replace(/\D/g, '')}`} target="_blank" rel="noopener noreferrer"
                         className="flex items-center gap-2 text-sm text-green-600 hover:text-green-700 hover:underline">
                        <MessageCircle className="w-3.5 h-3.5 flex-shrink-0" />
                        {lead.whatsapp}
                      </a>
                    )}
                    {lead.address && (
                      <span className="flex items-center gap-2 text-sm text-gray-600 col-span-full truncate" title={lead.address}>
                        <MapPin className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                        {lead.address.substring(0, 60)}{lead.city ? ` - ${lead.city}` : ''}{lead.state ? `/${lead.state}` : ''}
                      </span>
                    )}
                    {!lead.address && (lead.city || lead.state) && (
                      <span className="flex items-center gap-2 text-sm text-gray-600">
                        <MapPin className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                        {[lead.city, lead.state].filter(Boolean).join('/')}
                      </span>
                    )}
                  </div>

                  {/* Social media row */}
                  {(lead.instagram || lead.facebook || lead.linkedin || lead.twitter || lead.youtube) && (
                    <div className="flex items-center gap-2 pt-2.5 border-t border-gray-100">
                      {lead.instagram && (
                        <a href={lead.instagram} target="_blank" rel="noopener noreferrer"
                           className="p-1.5 rounded-md hover:bg-pink-50 text-gray-400 hover:text-pink-500 transition-colors" title="Instagram">
                          <Instagram className="w-4 h-4" />
                        </a>
                      )}
                      {lead.facebook && (
                        <a href={lead.facebook} target="_blank" rel="noopener noreferrer"
                           className="p-1.5 rounded-md hover:bg-blue-50 text-gray-400 hover:text-blue-600 transition-colors" title="Facebook">
                          <Facebook className="w-4 h-4" />
                        </a>
                      )}
                      {lead.linkedin && (
                        <a href={lead.linkedin} target="_blank" rel="noopener noreferrer"
                           className="p-1.5 rounded-md hover:bg-sky-50 text-gray-400 hover:text-sky-600 transition-colors" title="LinkedIn">
                          <Linkedin className="w-4 h-4" />
                        </a>
                      )}
                      {lead.twitter && (
                        <a href={lead.twitter} target="_blank" rel="noopener noreferrer"
                           className="p-1.5 rounded-md hover:bg-gray-100 text-gray-400 hover:text-gray-700 transition-colors" title="X / Twitter">
                          <Twitter className="w-4 h-4" />
                        </a>
                      )}
                      {lead.youtube && (
                        <a href={lead.youtube} target="_blank" rel="noopener noreferrer"
                           className="p-1.5 rounded-md hover:bg-red-50 text-gray-400 hover:text-red-500 transition-colors" title="YouTube">
                          <Youtube className="w-4 h-4" />
                        </a>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Empty state */}
          {batch.status === 'completed' && (!batch.leads || batch.leads.length === 0) && (
            <EmptyState
              icon={Users}
              title="Nenhum lead encontrado"
              description="Nenhum email ou dado de contato foi encontrado neste lote de URLs"
            />
          )}
        </>
      )}

      {/* Export Modal */}
      {showExport && batchId && (
        <ExportModal
          onClose={() => setShowExport(false)}
          totalLeads={batch?.total_leads || 0}
          filters={{ batch_id: batchId }}
        />
      )}
    </div>
  )
}
