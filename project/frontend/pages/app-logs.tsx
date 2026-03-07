import { useEffect, useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/router'
import Layout from '../components/Layout'
import api from '../lib/api'
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Info,
  Bug,
  Zap,
  MapPin,
  Instagram,
  Linkedin,
  Building2,
  Search,
  Store,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Filter,
  X,
  Terminal,
  Wifi,
  Circle,
} from 'lucide-react'

// ─── Types ───────────────────────────────────────────────────────────────────

interface LogEntry {
  id: number
  created_at: string
  level: string
  provider: string | null
  query: string | null
  message: string
  exception: string | null
}

interface LogsResponse {
  logs: LogEntry[]
  total: number
  page: number
  per_page: number
  total_pages: number
  level_counts: Record<string, number>
}

// ─── Constants ───────────────────────────────────────────────────────────────

const LEVEL_CONFIG: Record<string, { label: string; color: string; bg: string; border: string; Icon: any; pulse?: boolean }> = {
  DEBUG:    { label: 'DEBUG',    color: 'text-gray-500 dark:text-gray-400',   bg: 'bg-gray-100 dark:bg-gray-800',         border: 'border-gray-200 dark:border-gray-700', Icon: Bug },
  INFO:     { label: 'INFO',     color: 'text-blue-600 dark:text-blue-400',   bg: 'bg-blue-50 dark:bg-blue-950',          border: 'border-blue-200 dark:border-blue-800', Icon: Info },
  WARNING:  { label: 'WARN',     color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-950',        border: 'border-amber-200 dark:border-amber-800', Icon: AlertTriangle },
  ERROR:    { label: 'ERROR',    color: 'text-red-600 dark:text-red-400',     bg: 'bg-red-50 dark:bg-red-950',            border: 'border-red-200 dark:border-red-800',   Icon: AlertCircle },
  CRITICAL: { label: 'CRIT',    color: 'text-rose-700 dark:text-rose-300',   bg: 'bg-rose-100 dark:bg-rose-900/40',      border: 'border-rose-300 dark:border-rose-700', Icon: Zap, pulse: true },
}

const PROVIDER_ICONS: Record<string, any> = {
  google_maps:        MapPin,
  instagram:          Instagram,
  linkedin:           Linkedin,
  directories:        Building2,
  search_engines:     Search,
  api_enrichment:     Activity,
  local_business_data: Store,
  sync:               RefreshCw,
  monitor:            Activity,
}

const LEVEL_ORDER = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']

// ─── Helpers ─────────────────────────────────────────────────────────────────

function ProviderIcon({ provider }: { provider: string | null }) {
  if (!provider) return <Terminal className="w-3.5 h-3.5 text-gray-400" />
  const key = Object.keys(PROVIDER_ICONS).find(k => provider.toLowerCase().includes(k))
  const Icon = key ? PROVIDER_ICONS[key] : Terminal
  return <Icon className="w-3.5 h-3.5" />
}

function formatTime(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'medium' })
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60000) return `${Math.round(diff / 1000)}s atrás`
  if (diff < 3600000) return `${Math.round(diff / 60000)}m atrás`
  if (diff < 86400000) return `${Math.round(diff / 3600000)}h atrás`
  return `${Math.round(diff / 86400000)}d atrás`
}

// ─── Components ──────────────────────────────────────────────────────────────

function LevelBadge({ level }: { level: string }) {
  const cfg = LEVEL_CONFIG[level] ?? LEVEL_CONFIG.INFO
  const Icon = cfg.Icon
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${cfg.bg} ${cfg.color} ${cfg.border}`}>
      {cfg.pulse && <Circle className="w-2 h-2 fill-current animate-ping absolute opacity-75" />}
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  )
}

function StatCard({ level, count, active, onClick }: { level: string; count: number; active: boolean; onClick: () => void }) {
  const cfg = LEVEL_CONFIG[level] ?? LEVEL_CONFIG.INFO
  const Icon = cfg.Icon
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2.5 px-4 py-3 rounded-xl border-2 transition-all duration-200 text-left cursor-pointer
        ${active
          ? `${cfg.bg} ${cfg.border} ring-2 ring-offset-1 ring-offset-white dark:ring-offset-gray-900 ${cfg.border.replace('border-', 'ring-')}`
          : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
        }`}
    >
      <div className={`p-1.5 rounded-lg ${cfg.bg}`}>
        <Icon className={`w-4 h-4 ${cfg.color}`} />
      </div>
      <div>
        <div className={`text-lg font-black leading-none ${cfg.color}`}>{count.toLocaleString()}</div>
        <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mt-0.5">{cfg.label}</div>
      </div>
    </button>
  )
}

