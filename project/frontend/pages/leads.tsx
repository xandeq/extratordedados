import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import {
  Search, Database, ChevronLeft, ChevronRight, Check,
  Tag, Filter, Mail, Phone, Building2, MessageCircle,
  Instagram, Facebook, Linkedin, ExternalLink, MoreHorizontal,
  Users, ArrowUpDown, Download, Trash2, Sparkles, CheckCircle2,
  AlertCircle, XCircle, Copy, BadgeCheck, RefreshCw, Lock,
  Bookmark, BookmarkCheck, ChevronDown, X as XIcon
} from 'lucide-react'
import api from '../lib/api'
import { useToast } from '../components/Toast'
import StatusBadge from '../components/StatusBadge'
import LoadingSkeleton from '../components/LoadingSkeleton'
import EmptyState from '../components/EmptyState'
import LeadDrawer from '../components/LeadDrawer'
import ExportModal from '../components/ExportModal'
import UpgradeModal from '../components/UpgradeModal'
import InfoBox from '../components/InfoBox'
import Tooltip from '../components/Tooltip'
import { useClientPlan } from '../lib/useClientPlan'

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
  lead_score: number
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
  { value: 'score', label: 'Melhor score' },
]

function ScoreBadge({ score }: { score: number }) {
  const pct = score ?? 0
  const color = pct >= 70
    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
    : pct >= 40
      ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
      : 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400'
  return (
    <span className={`inline-flex items-center justify-center w-10 h-6 rounded-full text-xs font-semibold tabular-nums ${color}`}>
      {pct}
    </span>
  )
}

