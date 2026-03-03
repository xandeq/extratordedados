import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import {
  Search, Database, ChevronLeft, ChevronRight, Check,
  Tag, Filter, Mail, Phone, Building2, MessageCircle,
  Instagram, Facebook, Linkedin, ExternalLink, MoreHorizontal,
  Users, ArrowUpDown, Download
} from 'lucide-react'
import api from '../lib/api'
import { useToast } from '../components/Toast'
import StatusBadge from '../components/StatusBadge'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import LeadDrawer from '../components/LeadDrawer'
import ExportModal from '../components/ExportModal'

interface Lead {
  id: number
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
  crm_status: string
  tags: string
  notes: string
  contact_name: string
  batch_name: string
  batch_id: number
}

const CRM_STATUSES = [
  { value: '', label: 'Todos' },
  { value: 'novo', label: 'Novo' },
  { value: 'contatado', label: 'Contatado' },
  { value: 'interessado', label: 'Interessado' },
  { value: 'negociando', label: 'Negociando' },
  { value: 'cliente', label: 'Cliente' },
  { value: 'descartado', label: 'Descartado' },
]

const SORT_OPTIONS = [
  { value: 'newest', label: 'Mais recentes' },
  { value: 'oldest', label: 'Mais antigos' },
  { value: 'company', label: 'Empresa A-Z' },
  { value: 'status', label: 'Status' },
  { value: 'updated', label: 'Atualizados' },
]

