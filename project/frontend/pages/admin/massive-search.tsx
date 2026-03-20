import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import {
  Zap, Shield, CheckCircle2, XCircle, Loader2, RefreshCw,
  MapPin, Search, Database, Building2, Globe, Mail, Hash,
  Play, Share2, EyeOff, Sparkles, GitMerge, ArrowRight,
  Clock, CheckSquare, AlertTriangle
} from 'lucide-react'
import api from '../../lib/api'
import { useToast } from '../../components/Toast'
import { formatDate, formatNumber } from '../../lib/formatters'

// ─── Types ──────────────────────────────────────────────────────────────────

interface Niche {
  id: string
  name: string
  selected: boolean
}

interface Method {
  id: string
  name: string
  icon: React.ElementType
  rateLimit: string
  enabled: boolean
}

interface AdminBatch {
  id: number
  name: string
  status: string
  total_urls: number
  processed_urls: number
  total_leads: number
  lead_count: number
  created_at: string
  finished_at: string | null
  is_shared: boolean
}

// ─── Constants ───────────────────────────────────────────────────────────────

const PREDEFINED_NICHES: Niche[] = [
  { id: 'clinica_medica', name: 'Clínica Médica', selected: false },
  { id: 'clinica_odontologica', name: 'Clínica Odontológica', selected: false },
  { id: 'clinica_veterinaria', name: 'Clínica Veterinária', selected: false },
  { id: 'escritorio_advocacia', name: 'Escritório de Advocacia', selected: false },
  { id: 'escritorio_contabilidade', name: 'Escritório de Contabilidade', selected: false },
  { id: 'consultoria_empresarial', name: 'Consultoria Empresarial', selected: false },
  { id: 'escola_particular', name: 'Escola Particular', selected: false },
  { id: 'imobiliaria', name: 'Imobiliária', selected: false },
  { id: 'academia', name: 'Academia/Fitness', selected: false },
  { id: 'restaurante', name: 'Restaurante', selected: false },
]

const REGIONS = [
  { id: 'grande_vitoria_es', name: 'Grande Vitória-ES', cities: ['Vitória', 'Vila Velha', 'Serra', 'Cariacica', 'Viana', 'Guarapari'] },
  { id: 'grande_sp', name: 'Grande São Paulo-SP', cities: ['São Paulo', 'Guarulhos', 'Osasco', 'Santo André'] },
  { id: 'grande_rj', name: 'Grande Rio de Janeiro-RJ', cities: ['Rio de Janeiro', 'Niterói', 'Duque de Caxias'] },
  { id: 'grande_bh', name: 'Grande Belo Horizonte-MG', cities: ['Belo Horizonte', 'Contagem', 'Betim'] },
]

const INITIAL_METHODS: Method[] = [
  { id: 'search_engines', name: 'Motores de Busca', icon: Search, rateLimit: '3/h', enabled: true },
  { id: 'google_maps', name: 'Google Maps', icon: MapPin, rateLimit: '5/h', enabled: true },
  { id: 'local_business_data', name: 'Local Business Data', icon: Building2, rateLimit: '500/mês', enabled: true },
  { id: 'website_email_crawler', name: 'Website Crawler', icon: Globe, rateLimit: '5×5', enabled: true },
  { id: 'google_email_harvest', name: 'Email Harvest', icon: Mail, rateLimit: '3×3', enabled: true },
  { id: 'cnpj_open', name: 'CNPJ Open', icon: Hash, rateLimit: 'grátis', enabled: true },
  { id: 'api_enrichment', name: 'API Enrichment', icon: Database, rateLimit: '3/h', enabled: false },
  { id: 'directories', name: 'Diretórios BR', icon: Globe, rateLimit: '5×5', enabled: true },
]

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  running: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  completed: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
}