export default function Leads() {
  const router = useRouter()
  const { addToast } = useToast()
  const { plan, canViewLeads, canExport, usage, limits } = useClientPlan()

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
  const [cityFilter, setCityFilter] = useState('')
  const [stateFilter, setStateFilter] = useState('')
  const [sort, setSort] = useState('newest')

  // Location options
  const [availableCities, setAvailableCities] = useState<string[]>([])
  const [availableStates, setAvailableStates] = useState<string[]>([])
  const [loadingLocations, setLoadingLocations] = useState(false)

  // Selection
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [showBulkMenu, setShowBulkMenu] = useState(false)

  // Drawer
  const [drawerLead, setDrawerLead] = useState<Lead | null>(null)

  // Export
  const [showExport, setShowExport] = useState(false)

  // Send to CRM
  const [showSendToCrmModal, setShowSendToCrmModal] = useState(false)
  const [crmApiUrl, setCrmApiUrl] = useState('')
  const [crmAuthToken, setCrmAuthToken] = useState('')
  const [sendingToCrm, setSendingToCrm] = useState(false)
  const [crmSyncResult, setCrmSyncResult] = useState<{
    success: boolean
    sent_count?: number
    failed_count?: number
    message?: string
    error?: string
  } | null>(null)

  // Upgrade Modal
  const [showUpgrade, setShowUpgrade] = useState(false)
  const [upgradeReason, setUpgradeReason] = useState<'export' | 'filters' | 'generic'>('generic')

  const triggerUpgrade = (reason: 'export' | 'filters' | 'generic') => {
    setUpgradeReason(reason)
    setShowUpgrade(true)
  }

  // Tag input modal (replaces prompt())
  const [showTagInput, setShowTagInput] = useState(false)
  const [tagInputValue, setTagInputValue] = useState('')

  // Delete confirmation modal (bulk selected)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  // Sync + Delete
  const [showSyncDeleteConfirm, setShowSyncDeleteConfirm] = useState(false)
  const [syncingAndDeleting, setSyncingAndDeleting] = useState(false)
  const [syncDeleteConfirmText, setSyncDeleteConfirmText] = useState('')
  const [syncDeleteResult, setSyncDeleteResult] = useState<{
    synced: number
    skipped: number
    errors: number
    deleted: number
  } | null>(null)

  // Delete All
  const [showDeleteAllConfirm, setShowDeleteAllConfirm] = useState(false)
  const [deleteAllConfirmText, setDeleteAllConfirmText] = useState('')
  const [deletingAll, setDeletingAll] = useState(false)


  // Saved Filters
  interface SavedFilter {
    id: number
    name: string
    filters: { search?: string; status?: string; tag?: string; city?: string; state?: string; sort?: string }
    created_at: string
  }
  const [savedFilters, setSavedFilters] = useState<SavedFilter[]>([])
  const [activeFilterId, setActiveFilterId] = useState<number | null>(null)
  const [showSavedFilters, setShowSavedFilters] = useState(false)
  const [showSaveModal, setShowSaveModal] = useState(false)
  const [saveFilterName, setSaveFilterName] = useState('')
  const [savingFilter, setSavingFilter] = useState(false)

  // Sanitize
  const [sanitizing, setSanitizing] = useState(false)
  const [sanitizeReport, setSanitizeReport] = useState<{
    analyzed: number
    invalid_emails: number
    encoding_corrected: number
    spam_detected: number
    duplicates_removed: number
    no_contact_removed: number
    quality_updated: number
    ids_deleted: number
  } | null>(null)

  const tagInputRef = useRef<HTMLInputElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Close saved filters dropdown on outside click
  useEffect(() => {
    if (!showSavedFilters) return
    const handler = () => setShowSavedFilters(false)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [showSavedFilters])

  // Listen for global Esc (close modal event from Layout shortcuts)
  useEffect(() => {
    const handler = () => {
      if (showSaveModal) { setShowSaveModal(false); return }
      if (showTagInput) { setShowTagInput(false); return }
      if (showExport) { setShowExport(false); return }
      if (showSendToCrmModal) { setShowSendToCrmModal(false); setCrmSyncResult(null); return }
      if (drawerLead) { setDrawerLead(null); return }
    }
    window.addEventListener('app:close-modal', handler)
    return () => window.removeEventListener('app:close-modal', handler)
  }, [showSaveModal, showTagInput, showExport, showSendToCrmModal, drawerLead])

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

  // Fetch available locations
  useEffect(() => {
    const fetchLocations = async () => {
      const token = localStorage.getItem('token')
      if (!token) return
      try {
        setLoadingLocations(true)
        const res = await api.get('/api/leads/locations/available')
        setAvailableCities(res.data.cities || [])
        setAvailableStates(res.data.states || [])
      } catch (err) {
        // silently fail
      } finally {
        setLoadingLocations(false)
      }
    }
    fetchLocations()
  }, [])

  const fetchLeads = useCallback(async () => {
    abortControllerRef.current?.abort()
    const controller = new AbortController()
    abortControllerRef.current = controller

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
      if (cityFilter) params.append('city', cityFilter)
      if (stateFilter) params.append('state', stateFilter)

      const res = await api.get(`/api/leads?${params.toString()}`, { signal: controller.signal })
      setLeads(res.data.leads)
      setTotal(res.data.total)
      setTotalPages(res.data.total_pages)
      setStatusCounts(res.data.status_counts || {})
      setAllTags(res.data.all_tags || [])
    } catch (err: any) {
      if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') return
      if (err.response?.status === 401) router.push('/login')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [page, sort, searchDebounced, statusFilter, tagFilter, cityFilter, stateFilter])

  useEffect(() => { fetchLeads() }, [fetchLeads])

  const fetchSavedFilters = useCallback(async () => {
    try {
      const res = await api.get('/api/leads/saved-filters')
      setSavedFilters(res.data.filters || [])
    } catch {
      // silently fail — plan may not allow saved filters
    }
  }, [])

  useEffect(() => { fetchSavedFilters() }, [fetchSavedFilters])

  const hasActiveFilters = search || statusFilter || tagFilter || cityFilter || stateFilter || sort !== 'newest'

  const applyFilter = (sf: SavedFilter) => {
    setSearch(sf.filters.search || '')
    setSearchDebounced(sf.filters.search || '')
    setStatusFilter(sf.filters.status || '')
    setTagFilter(sf.filters.tag || '')
    setCityFilter(sf.filters.city || '')
    setStateFilter(sf.filters.state || '')
    setSort(sf.filters.sort || 'newest')
    setActiveFilterId(sf.id)
    setShowSavedFilters(false)
    setPage(1)
  }

  const clearAllFilters = () => {
    setSearch('')
    setSearchDebounced('')
    setStatusFilter('')
    setTagFilter('')
    setCityFilter('')
    setStateFilter('')
    setSort('newest')
    setActiveFilterId(null)
    setPage(1)
  }

  const handleSaveFilter = async () => {
    if (!saveFilterName.trim()) return
    setSavingFilter(true)
    try {
      await api.post('/api/leads/saved-filters', {
        name: saveFilterName.trim(),
        filters: {
          search: searchDebounced || undefined,
          status: statusFilter || undefined,
          tag: tagFilter || undefined,
          city: cityFilter || undefined,
          state: stateFilter || undefined,
          sort: sort !== 'newest' ? sort : undefined,
        }
      })
      addToast(`Filtro "${saveFilterName.trim()}" salvo`, 'success')
      setShowSaveModal(false)
      setSaveFilterName('')
      fetchSavedFilters()
    } catch (err: unknown) {
      const msg = (err as any)?.response?.data?.error
      if ((err as any)?.response?.data?.upgrade_required) {
        setShowSaveModal(false)
        setSaveFilterName('')
        triggerUpgrade('filters')
      } else {
        addToast(msg || 'Erro ao salvar filtro', 'error')
      }
    } finally {
      setSavingFilter(false)
    }
  }

  const handleDeleteFilter = async (id: number) => {
    try {
      await api.delete(`/api/leads/saved-filters/${id}`)
      if (activeFilterId === id) setActiveFilterId(null)
      fetchSavedFilters()
    } catch {
      addToast('Erro ao excluir filtro', 'error')
    }
  }

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

  const handleBulkDelete = () => {
    if (selected.size === 0) return
    setShowDeleteConfirm(true)
  }

  const confirmBulkDelete = async () => {
    if (selected.size === 0) return
    try {
      await api.post('/api/leads/bulk-delete', {
        lead_ids: Array.from(selected),
      })
      addToast(`${selected.size} lead${selected.size > 1 ? 's' : ''} deletado${selected.size > 1 ? 's' : ''}`, 'success')
      setSelected(new Set())
      setShowDeleteConfirm(false)
      fetchLeads()
    } catch {
      addToast('Erro ao deletar leads', 'error')
    }
  }


  const handleSanitize = async () => {
    setSanitizing(true)
    try {
      const payload = selected.size > 0 ? { lead_ids: Array.from(selected) } : {}
      const res = await api.post('/api/leads/sanitize', payload)
      setSanitizeReport(res.data.report)
      fetchLeads()
    } catch {
      addToast('Erro ao sanitizar leads', 'error')
    } finally {
      setSanitizing(false)
    }
  }

  const handleDrawerUpdate = (updatedLead: Lead) => {
    setLeads(prev => prev.map(l => l.id === updatedLead.id ? updatedLead : l))
    setDrawerLead(updatedLead)
  }

  const confirmSyncAndDelete = async () => {
    setSyncingAndDeleting(true)
    try {
      const res = await api.post('/api/crm/sync-and-delete-all')
      setSyncDeleteResult(res.data.result)
    } catch {
      addToast('Erro ao sincronizar e deletar leads', 'error')
      setShowSyncDeleteConfirm(false)
      setSyncDeleteConfirmText('')
    } finally {
      setSyncingAndDeleting(false)
    }
  }

  const confirmDeleteAll = async () => {
    setDeletingAll(true)
    try {
      await api.post('/api/leads/delete-all')
      addToast('Todos os leads foram deletados', 'success')
      setShowDeleteAllConfirm(false)
      setDeleteAllConfirmText('')
      fetchLeads()
    } catch {
      addToast('Erro ao deletar todos os leads', 'error')
    } finally {
      setDeletingAll(false)
    }
  }

  const handleSendToCrm = async () => {
    if (!crmApiUrl.trim() || !crmAuthToken.trim()) {
      addToast('URL e token do CRM são obrigatórios', 'error')
      return
    }

    setSendingToCrm(true)
    setCrmSyncResult(null)
    try {
      const payload = {
        lead_ids: selected.size > 0 ? Array.from(selected) : [],
        filters: selected.size === 0 ? {
          status: statusFilter,
          tag: tagFilter,
          city: cityFilter,
          state: stateFilter,
          search: searchDebounced,
        } : {},
        crm_api_url: crmApiUrl.trim(),
        crm_auth_token: crmAuthToken.trim(),
      }

      const res = await api.post('/api/leads/send-to-crm', payload)
      setCrmSyncResult({
        success: true,
        sent_count: res.data.sent_count,
        failed_count: res.data.failed_count,
        message: res.data.message || `${res.data.sent_count} leads enviados para o CRM`,
      })
      addToast(`✅ ${res.data.sent_count} leads enviados com sucesso!`, 'success')
    } catch (err: any) {
      const errorMsg = err.response?.data?.error || 'Erro ao enviar leads para o CRM'
      setCrmSyncResult({
        success: false,
        error: errorMsg,
      })
      addToast(errorMsg, 'error')
    } finally {
      setSendingToCrm(false)
    }
  }

  const totalAll = Object.values(statusCounts).reduce((a, b) => a + b, 0)

  if (loading) return <LoadingSkeleton />

  return (
    <div className="space-y-5 animate-fade-in">
      {/* SaaS Limit Banner */}
      {usage && limits && (
        <>
          {!canViewLeads() && (
            <div className="px-4 py-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300 flex items-center gap-2">
              <Lock className="w-5 h-5 flex-shrink-0" />
              <div>
                <p className="font-semibold">Limite de visualização atingido</p>
                <p className="text-sm">Você visualizou {usage.leads_viewed} de {limits.leads_per_month} leads neste mês. Faça upgrade para continuar.</p>
              </div>
            </div>
          )}
          {!canExport() && (
            <div className="px-4 py-3 bg-orange-50 dark:bg-orange-900/30 border border-orange-200 dark:border-orange-800 rounded-lg text-orange-700 dark:text-orange-300 flex items-center gap-2">
              <AlertCircle className="w-5 h-5 flex-shrink-0" />
              <div>
                <p className="font-semibold">Limite de exportação atingido</p>
                <p className="text-sm">Você exportou {usage.leads_exported} de {limits.exports_per_month} listas neste mês. Faça upgrade para continuar.</p>
              </div>
            </div>
          )}
          {canViewLeads() && canExport() && usage.leads_exported / limits.exports_per_month > 0.8 && (
            <div className="px-4 py-3 bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-800 rounded-lg text-yellow-700 dark:text-yellow-300 flex items-center gap-2">
              <AlertCircle className="w-5 h-5 flex-shrink-0" />
              <div>
                <p className="font-semibold">Próximo do limite de exportação</p>
                <p className="text-sm">Você utilizou {Math.round(usage.leads_exported / limits.exports_per_month * 100)}% do seu limite. Considere fazer upgrade.</p>
              </div>
            </div>
          )}
        </>
      )}

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Base de Leads</h1>
          <p className="text-sm text-gray-500 mt-0.5">{total} leads disponíveis</p>
        </div>
        {total > 0 && (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <button
                onClick={handleSanitize}
                disabled={sanitizing}
                title={selected.size > 0 ? `Sanitizar ${selected.size} leads selecionados` : 'Sanitizar todos os leads'}
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
              >
                <Sparkles className="w-4 h-4" />
                {sanitizing ? 'Sanitizando...' : selected.size > 0 ? `Sanitizar (${selected.size})` : 'Sanitizar Leads'}
              </button>
              <Tooltip
                text="Corrige nomes com caracteres errados (ex: Caf?? → Café), padroniza maiusculas/minusculas e extrai o nome correto do dominio. Seguro de usar a qualquer momento."
                position="bottom"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => {
                  if (!canExport()) {
                    addToast('Você atingiu o limite de exportações para este mês', 'error')
                    return
                  }
                  setShowExport(true)
                }}
                disabled={!canExport()}
                title={!canExport() ? 'Limite de exportação atingido' : 'Exportar leads'}
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary-600 hover:bg-primary-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
              >
                <Download className="w-4 h-4" />
                Exportar {!canExport() && '(Limite)'}
              </button>
              <Tooltip
                text={canExport() ? "Baixe sua lista em CSV, JSON ou formato pronto para WhatsApp, email marketing e telemarketing." : "Você atingiu o limite de exportações. Faça upgrade para continuar."}
                position="bottom"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setShowSendToCrmModal(true)}
                title="Enviar leads selecionados ou filtrados para um CRM"
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
              >
                📤 Enviar para CRM
              </button>
              <Tooltip
                text="Envie seus leads para o DIAX CRM ou qualquer outro sistema com API compatível."
                position="bottom"
              />
            </div>
          </div>
        )}
      </div>

      {/* InfoBox */}
      <InfoBox
        storageKey="leads"
        title="Base de Leads"
        description="Acesse a base central de contatos qualificados. Filtre por status, tag, cidade ou segmento, organize no seu funil de vendas e exporte para sua ferramenta favorita."
        steps={[
          'Use os filtros de status (Novo, Contatado...) para organizar seu funil',
          'Clique em um lead para abrir o painel lateral e adicionar notas e tags',
          'Selecione varios leads e use Acoes em Massa para atualizar status ou deletar',
          'Clique em Exportar para baixar a lista em CSV ou formato de disparo',
        ]}
      />

      {/* Status pills */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        <Tooltip text="Filtre por etapa do funil de vendas. 'Novo' = ainda nao contatado. 'Cliente' = convertido." position="right" />
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

      {/* Search Bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar empresa, email, telefone, CNPJ..."
          className="w-full pl-10 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all"
        />
      </div>

      {/* Location Filters Section */}
      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="w-4 h-4 text-primary-600" />
          <h3 className="text-sm font-semibold text-gray-900">Filtros de Localização</h3>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {/* City Filter */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Cidade</label>
            <select
              value={cityFilter}
              onChange={(e) => { setCityFilter(e.target.value); setPage(1) }}
              disabled={loadingLocations}
              className="w-full px-3 py-2.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500/30 disabled:opacity-50"
            >
              <option value="">Todas as cidades</option>
              {availableCities.map(city => (
                <option key={city} value={city}>{city}</option>
              ))}
            </select>
          </div>

          {/* State Filter */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Estado</label>
            <select
              value={stateFilter}
              onChange={(e) => { setStateFilter(e.target.value); setPage(1) }}
              disabled={loadingLocations}
              className="w-full px-3 py-2.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500/30 disabled:opacity-50"
            >
              <option value="">Todos os estados</option>
              {availableStates.map(state => (
                <option key={state} value={state}>{state}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Other Filters Section */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Tag filter */}
        {allTags.length > 0 && (
          <div className="flex items-center gap-1">
            <select
              value={tagFilter}
              onChange={(e) => { setTagFilter(e.target.value); setPage(1) }}
              className="px-3 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500/30"
            >
              <option value="">Todas as tags</option>
              {allTags.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <Tooltip text="Tags sao etiquetas que voce adiciona manualmente ou o sistema cria automaticamente por segmento (ex: saude, beleza, educacao)." />
          </div>
        )}

        {/* Sort */}
        <div className="flex items-center gap-1">
          <select
            value={sort}
            onChange={(e) => { setSort(e.target.value); setPage(1) }}
            className="px-3 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500/30"
          >
            {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <Tooltip text="Ordene a lista por data de extracao, nome da empresa ou status do funil." />
        </div>
      </div>

      {/* Saved Filters Bar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Active filter indicator */}
        {activeFilterId && (
          <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 border border-blue-200 dark:bg-blue-900/20 dark:border-blue-800 text-blue-700 dark:text-blue-300 text-xs font-medium rounded-full">
            <BookmarkCheck className="w-3.5 h-3.5" />
            {savedFilters.find(f => f.id === activeFilterId)?.name ?? 'Filtro ativo'}
            <button onClick={clearAllFilters} className="ml-0.5 hover:text-blue-900 dark:hover:text-blue-100">
              <XIcon className="w-3 h-3" />
            </button>
          </span>
        )}

        {/* Saved filters dropdown trigger */}
        {savedFilters.length > 0 && (
          <div className="relative">
            <button
              onClick={() => setShowSavedFilters(!showSavedFilters)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-xs font-medium rounded-full hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
              <Bookmark className="w-3.5 h-3.5 text-blue-500" />
              Meus filtros ({savedFilters.length})
              <ChevronDown className={`w-3 h-3 transition-transform ${showSavedFilters ? 'rotate-180' : ''}`} />
            </button>
            {showSavedFilters && (
              <div className="absolute top-full left-0 mt-1.5 z-30 w-64 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-lg py-1">
                {savedFilters.map((sf) => (
                  <div
                    key={sf.id}
                    className={`flex items-center gap-2 px-3 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${activeFilterId === sf.id ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}
                  >
                    <button
                      onClick={() => applyFilter(sf)}
                      className="flex-1 text-left"
                    >
                      <p className={`text-sm font-medium ${activeFilterId === sf.id ? 'text-blue-700 dark:text-blue-300' : 'text-gray-800 dark:text-gray-200'}`}>
                        {sf.name}
                      </p>
                      <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate">
                        {[sf.filters.city, sf.filters.state, sf.filters.status, sf.filters.tag].filter(Boolean).join(' · ') || 'Sem filtros específicos'}
                      </p>
                    </button>
                    {activeFilterId === sf.id && (
                      <CheckCircle2 className="w-4 h-4 text-blue-500 flex-shrink-0" />
                    )}
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDeleteFilter(sf.id) }}
                      className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-gray-400 hover:text-red-500 transition-colors flex-shrink-0"
                      title="Excluir filtro"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Save current filter button */}
        {hasActiveFilters && (
          <button
            onClick={() => { setSaveFilterName(''); setShowSaveModal(true) }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-gray-800 border border-dashed border-blue-300 dark:border-blue-700 text-blue-600 dark:text-blue-400 text-xs font-medium rounded-full hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
          >
            <Bookmark className="w-3.5 h-3.5" />
            Salvar filtro atual
          </button>
        )}

        {/* Clear filters */}
        {hasActiveFilters && (
          <button
            onClick={clearAllFilters}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-gray-500 dark:text-gray-400 text-xs hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
          >
            <XIcon className="w-3.5 h-3.5" />
            Limpar filtros
          </button>
        )}
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
              onClick={handleBulkDelete}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-red-50 border border-red-200 rounded-lg text-xs font-medium text-red-700 hover:bg-red-100"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Deletar
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
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Score</th>
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
                      <ScoreBadge score={lead.lead_score ?? 0} />
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
            : 'A base de leads será exibida aqui assim que disponível'}
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
          onUpgradeRequired={() => triggerUpgrade('export')}
          totalLeads={total}
          filters={{
            search: searchDebounced || undefined,
            status: statusFilter || undefined,
            tag: tagFilter || undefined,
            ids: selected.size > 0 ? Array.from(selected) : undefined,
          }}
        />
      )}

      {/* Send to CRM Modal */}
      {showSendToCrmModal && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={() => { setShowSendToCrmModal(false); setCrmSyncResult(null) }} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-fade-in max-h-96 overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">Enviar para CRM</h3>
                <button
                  onClick={() => { setShowSendToCrmModal(false); setCrmSyncResult(null) }}
                  className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300"
                >
                  <XIcon className="w-5 h-5" />
                </button>
              </div>

              {!crmSyncResult ? (
                <>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                    Envie {selected.size > 0 ? `${selected.size} leads selecionados` : `leads com os filtros atuais`} para seu CRM.
                  </p>

                  <div className="space-y-4 mb-6">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                        URL do CRM *
                      </label>
                      <input
                        type="url"
                        value={crmApiUrl}
                        onChange={(e) => setCrmApiUrl(e.target.value)}
                        placeholder="http://localhost:5062 ou https://api.seucrm.com"
                        className="w-full px-4 py-3 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 transition-all"
                      />
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        (localhost, 127.0.0.1 ou https://)
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                        Token JWT do CRM *
                      </label>
                      <input
                        type="password"
                        value={crmAuthToken}
                        onChange={(e) => setCrmAuthToken(e.target.value)}
                        placeholder="eyJhbGciOiJIUzI1NiIs..."
                        className="w-full px-4 py-3 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 transition-all"
                      />
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        Guardado apenas em sessão (sessionStorage)
                      </p>
                    </div>

                    <div className="p-3 bg-indigo-50 dark:bg-indigo-900/30 rounded-lg border border-indigo-100 dark:border-indigo-800">
                      <p className="text-xs text-indigo-700 dark:text-indigo-300">
                        <strong>Leads a enviar:</strong> {selected.size > 0 ? selected.size : total}
                      </p>
                    </div>
                  </div>

                  <div className="flex gap-3">
                    <button
                      onClick={() => { setShowSendToCrmModal(false); setCrmSyncResult(null) }}
                      className="flex-1 px-4 py-2.5 bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-900 dark:text-gray-100 text-sm font-semibold rounded-xl transition-colors"
                    >
                      Cancelar
                    </button>
                    <button
                      onClick={handleSendToCrm}
                      disabled={sendingToCrm || !crmApiUrl.trim() || !crmAuthToken.trim()}
                      className="flex-1 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-sm font-semibold rounded-xl transition-colors"
                    >
                      {sendingToCrm ? 'Enviando...' : '📤 Enviar'}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  {crmSyncResult.success ? (
                    <>
                      <div className="p-4 bg-emerald-50 dark:bg-emerald-900/30 rounded-lg border border-emerald-100 dark:border-emerald-800 mb-4">
                        <div className="flex items-start gap-3">
                          <CheckCircle2 className="w-6 h-6 text-emerald-600 dark:text-emerald-400 flex-shrink-0 mt-0.5" />
                          <div>
                            <p className="font-semibold text-emerald-700 dark:text-emerald-300 mb-1">
                              Enviado com sucesso!
                            </p>
                            <p className="text-sm text-emerald-600 dark:text-emerald-400 mb-2">
                              {crmSyncResult.message}
                            </p>
                            <div className="text-sm text-emerald-600 dark:text-emerald-400">
                              <p>✅ Enviados: <strong>{crmSyncResult.sent_count}</strong></p>
                              {crmSyncResult.failed_count ? <p>⚠️ Falhados: <strong>{crmSyncResult.failed_count}</strong></p> : null}
                            </div>
                          </div>
                        </div>
                      </div>

                      <button
                        onClick={() => { setShowSendToCrmModal(false); setCrmSyncResult(null) }}
                        className="w-full px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-xl transition-colors"
                      >
                        Fechar
                      </button>
                    </>
                  ) : (
                    <>
                      <div className="p-4 bg-red-50 dark:bg-red-900/30 rounded-lg border border-red-100 dark:border-red-800 mb-4">
                        <div className="flex items-start gap-3">
                          <XCircle className="w-6 h-6 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                          <div>
                            <p className="font-semibold text-red-700 dark:text-red-300 mb-1">
                              Erro ao enviar
                            </p>
                            <p className="text-sm text-red-600 dark:text-red-400">
                              {crmSyncResult.error}
                            </p>
                          </div>
                        </div>
                      </div>

                      <div className="flex gap-3">
                        <button
                          onClick={() => setCrmSyncResult(null)}
                          className="flex-1 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-xl transition-colors"
                        >
                          Tentar Novamente
                        </button>
                        <button
                          onClick={() => { setShowSendToCrmModal(false); setCrmSyncResult(null) }}
                          className="flex-1 px-4 py-2.5 bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-900 dark:text-gray-100 text-sm font-semibold rounded-xl transition-colors"
                        >
                          Fechar
                        </button>
                      </div>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        </>
      )}

      {/* Upgrade Modal */}
      {showUpgrade && (
        <UpgradeModal
          onClose={() => setShowUpgrade(false)}
          reason={upgradeReason}
          currentPlan={plan ?? 'free'}
        />
      )}

      {/* Tag Input Mini-Modal */}
      {/* Save Filter Modal */}
      {showSaveModal && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={() => setShowSaveModal(false)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-sm p-6 animate-fade-in">
              <h3 className="text-base font-bold text-gray-900 dark:text-gray-100 mb-1">Salvar Filtro</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                Nomeie a combinação atual de filtros para reutilizar depois.
              </p>
              <input
                autoFocus
                type="text"
                value={saveFilterName}
                onChange={(e) => setSaveFilterName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSaveFilter() }}
                placeholder="Ex: Clínicas em Vitória, SP premium..."
                maxLength={100}
                className="w-full px-4 py-3 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 transition-all mb-4"
              />
              <div className="flex gap-3">
                <button
                  onClick={() => setShowSaveModal(false)}
                  className="flex-1 px-4 py-2.5 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-xl font-medium text-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  Cancelar
                </button>
                <button
                  onClick={handleSaveFilter}
                  disabled={!saveFilterName.trim() || savingFilter}
                  className="flex-1 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-semibold text-sm transition-colors flex items-center justify-center gap-2"
                >
                  <Bookmark className="w-4 h-4" />
                  {savingFilter ? 'Salvando...' : 'Salvar'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

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

      {/* Sanitize Report Modal */}
      {sanitizeReport && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={() => setSanitizeReport(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-fade-in">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-12 h-12 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                  <BadgeCheck className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">Sanitização Concluída</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">{sanitizeReport.analyzed} leads analisados</p>
                </div>
              </div>

              <div className="space-y-2 mb-5">
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    Encoding / acentuação corrigidos
                  </div>
                  <span className="font-bold text-emerald-600 dark:text-emerald-400">{sanitizeReport.encoding_corrected}</span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <XCircle className="w-4 h-4 text-red-500" />
                    E-mails inválidos detectados
                  </div>
                  <span className="font-bold text-red-600 dark:text-red-400">{sanitizeReport.invalid_emails}</span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <AlertCircle className="w-4 h-4 text-orange-500" />
                    Domínios de spam detectados
                  </div>
                  <span className="font-bold text-orange-600 dark:text-orange-400">{sanitizeReport.spam_detected}</span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <Copy className="w-4 h-4 text-blue-500" />
                    Duplicatas removidas
                  </div>
                  <span className="font-bold text-blue-600 dark:text-blue-400">{sanitizeReport.duplicates_removed}</span>
                </div>
                {(sanitizeReport.no_contact_removed ?? 0) > 0 && (
                  <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                    <div className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                      <XCircle className="w-4 h-4 text-gray-500" />
                      Sem contato válido (removidos)
                    </div>
                    <span className="font-bold text-gray-600 dark:text-gray-400">{sanitizeReport.no_contact_removed}</span>
                  </div>
                )}
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <Sparkles className="w-4 h-4 text-purple-500" />
                    Quality score atualizado
                  </div>
                  <span className="font-bold text-purple-600 dark:text-purple-400">{sanitizeReport.quality_updated}</span>
                </div>
                {sanitizeReport.ids_deleted > 0 && (
                  <div className="flex items-center justify-between p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
                    <div className="flex items-center gap-2 text-sm text-red-700 dark:text-red-300">
                      <Trash2 className="w-4 h-4" />
                      Leads removidos (inválidos/duplicatas)
                    </div>
                    <span className="font-bold text-red-600 dark:text-red-400">{sanitizeReport.ids_deleted}</span>
                  </div>
                )}
              </div>

              <button
                onClick={() => setSanitizeReport(null)}
                className="w-full px-4 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl font-semibold text-sm transition-colors"
              >
                Fechar
              </button>
            </div>
          </div>
        </>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={() => setShowDeleteConfirm(false)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-fade-in">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                  <Trash2 className="w-6 h-6 text-red-600 dark:text-red-400" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">Confirmar Exclusão</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">Esta ação não pode ser desfeita</p>
                </div>
              </div>
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 mb-4">
                <p className="text-sm text-red-800 dark:text-red-300">
                  Você está prestes a deletar <strong>{selected.size} lead{selected.size > 1 ? 's' : ''}</strong>.
                  Os dados serão permanentemente removidos do sistema.
                </p>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  className="flex-1 px-4 py-2.5 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-xl font-medium text-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  Cancelar
                </button>
                <button
                  onClick={confirmBulkDelete}
                  className="flex-1 px-4 py-2.5 bg-red-600 hover:bg-red-700 text-white rounded-xl font-semibold text-sm transition-colors"
                >
                  Deletar {selected.size} Lead{selected.size > 1 ? 's' : ''}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Sync + Delete Modal */}
      {showSyncDeleteConfirm && (
        <>
          <div className="fixed inset-0 bg-black/50 z-40" onClick={() => { if (!syncingAndDeleting) { setShowSyncDeleteConfirm(false); setSyncDeleteConfirmText(''); setSyncDeleteResult(null) } }} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-fade-in">

              {/* Header */}
              <div className="flex items-center gap-3 mb-4">
                <div className="w-12 h-12 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                  <RefreshCw className={`w-6 h-6 text-amber-600 dark:text-amber-400 ${syncingAndDeleting ? 'animate-spin' : ''}`} />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">Sync + Apagar</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {syncingAndDeleting ? 'Sincronizando com CRM...' : syncDeleteResult ? 'Concluído' : 'Sincronizar e limpar base'}
                  </p>
                </div>
              </div>

              {/* Resultado final */}
              {syncDeleteResult ? (
                <>
                  <div className="space-y-2 mb-5">
                    <div className="flex items-center justify-between p-3 bg-green-50 dark:bg-green-900/20 rounded-xl">
                      <div className="flex items-center gap-2 text-sm text-green-800 dark:text-green-300">
                        <CheckCircle2 className="w-4 h-4 text-green-500" />
                        Sincronizados com CRM
                      </div>
                      <span className="font-bold text-green-600 dark:text-green-400">{syncDeleteResult.synced}</span>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                      <div className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                        <Copy className="w-4 h-4 text-gray-400" />
                        Já existiam no CRM
                      </div>
                      <span className="font-bold text-gray-500">{syncDeleteResult.skipped}</span>
                    </div>
                    {syncDeleteResult.errors > 0 && (
                      <div className="flex items-center justify-between p-3 bg-orange-50 dark:bg-orange-900/20 rounded-xl">
                        <div className="flex items-center gap-2 text-sm text-orange-700 dark:text-orange-300">
                          <AlertCircle className="w-4 h-4 text-orange-500" />
                          Erros de sync
                        </div>
                        <span className="font-bold text-orange-600">{syncDeleteResult.errors}</span>
                      </div>
                    )}
                    <div className="flex items-center justify-between p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
                      <div className="flex items-center gap-2 text-sm text-red-700 dark:text-red-300">
                        <Trash2 className="w-4 h-4" />
                        Leads deletados do extrator
                      </div>
                      <span className="font-bold text-red-600 dark:text-red-400">{syncDeleteResult.deleted}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => { setShowSyncDeleteConfirm(false); setSyncDeleteConfirmText(''); setSyncDeleteResult(null) }}
                    className="w-full px-4 py-2.5 bg-amber-500 hover:bg-amber-600 text-white rounded-xl font-semibold text-sm transition-colors"
                  >
                    Fechar
                  </button>
                </>
              ) : syncingAndDeleting ? (
                /* Loading state */
                <div className="py-8 flex flex-col items-center gap-3 text-gray-500 dark:text-gray-400">
                  <RefreshCw className="w-8 h-8 animate-spin text-amber-500" />
                  <p className="text-sm font-medium">Sincronizando {total} leads com o CRM...</p>
                  <p className="text-xs text-gray-400">Aguarde, isso pode levar alguns segundos</p>
                </div>
              ) : (
                /* Confirm state */
                <>
                  <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4 mb-4">
                    <p className="text-sm text-amber-800 dark:text-amber-300">
                      Isso irá <strong>sincronizar todos os {total} leads</strong> para <strong>api.alexandrequeiroz.com.br</strong> e depois <strong>apagar tudo</strong> do extrator. Ação irreversível.
                    </p>
                  </div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                    Digite <strong className="text-amber-600 dark:text-amber-400 font-mono">CONFIRMAR</strong> para continuar:
                  </p>
                  <input
                    type="text"
                    value={syncDeleteConfirmText}
                    onChange={(e) => setSyncDeleteConfirmText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && syncDeleteConfirmText === 'CONFIRMAR') confirmSyncAndDelete() }}
                    placeholder="CONFIRMAR"
                    autoFocus
                    className="w-full px-4 py-3 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl text-sm font-mono text-gray-900 dark:text-gray-100 placeholder-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-all mb-4"
                  />
                  <div className="flex gap-3">
                    <button
                      onClick={() => { setShowSyncDeleteConfirm(false); setSyncDeleteConfirmText('') }}
                      className="flex-1 px-4 py-2.5 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-xl font-medium text-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                    >
                      Cancelar
                    </button>
                    <button
                      onClick={confirmSyncAndDelete}
                      disabled={syncDeleteConfirmText !== 'CONFIRMAR'}
                      className="flex-1 px-4 py-2.5 bg-amber-500 hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl font-semibold text-sm transition-colors"
                    >
                      Sync + Apagar {total} Leads
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}

      {/* Delete ALL Confirmation Modal */}
      {showDeleteAllConfirm && (
        <>
          <div className="fixed inset-0 bg-black/50 z-40" onClick={() => { setShowDeleteAllConfirm(false); setDeleteAllConfirmText('') }} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-fade-in">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                  <Trash2 className="w-7 h-7 text-red-600 dark:text-red-400" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">Apagar TODOS os Leads</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">Ação irreversível</p>
                </div>
              </div>

              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 mb-5">
                <p className="text-sm text-red-800 dark:text-red-300">
                  Isso irá deletar <strong>todos os {total} leads</strong> da sua conta permanentemente.
                  Esta ação <strong>não pode ser desfeita</strong>.
                </p>
              </div>

              <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                Digite <strong className="text-red-600 dark:text-red-400 font-mono">CONFIRMAR</strong> para continuar:
              </p>
              <input
                type="text"
                value={deleteAllConfirmText}
                onChange={(e) => setDeleteAllConfirmText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && deleteAllConfirmText === 'CONFIRMAR') confirmDeleteAll() }}
                placeholder="CONFIRMAR"
                autoFocus
                className="w-full px-4 py-3 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl text-sm font-mono text-gray-900 dark:text-gray-100 placeholder-gray-300 focus:outline-none focus:ring-2 focus:ring-red-500/30 focus:border-red-400 transition-all mb-4"
              />

              <div className="flex gap-3">
                <button
                  onClick={() => { setShowDeleteAllConfirm(false); setDeleteAllConfirmText('') }}
                  className="flex-1 px-4 py-2.5 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-xl font-medium text-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  Cancelar
                </button>
                <button
                  onClick={confirmDeleteAll}
                  disabled={deleteAllConfirmText !== 'CONFIRMAR' || deletingAll}
                  className="flex-1 px-4 py-2.5 bg-red-600 hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl font-semibold text-sm transition-colors"
                >
                  {deletingAll ? 'Deletando...' : `Apagar ${total} Leads`}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