export default function Leads() {
  const router = useRouter()
  const { addToast } = useToast()

  const [leads, setLeads] = useState<Lead[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({})
  const [allTags, setAllTags] = useState<string[]>([])

  // Filters
  const [search, setSearch] = useState('')
  const [searchDebounced, setSearchDebounced] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [sort, setSort] = useState('newest')

  // Selection
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [showBulkMenu, setShowBulkMenu] = useState(false)

  // Drawer
  const [drawerLead, setDrawerLead] = useState<Lead | null>(null)

  // Export
  const [showExport, setShowExport] = useState(false)

  // Tag input modal (replaces prompt())
  const [showTagInput, setShowTagInput] = useState(false)
  const [tagInputValue, setTagInputValue] = useState('')

  const tagInputRef = useRef<HTMLInputElement>(null)

  // Listen for global Esc (close modal event from Layout shortcuts)
  useEffect(() => {
    const handler = () => {
      if (showTagInput) { setShowTagInput(false); return }
      if (showExport) { setShowExport(false); return }
      if (drawerLead) { setDrawerLead(null); return }
    }
    window.addEventListener('app:close-modal', handler)
    return () => window.removeEventListener('app:close-modal', handler)
  }, [showTagInput, showExport, drawerLead])

  // Auto-focus tag input when shown
  useEffect(() => {
    if (showTagInput && tagInputRef.current) tagInputRef.current.focus()
  }, [showTagInput])

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearchDebounced(search)
      setPage(1)
    }, 400)
    return () => clearTimeout(timer)
  }, [search])

  const fetchLeads = useCallback(async () => {
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }

    try {
      const params = new URLSearchParams({
        page: page.toString(),
        per_page: '50',
        sort,
      })
      if (searchDebounced) params.append('search', searchDebounced)
      if (statusFilter) params.append('status', statusFilter)
      if (tagFilter) params.append('tag', tagFilter)

      const res = await api.get(`/api/leads?${params.toString()}`)
      setLeads(res.data.leads)
      setTotal(res.data.total)
      setTotalPages(res.data.total_pages)
      setStatusCounts(res.data.status_counts || {})
      setAllTags(res.data.all_tags || [])
    } catch (err: any) {
      if (err.response?.status === 401) router.push('/login')
    } finally {
      setLoading(false)
    }
  }, [page, sort, searchDebounced, statusFilter, tagFilter])

  useEffect(() => { fetchLeads() }, [fetchLeads])

  const toggleSelect = (id: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selected.size === leads.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(leads.map(l => l.id)))
    }
  }

  const handleBulkStatus = async (newStatus: string) => {
    if (selected.size === 0) return
    try {
      await api.put('/api/leads/bulk-status', {
        lead_ids: Array.from(selected),
        crm_status: newStatus,
      })
      addToast(`${selected.size} leads atualizados para "${newStatus}"`, 'success')
      setSelected(new Set())
      setShowBulkMenu(false)
      fetchLeads()
    } catch {
      addToast('Erro ao atualizar leads', 'error')
    }
  }

  const handleBulkTag = () => {
    if (selected.size === 0) return
    setTagInputValue('')
    setShowTagInput(true)
  }

  const submitBulkTag = async () => {
    if (!tagInputValue.trim()) return
    try {
      await api.put('/api/leads/bulk-tag', {
        lead_ids: Array.from(selected),
        tag: tagInputValue.trim(),
      })
      addToast(`Tag "${tagInputValue.trim()}" adicionada a ${selected.size} leads`, 'success')
      setSelected(new Set())
      setShowTagInput(false)
      setTagInputValue('')
      fetchLeads()
    } catch {
      addToast('Erro ao adicionar tag', 'error')
    }
  }

  const handleDrawerUpdate = (updatedLead: Lead) => {
    setLeads(prev => prev.map(l => l.id === updatedLead.id ? updatedLead : l))
    setDrawerLead(updatedLead)
  }

  const totalAll = Object.values(statusCounts).reduce((a, b) => a + b, 0)

  if (loading) return <LoadingSkeleton />

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Leads CRM</h1>
          <p className="text-sm text-gray-500 mt-0.5">{total} leads encontrados</p>
        </div>
        {total > 0 && (
          <button
            onClick={() => setShowExport(true)}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
          >
            <Download className="w-4 h-4" />
            Exportar
          </button>
        )}
      </div>

      {/* Status pills */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        {CRM_STATUSES.map((s) => {
          const count = s.value ? (statusCounts[s.value] || 0) : totalAll
          const active = statusFilter === s.value
          return (
            <button
              key={s.value}
              onClick={() => { setStatusFilter(s.value); setPage(1) }}
              className={`
                inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all
                ${active
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
                }
              `}
            >
              {s.label}
              <span className={`text-[10px] ${active ? 'text-primary-200' : 'text-gray-400'}`}>
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* Search + Filters bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar empresa, email, telefone, CNPJ..."
            className="w-full pl-10 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all"
          />
        </div>

        {/* Tag filter */}
        {allTags.length > 0 && (
          <select
            value={tagFilter}
            onChange={(e) => { setTagFilter(e.target.value); setPage(1) }}
            className="px-3 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500/30"
          >
            <option value="">Todas as tags</option>
            {allTags.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}

        {/* Sort */}
        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value); setPage(1) }}
          className="px-3 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500/30"
        >
          {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      {/* Bulk actions */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 px-4 py-3 bg-primary-50 border border-primary-100 rounded-xl">
          <span className="text-sm font-medium text-primary-700">{selected.size} selecionado{selected.size > 1 ? 's' : ''}</span>
          <div className="flex items-center gap-2 ml-auto">
            <div className="relative">
              <button
                onClick={() => setShowBulkMenu(!showBulkMenu)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                <ArrowUpDown className="w-3.5 h-3.5" />
                Mudar Status
              </button>
              {showBulkMenu && (
                <div className="absolute top-full left-0 mt-1 w-44 bg-white rounded-xl border border-gray-200 shadow-lg z-30 py-1">
                  {CRM_STATUSES.filter(s => s.value).map((s) => (
                    <button
                      key={s.value}
                      onClick={() => handleBulkStatus(s.value)}
                      className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={handleBulkTag}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              <Tag className="w-3.5 h-3.5" />
              Adicionar Tag
            </button>
            <button
              onClick={() => setShowExport(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              <Download className="w-3.5 h-3.5" />
              Exportar
            </button>
            <button
              onClick={() => setSelected(new Set())}
              className="text-xs text-gray-500 hover:text-gray-700 underline"
            >
              Limpar
            </button>
          </div>
        </div>
      )}

      {/* Table */}
      {leads.length > 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px]">
              <thead>
                <tr className="bg-gray-50/60">
                  <th className="px-4 py-3 w-10">
                    <input
                      type="checkbox"
                      checked={selected.size === leads.length && leads.length > 0}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Empresa</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Contato</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Redes</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Tags</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Lote</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {leads.map((lead) => (
                  <tr
                    key={lead.id}
                    className={`hover:bg-gray-50/50 transition-colors cursor-pointer ${selected.has(lead.id) ? 'bg-primary-50/30' : ''}`}
                    onClick={() => setDrawerLead(lead)}
                  >
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(lead.id)}
                        onChange={() => toggleSelect(lead.id)}
                        className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
                          <Building2 className="w-4 h-4 text-gray-400" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-gray-900 truncate max-w-[180px]">
                            {lead.company_name || 'Sem nome'}
                          </p>
                          {lead.cnpj && (
                            <p className="text-[10px] text-gray-400 font-mono">{lead.cnpj}</p>
                          )}
                          {lead.city && (
                            <p className="text-[10px] text-gray-400">{lead.city}{lead.state ? `/${lead.state}` : ''}</p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="space-y-1">
                        <p className="text-sm text-gray-700 truncate max-w-[200px]">{lead.email}</p>
                        {lead.phone && (
                          <p className="text-xs text-gray-400 flex items-center gap-1">
                            <Phone className="w-3 h-3" /> {lead.phone}
                          </p>
                        )}
                        {lead.whatsapp && (
                          <p className="text-xs text-green-500 flex items-center gap-1">
                            <MessageCircle className="w-3 h-3" /> WA
                          </p>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={lead.crm_status || 'novo'} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-0.5">
                        {lead.instagram && <Instagram className="w-3.5 h-3.5 text-pink-400" />}
                        {lead.facebook && <Facebook className="w-3.5 h-3.5 text-blue-500" />}
                        {lead.linkedin && <Linkedin className="w-3.5 h-3.5 text-sky-500" />}
                        {!lead.instagram && !lead.facebook && !lead.linkedin && (
                          <span className="text-gray-300 text-xs">-</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {lead.tags ? (
                        <div className="flex flex-wrap gap-1 max-w-[140px]">
                          {lead.tags.split(',').slice(0, 2).map((t, i) => t.trim() && (
                            <span key={i} className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-[10px] font-medium truncate max-w-[60px]">
                              {t.trim()}
                            </span>
                          ))}
                          {lead.tags.split(',').length > 2 && (
                            <span className="text-[10px] text-gray-400">+{lead.tags.split(',').length - 2}</span>
                          )}
                        </div>
                      ) : (
                        <span className="text-gray-300 text-xs">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs text-gray-400 truncate max-w-[100px] block">{lead.batch_name}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-5 py-3 border-t border-gray-100">
              <p className="text-xs text-gray-500">
                Pagina {page} de {totalPages} ({total} leads)
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="p-1.5 rounded-lg hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-4 h-4 text-gray-600" />
                </button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let p = page <= 3 ? i + 1 : page + i - 2
                  if (p > totalPages) return null
                  if (p < 1) return null
                  return (
                    <button
                      key={p}
                      onClick={() => setPage(p)}
                      className={`w-8 h-8 rounded-lg text-xs font-medium transition-colors ${
                        p === page ? 'bg-primary-600 text-white' : 'text-gray-600 hover:bg-gray-100'
                      }`}
                    >
                      {p}
                    </button>
                  )
                })}
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="p-1.5 rounded-lg hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="w-4 h-4 text-gray-600" />
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <EmptyState
          icon={Database}
          title="Nenhum lead encontrado"
          description={search || statusFilter || tagFilter
            ? 'Tente alterar os filtros de busca'
            : 'Faca uma extracao para comecar a gerenciar seus leads'}
          action={!search && !statusFilter ? (
            <Link href="/scrape">
              <button className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white text-sm font-semibold rounded-xl transition-colors">
                Nova Extracao
              </button>
            </Link>
          ) : undefined}
        />
      )}

      {/* Lead Drawer */}
      {drawerLead && (
        <LeadDrawer
          lead={drawerLead}
          onClose={() => setDrawerLead(null)}
          onUpdate={handleDrawerUpdate}
        />
      )}

      {/* Export Modal */}
      {showExport && (
        <ExportModal
          onClose={() => setShowExport(false)}
          totalLeads={total}
          filters={{
            search: searchDebounced || undefined,
            status: statusFilter || undefined,
            tag: tagFilter || undefined,
            ids: selected.size > 0 ? Array.from(selected) : undefined,
          }}
        />
      )}

      {/* Tag Input Mini-Modal */}
      {showTagInput && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={() => setShowTagInput(false)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-sm p-6 animate-fade-in">
              <h3 className="text-base font-bold text-gray-900 dark:text-gray-100 mb-1">Adicionar Tag</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                {selected.size} lead{selected.size > 1 ? 's' : ''} selecionado{selected.size > 1 ? 's' : ''}
              </p>
              <input
                ref={tagInputRef}
                type="text"
                value={tagInputValue}
                onChange={(e) => setTagInputValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') submitBulkTag() }}
                placeholder="Nome da tag..."
                className="w-full px-4 py-3 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all mb-4"
              />
              {allTags.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-4">
                  {allTags.slice(0, 8).map(t => (
                    <button
                      key={t}
                      onClick={() => setTagInputValue(t)}
                      className="px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded-md text-xs font-medium hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                    >
                      {t}
                    </button>
                  ))}
                </div>
              )}
              <div className="flex gap-3">
                <button
                  onClick={() => setShowTagInput(false)}
                  className="flex-1 px-4 py-2.5 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-xl font-medium text-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  Cancelar
                </button>
                <button
                  onClick={submitBulkTag}
                  disabled={!tagInputValue.trim()}
                  className="flex-1 px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-50"
                >
                  Adicionar
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