function LogRow({ log }: { log: LogEntry }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = LEVEL_CONFIG[log.level] ?? LEVEL_CONFIG.INFO
  const hasException = !!log.exception

  return (
    <div className={`border-l-4 ${cfg.border.replace('border-', 'border-l-')} bg-white dark:bg-gray-900 rounded-r-xl mb-1.5 overflow-hidden transition-all duration-200`}>
      {/* Main row */}
      <div
        className={`flex items-start gap-3 px-4 py-3 ${hasException ? 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50' : ''}`}
        onClick={() => hasException && setExpanded(e => !e)}
      >
        {/* Level badge */}
        <div className="pt-0.5 shrink-0">
          <LevelBadge level={log.level} />
        </div>

        {/* Provider */}
        <div className={`flex items-center gap-1.5 text-xs shrink-0 min-w-[110px] ${cfg.color}`}>
          <ProviderIcon provider={log.provider} />
          <span className="font-mono font-medium truncate max-w-[90px]">{log.provider ?? 'system'}</span>
        </div>

        {/* Message */}
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-800 dark:text-gray-200 font-medium leading-snug break-words">
            {log.message}
          </p>
          {log.query && (
            <p className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-0.5 truncate">
              ↳ {log.query}
            </p>
          )}
        </div>

        {/* Time + expand */}
        <div className="flex items-center gap-2 shrink-0 ml-2">
          <span className="text-[11px] text-gray-400 dark:text-gray-500 tabular-nums" title={formatTime(log.created_at)}>
            {relativeTime(log.created_at)}
          </span>
          {hasException && (
            <span className="text-gray-400">
              {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </span>
          )}
        </div>
      </div>

      {/* Exception panel */}
      {expanded && hasException && (
        <div className="px-4 pb-3 pt-0">
          <pre className={`text-xs font-mono p-3 rounded-lg border ${cfg.bg} ${cfg.color} ${cfg.border} overflow-x-auto whitespace-pre-wrap leading-relaxed`}>
            {log.exception}
          </pre>
        </div>
      )}
    </div>
  )
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function AppLogs() {
  const router = useRouter()
  const [data, setData] = useState<LogsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [levelFilter, setLevelFilter] = useState('')
  const [providerFilter, setProviderFilter] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetchLogs = useCallback(async (silent = false) => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    if (!silent) setLoading(true)
    setError('')

    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }

    try {
      const params = new URLSearchParams({ page: page.toString(), per_page: '50' })
      if (levelFilter) params.append('level', levelFilter)
      if (providerFilter) params.append('provider', providerFilter)
      if (search) params.append('search', search)

      const res = await api.get<LogsResponse>(`/api/admin/logs?${params}`, { signal: ctrl.signal })
      setData(res.data)
    } catch (err: any) {
      if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') return
      if (err.response?.status === 401) { router.push('/login'); return }
      if (err.response?.status === 403) setError('Acesso restrito a administradores.')
      else setError('Erro ao carregar logs.')
    } finally {
      if (!ctrl.signal.aborted) setLoading(false)
    }
  }, [page, levelFilter, providerFilter, search, router])

  // Fetch on filter/page change
  useEffect(() => { fetchLogs() }, [fetchLogs])

  // Auto-refresh
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (autoRefresh) {
      intervalRef.current = setInterval(() => fetchLogs(true), 10000)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [autoRefresh, fetchLogs])

  const resetFilters = () => {
    setLevelFilter('')
    setProviderFilter('')
    setSearch('')
    setPage(1)
  }

  const hasFilters = levelFilter || providerFilter || search

  const totalCounts = data?.level_counts ?? {}
  const grandTotal = Object.values(totalCounts).reduce((a, b) => a + b, 0)

  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">

        {/* ── Header ── */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-black text-gray-900 dark:text-white flex items-center gap-2">
              <Terminal className="w-6 h-6 text-primary-600" />
              Logs do Sistema
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              {grandTotal.toLocaleString()} entradas registradas
            </p>
          </div>

          <div className="flex items-center gap-2">
            {/* Auto-refresh toggle */}
            <button
              onClick={() => setAutoRefresh(v => !v)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border transition-all duration-200
                ${autoRefresh
                  ? 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-700 text-emerald-700 dark:text-emerald-400'
                  : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-300'
                }`}
            >
              <Wifi className={`w-4 h-4 ${autoRefresh ? 'animate-pulse' : ''}`} />
              {autoRefresh ? 'Live (10s)' : 'Auto-refresh'}
            </button>

            {/* Manual refresh */}
            <button
              onClick={() => fetchLogs()}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:border-primary-400 hover:text-primary-600 transition-all duration-200"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Atualizar
            </button>
          </div>
        </div>

        {/* ── Level Stats Bar ── */}
        <div className="flex flex-wrap gap-2">
          {LEVEL_ORDER.map(level => {
            const count = totalCounts[level] ?? 0
            return (
              <StatCard
                key={level}
                level={level}
                count={count}
                active={levelFilter === level}
                onClick={() => { setLevelFilter(v => v === level ? '' : level); setPage(1) }}
              />
            )
          })}
        </div>

        {/* ── Filters ── */}
        <div className="flex flex-wrap items-center gap-2 p-3 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700">
          <Filter className="w-4 h-4 text-gray-400 shrink-0" />

          {/* Level select */}
          <select
            value={levelFilter}
            onChange={e => { setLevelFilter(e.target.value); setPage(1) }}
            className="text-sm border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 focus:outline-none focus:border-primary-400"
          >
            <option value="">Todos os níveis</option>
            {LEVEL_ORDER.map(l => <option key={l} value={l}>{l}</option>)}
          </select>

          {/* Provider input */}
          <input
            type="text"
            placeholder="Provider (ex: google_maps)"
            value={providerFilter}
            onChange={e => { setProviderFilter(e.target.value); setPage(1) }}
            className="text-sm border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:border-primary-400 w-48"
          />

          {/* Search */}
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              type="text"
              placeholder="Buscar na mensagem, query..."
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1) }}
              className="w-full text-sm border border-gray-200 dark:border-gray-700 rounded-lg pl-8 pr-3 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:border-primary-400"
            />
          </div>

          {hasFilters && (
            <button
              onClick={resetFilters}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-red-500 transition-colors"
            >
              <X className="w-3.5 h-3.5" /> Limpar
            </button>
          )}
        </div>

        {/* ── Error ── */}
        {error && (
          <div className="flex items-center gap-2 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-600 dark:text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        {/* ── Log List ── */}
        {loading && !data ? (
          <div className="flex items-center justify-center py-20 text-gray-400 gap-3">
            <RefreshCw className="w-5 h-5 animate-spin" />
            <span className="text-sm">Carregando logs...</span>
          </div>
        ) : data && data.logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400 gap-3">
            <Terminal className="w-10 h-10 opacity-30" />
            <p className="text-sm">Nenhum log encontrado{hasFilters ? ' com os filtros selecionados' : ''}.</p>
            {hasFilters && (
              <button onClick={resetFilters} className="text-xs text-primary-600 hover:underline">Limpar filtros</button>
            )}
          </div>
        ) : (
          <div>
            {/* Header legend */}
            <div className="flex items-center gap-3 px-4 pb-2 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
              <span className="w-[80px]">Nível</span>
              <span className="w-[110px]">Provider</span>
              <span className="flex-1">Mensagem</span>
              <span>Tempo</span>
            </div>

            {/* Rows */}
            <div>
              {data?.logs.map(log => <LogRow key={log.id} log={log} />)}
            </div>

            {/* Pagination */}
            {data && data.total_pages > 1 && (
              <div className="flex items-center justify-between mt-5 pt-4 border-t border-gray-100 dark:border-gray-800">
                <span className="text-xs text-gray-400">
                  {((page - 1) * 50 + 1)}–{Math.min(page * 50, data.total)} de {data.total.toLocaleString()}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-30 hover:border-primary-400 hover:text-primary-600 transition-colors"
                  >
                    ← Anterior
                  </button>
                  <span className="px-3 py-1.5 text-xs text-gray-500">
                    {page} / {data.total_pages}
                  </span>
                  <button
                    onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
                    disabled={page === data.total_pages}
                    className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-30 hover:border-primary-400 hover:text-primary-600 transition-colors"
                  >
                    Próxima →
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Layout>
  )
}