const LS_KEY = 'admin_massive_custom_niches'
function loadLocal(): string[] {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]') } catch { return [] }
}
function saveLocal(names: string[]) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(names)) } catch {}
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function AdminMassiveSearch() {
  const router = useRouter()
  const { addToast } = useToast()

  // Search config state
  const [niches, setNiches] = useState<Niche[]>(() => {
    const custom = loadLocal()
    if (custom.length === 0) return PREDEFINED_NICHES
    const existing = new Set(PREDEFINED_NICHES.map(n => n.name.toLowerCase()))
    const extras = custom
      .filter(name => !existing.has(name.toLowerCase()))
      .map((name, i) => ({ id: `custom_${i}_${name}`, name, selected: false }))
    return [...PREDEFINED_NICHES, ...extras]
  })
  const [customNiche, setCustomNiche] = useState('')
  const [selectedRegion, setSelectedRegion] = useState('grande_vitoria_es')
  const [maxPages, setMaxPages] = useState(2)
  const [methods, setMethods] = useState<Method[]>(INITIAL_METHODS)
  const [isDraft, setIsDraft] = useState(true)  // start as draft by default

  // Execution state
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Operations state
  const [sanitizing, setSanitizing] = useState(false)
  const [deduping, setDeduping] = useState(false)

  // Batches list
  const [batches, setBatches] = useState<AdminBatch[]>([])
  const [loadingBatches, setLoadingBatches] = useState(true)
  const [publishingId, setPublishingId] = useState<number | null>(null)

  // ─── Auth guard ────────────────────────────────────────────────────────────

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }
    fetchBatches()

    // Load custom niches from DB
    api.get('/api/niches/custom').then(res => {
      const dbNames = (res.data?.niches || []).map((n: any) => n.name)
      if (dbNames.length === 0) return
      saveLocal(dbNames)
      setNiches(prev => {
        const existing = new Set(prev.map(n => n.name.toLowerCase()))
        const extras = dbNames
          .filter((name: string) => !existing.has(name.toLowerCase()))
          .map((name: string, i: number) => ({ id: `db_${i}_${name}`, name, selected: false }))
        return extras.length > 0 ? [...prev, ...extras] : prev
      })
    }).catch(() => {})
  }, [])

  const fetchBatches = useCallback(async () => {
    try {
      setLoadingBatches(true)
      const res = await api.get('/api/admin/batches')
      setBatches(res.data.batches || [])
    } catch (err: any) {
      const status = err?.response?.status
      if (status === 401) router.push('/login')
      else if (status === 403) router.push('/dashboard')
    } finally {
      setLoadingBatches(false)
    }
  }, [router])

  // ─── Niche helpers ────────────────────────────────────────────────────────

  const toggleNiche = (id: string) => setNiches(prev => prev.map(n => n.id === id ? { ...n, selected: !n.selected } : n))

  const addCustomNiche = async () => {
    const name = customNiche.trim()
    if (!name) return
    if (niches.some(n => n.name.toLowerCase() === name.toLowerCase())) {
      setNiches(prev => prev.map(n => n.name.toLowerCase() === name.toLowerCase() ? { ...n, selected: true } : n))
      setCustomNiche('')
      return
    }
    const newNiche: Niche = { id: `custom_${Date.now()}`, name, selected: true }
    setNiches(prev => [...prev, newNiche])
    setCustomNiche('')
    saveLocal([...loadLocal(), name])
    try { await api.post('/api/niches/custom', { name }) } catch {}
  }

  const removeCustomNiche = (id: string, name: string) => {
    if (PREDEFINED_NICHES.some(n => n.id === id)) return
    setNiches(prev => prev.filter(n => n.id !== id))
    saveLocal(loadLocal().filter(n => n.toLowerCase() !== name.toLowerCase()))
    api.delete(`/api/niches/custom/${encodeURIComponent(name)}`).catch(() => {})
  }

  const toggleMethod = (id: string) => setMethods(prev => prev.map(m => m.id === id ? { ...m, enabled: !m.enabled } : m))

  // ─── Search launch ────────────────────────────────────────────────────────

  const handleLaunch = async () => {
    const selectedNiches = niches.filter(n => n.selected).map(n => n.name)
    const enabledMethods = methods.filter(m => m.enabled).map(m => m.id)
    if (selectedNiches.length === 0) { setError('Selecione pelo menos um nicho'); return }
    if (enabledMethods.length === 0) { setError('Selecione pelo menos um método'); return }

    setLaunching(true)
    setError('')
    setSuccess('')

    try {
      const res = await api.post('/api/search/massive', {
        niches: selectedNiches,
        region: selectedRegion,
        methods: enabledMethods,
        max_pages: maxPages,
        is_draft: isDraft,
      })
      const { batch_id, total_jobs } = res.data
      setSuccess(
        `Busca iniciada — ${total_jobs} jobs em execução.` +
        (isDraft ? ' Batch criado como Rascunho (não publicado).' : ' Batch criado como Publicado.')
      )
      fetchBatches()
      setTimeout(() => router.push(`/batch/${batch_id}`), 2500)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao iniciar busca')
    } finally {
      setLaunching(false)
    }
  }

  // ─── Operations ───────────────────────────────────────────────────────────

  const handleSanitize = async () => {
    setSanitizing(true)
    try {
      const res = await api.post('/api/leads/sanitize', {})
      const d = res.data
      addToast(`Sanitização concluída: ${d.fixed ?? 0} corrigidos, ${d.removed ?? 0} removidos`, 'success')
    } catch (err: any) {
      addToast(err.response?.data?.error || 'Erro na sanitização', 'error')
    } finally {
      setSanitizing(false)
    }
  }

  const handleDedup = async () => {
    setDeduping(true)
    try {
      const res = await api.post('/api/leads/fuzzy-dedup', {})
      const d = res.data
      addToast(`Deduplicação concluída: ${d.removed ?? 0} duplicatas removidas`, 'success')
    } catch (err: any) {
      addToast(err.response?.data?.error || 'Erro na deduplicação', 'error')
    } finally {
      setDeduping(false)
    }
  }

  // ─── Publish / Unpublish ──────────────────────────────────────────────────

  const handlePublish = async (batchId: number, publish: boolean) => {
    setPublishingId(batchId)
    try {
      const action = publish ? 'publish' : 'unpublish'
      await api.put(`/api/admin/batches/${batchId}/${action}`)
      addToast(publish ? 'Batch publicado na base compartilhada' : 'Batch removido da base', 'success')
      setBatches(prev => prev.map(b => b.id === batchId ? { ...b, is_shared: publish } : b))
    } catch (err: any) {
      addToast(err.response?.data?.error || 'Erro ao alterar publicação', 'error')
    } finally {
      setPublishingId(null)
    }
  }

  // ─── Derived values ───────────────────────────────────────────────────────

  const selectedNichesCount = niches.filter(n => n.selected).length
  const enabledMethodsCount = methods.filter(m => m.enabled).length
  const regionCities = REGIONS.find(r => r.id === selectedRegion)?.cities.length ?? 0

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 animate-fade-in">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Shield className="w-5 h-5 text-orange-500" />
            <span className="text-xs font-semibold text-orange-600 dark:text-orange-400 uppercase tracking-wide">
              Operação Admin
            </span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Zap className="w-6 h-6 text-indigo-600" />
            Alimentar Base de Leads
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Busca massiva → revisar → sanitizar → publicar para clientes
          </p>
        </div>
        <button
          onClick={fetchBatches}
          className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loadingBatches ? 'animate-spin' : ''}`} />
          Atualizar
        </button>
      </div>

      {/* Alert Messages */}
      {error && (
        <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-start gap-2.5 text-sm text-red-700 dark:text-red-400">
          <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}
      {success && (
        <div className="p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl flex items-start gap-2.5 text-sm text-green-700 dark:text-green-400">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
          {success}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* ── Left: Config ─────────────────────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-5">

          {/* Nichos */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">
              1 — Nichos <span className="text-gray-400 font-normal">({selectedNichesCount} selecionados)</span>
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-3">
              {niches.map(niche => {
                const isCustom = !PREDEFINED_NICHES.some(p => p.id === niche.id)
                return (
                  <div key={niche.id} className="relative group">
                    <button
                      onClick={() => toggleNiche(niche.id)}
                      className={`w-full px-3 py-2 rounded-lg border-2 text-left text-sm transition-all ${
                        niche.selected
                          ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-300'
                          : 'border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                      }`}
                    >
                      <div className="flex items-center gap-1.5">
                        {niche.selected && <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />}
                        <span className="font-medium truncate">{niche.name}</span>
                        {isCustom && (
                          <span className="ml-auto text-[10px] px-1 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 rounded flex-shrink-0">custom</span>
                        )}
                      </div>
                    </button>
                    {isCustom && (
                      <button
                        onClick={(e) => { e.stopPropagation(); removeCustomNiche(niche.id, niche.name) }}
                        className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-red-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                      >×</button>
                    )}
                  </div>
                )
              })}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={customNiche}
                onChange={e => setCustomNiche(e.target.value)}
                onKeyPress={e => e.key === 'Enter' && addCustomNiche()}
                placeholder="Adicionar nicho personalizado..."
                className="flex-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <button onClick={addCustomNiche} className="px-3 py-2 text-sm font-medium bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors">
                + Adicionar
              </button>
            </div>
          </div>

          {/* Região */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">2 — Região</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {REGIONS.map(region => (
                <button
                  key={region.id}
                  onClick={() => setSelectedRegion(region.id)}
                  className={`p-3 rounded-lg border-2 text-left transition-all ${
                    selectedRegion === region.id
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <MapPin className={`w-3.5 h-3.5 ${selectedRegion === region.id ? 'text-indigo-600' : 'text-gray-400'}`} />
                    <span className={`text-sm font-semibold ${selectedRegion === region.id ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'}`}>
                      {region.name}
                    </span>
                    {selectedRegion === region.id && <CheckCircle2 className="w-3.5 h-3.5 text-indigo-600 ml-auto" />}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 pl-5">{region.cities.slice(0, 4).join(', ')}{region.cities.length > 4 ? '...' : ''}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Métodos */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">
              3 — Métodos <span className="text-gray-400 font-normal">({enabledMethodsCount} ativos)</span>
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {methods.map(method => {
                const Icon = method.icon
                return (
                  <button
                    key={method.id}
                    onClick={() => toggleMethod(method.id)}
                    className={`p-3 rounded-lg border-2 text-left transition-all ${
                      method.enabled
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                        : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-0.5">
                      <Icon className={`w-3.5 h-3.5 ${method.enabled ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400'}`} />
                      <span className={`text-xs font-semibold ${method.enabled ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-700 dark:text-gray-300'}`}>
                        {method.name}
                      </span>
                    </div>
                    <span className="text-[10px] text-gray-400 dark:text-gray-500 pl-5">{method.rateLimit}</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {/* ── Right: Controls ───────────────────────────────────────────────── */}
        <div className="space-y-4">

          {/* Launch card */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 space-y-4">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Iniciar Busca</h3>

            {/* Summary */}
            <div className="space-y-1.5 text-xs text-gray-600 dark:text-gray-400">
              <div className="flex justify-between">
                <span>Nichos</span>
                <span className="font-semibold text-gray-900 dark:text-white">{selectedNichesCount}</span>
              </div>
              <div className="flex justify-between">
                <span>Métodos</span>
                <span className="font-semibold text-gray-900 dark:text-white">{enabledMethodsCount}</span>
              </div>
              <div className="flex justify-between">
                <span>Cidades</span>
                <span className="font-semibold text-gray-900 dark:text-white">{regionCities}</span>
              </div>
            </div>

            {/* Max pages */}
            <div>
              <label className="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1">
                Páginas por busca: {maxPages}
              </label>
              <input
                type="range" min="1" max="3" value={maxPages}
                onChange={e => setMaxPages(parseInt(e.target.value))}
                className="w-full h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full appearance-none cursor-pointer accent-indigo-600"
              />
              <div className="flex justify-between text-[10px] text-gray-400 mt-0.5">
                <span>Rápido</span><span>Médio</span><span>Completo</span>
              </div>
            </div>

            {/* Draft toggle */}
            <label className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
              <input
                type="checkbox"
                checked={isDraft}
                onChange={e => setIsDraft(e.target.checked)}
                className="w-4 h-4 accent-orange-500 rounded"
              />
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-900 dark:text-white">Iniciar como Rascunho</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {isDraft
                    ? 'Batch não aparece para clientes até publicar'
                    : 'Batch vai direto para a base compartilhada'}
                </p>
              </div>
              {isDraft
                ? <EyeOff className="w-4 h-4 text-orange-500 flex-shrink-0" />
                : <Share2 className="w-4 h-4 text-green-500 flex-shrink-0" />
              }
            </label>

            <button
              onClick={handleLaunch}
              disabled={launching || selectedNichesCount === 0 || enabledMethodsCount === 0}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-bold rounded-xl transition-colors"
            >
              {launching
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Iniciando...</>
                : <><Play className="w-4 h-4" /> Iniciar Busca Massiva</>
              }
            </button>
          </div>

          {/* Operations card */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 space-y-3">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Ações da Base</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Opera sobre todos os leads do admin na base compartilhada.
            </p>

            <button
              onClick={handleSanitize}
              disabled={sanitizing}
              className="w-full flex items-center gap-2 px-4 py-2.5 border border-gray-200 dark:border-gray-700 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
            >
              {sanitizing
                ? <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                : <Sparkles className="w-4 h-4 text-blue-500" />
              }
              {sanitizing ? 'Sanitizando...' : 'Sanitizar / Refinar'}
            </button>

            <button
              onClick={handleDedup}
              disabled={deduping}
              className="w-full flex items-center gap-2 px-4 py-2.5 border border-gray-200 dark:border-gray-700 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
            >
              {deduping
                ? <Loader2 className="w-4 h-4 animate-spin text-purple-500" />
                : <GitMerge className="w-4 h-4 text-purple-500" />
              }
              {deduping ? 'Deduplicando...' : 'Deduplicar Leads'}
            </button>

            <Link
              href="/leads"
              className="w-full flex items-center gap-2 px-4 py-2.5 border border-gray-200 dark:border-gray-700 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors no-underline"
            >
              <ArrowRight className="w-4 h-4 text-green-500" />
              Ver Base de Leads
            </Link>
          </div>

          {/* Info card */}
          <div className="bg-amber-50 dark:bg-amber-900/20 rounded-xl border border-amber-200 dark:border-amber-800 p-4">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-semibold text-amber-700 dark:text-amber-300 mb-1">Fluxo recomendado</p>
                <ol className="text-xs text-amber-700 dark:text-amber-400 space-y-0.5 list-decimal list-inside">
                  <li>Iniciar como Rascunho</li>
                  <li>Aguardar conclusão</li>
                  <li>Sanitizar + Deduplicar</li>
                  <li>Publicar na base</li>
                </ol>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Execuções Recentes ──────────────────────────────────────────────── */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-gray-400" />
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Execuções Recentes</h3>
          </div>
          <span className="text-xs text-gray-400 dark:text-gray-500">{batches.length} batches</span>
        </div>

        {loadingBatches ? (
          <div className="p-8 text-center text-sm text-gray-400 dark:text-gray-500">
            <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
            Carregando execuções...
          </div>
        ) : batches.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-400 dark:text-gray-500">
            Nenhum batch encontrado. Inicie uma busca acima.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50/60 dark:bg-gray-700/40">
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Nome</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Leads</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Base</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden md:table-cell">Data</th>
                  <th className="px-5 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {batches.slice(0, 15).map(batch => (
                  <tr key={batch.id} className="hover:bg-gray-50/50 dark:hover:bg-gray-700/30 transition-colors">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-gray-900 dark:text-white max-w-[200px] truncate" title={batch.name}>
                          {batch.name}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${STATUS_BADGE[batch.status] ?? STATUS_BADGE.pending}`}>
                        {batch.status}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-sm font-semibold text-gray-900 dark:text-white">
                      {formatNumber(batch.lead_count ?? batch.total_leads ?? 0)}
                    </td>
                    <td className="px-5 py-3.5">
                      {batch.is_shared ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 text-xs font-semibold">
                          <CheckSquare className="w-3 h-3" /> Publicado
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400 text-xs font-semibold">
                          <EyeOff className="w-3 h-3" /> Rascunho
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3.5 text-sm text-gray-400 dark:text-gray-500 hidden md:table-cell whitespace-nowrap">
                      {batch.created_at ? formatDate(batch.created_at) : '—'}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Link
                          href={`/batch/${batch.id}`}
                          className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
                        >
                          Ver
                        </Link>
                        {batch.is_shared ? (
                          <button
                            onClick={() => handlePublish(batch.id, false)}
                            disabled={publishingId === batch.id}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-orange-600 dark:text-orange-400 border border-orange-200 dark:border-orange-800 rounded-lg hover:bg-orange-50 dark:hover:bg-orange-900/20 disabled:opacity-50 transition-colors"
                          >
                            {publishingId === batch.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <EyeOff className="w-3 h-3" />}
                            Despublicar
                          </button>
                        ) : (
                          <button
                            onClick={() => handlePublish(batch.id, true)}
                            disabled={publishingId === batch.id}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-green-600 dark:text-green-400 border border-green-200 dark:border-green-800 rounded-lg hover:bg-green-50 dark:hover:bg-green-900/20 disabled:opacity-50 transition-colors"
                          >
                            {publishingId === batch.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Share2 className="w-3 h-3" />}
                            Publicar
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
