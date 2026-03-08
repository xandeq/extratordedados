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
  Copy,
  CheckCheck,
  Bot,
  Clock,
  Shield,
  Globe,
  Code,
  FileText,
  Layers,
  Hash,
  Calendar,
  BarChart3,
  Wrench,
  Sparkles,
  ChevronRight,
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
  fix_prompt?: string | null
  error_type?: string | null
  extra_data?: Record<string, any> | null
}

interface LogsResponse {
  logs: LogEntry[]
  total: number
  page: number
  per_page: number
  total_pages: number
  level_counts: Record<string, number>
  error_type_counts?: Record<string, number>
  provider_counts?: Record<string, number>
}

// ─── Constants ───────────────────────────────────────────────────────────────

const LEVEL_CONFIG: Record<string, { label: string; color: string; bg: string; border: string; Icon: any; pulse?: boolean }> = {
  DEBUG:    { label: 'DEBUG',    color: 'text-gray-500 dark:text-gray-400',   bg: 'bg-gray-100 dark:bg-gray-800',         border: 'border-gray-200 dark:border-gray-700', Icon: Bug },
  INFO:     { label: 'INFO',     color: 'text-blue-600 dark:text-blue-400',   bg: 'bg-blue-50 dark:bg-blue-950',          border: 'border-blue-200 dark:border-blue-800', Icon: Info },
  WARNING:  { label: 'WARN',     color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-950',        border: 'border-amber-200 dark:border-amber-800', Icon: AlertTriangle },
  ERROR:    { label: 'ERROR',    color: 'text-red-600 dark:text-red-400',     bg: 'bg-red-50 dark:bg-red-950',            border: 'border-red-200 dark:border-red-800',   Icon: AlertCircle },
  CRITICAL: { label: 'CRIT',    color: 'text-rose-700 dark:text-rose-300',   bg: 'bg-rose-100 dark:bg-rose-900/40',      border: 'border-rose-300 dark:border-rose-700', Icon: Zap, pulse: true },
}

const ERROR_TYPE_CONFIG: Record<string, { label: string; color: string; bg: string; icon: any }> = {
  rate_limit:           { label: 'Rate Limit',       color: 'text-orange-600 dark:text-orange-400', bg: 'bg-orange-50 dark:bg-orange-950', icon: Clock },
  quota_exceeded:       { label: 'Quota Exceeded',   color: 'text-red-600 dark:text-red-400',       bg: 'bg-red-50 dark:bg-red-950',       icon: AlertCircle },
  network_timeout:      { label: 'Timeout',          color: 'text-yellow-600 dark:text-yellow-400', bg: 'bg-yellow-50 dark:bg-yellow-950',  icon: Wifi },
  connection_error:     { label: 'Connection Error', color: 'text-rose-600 dark:text-rose-400',     bg: 'bg-rose-50 dark:bg-rose-950',     icon: Globe },
  parsing_error:        { label: 'Parsing Error',    color: 'text-purple-600 dark:text-purple-400', bg: 'bg-purple-50 dark:bg-purple-950',  icon: Code },
  scraping_blocked:     { label: 'Blocked',          color: 'text-red-700 dark:text-red-300',       bg: 'bg-red-100 dark:bg-red-900/40',   icon: Shield },
  html_structure_changed: { label: 'HTML Changed',   color: 'text-indigo-600 dark:text-indigo-400', bg: 'bg-indigo-50 dark:bg-indigo-950',  icon: FileText },
  provider_unavailable: { label: 'Unavailable',      color: 'text-gray-600 dark:text-gray-400',     bg: 'bg-gray-100 dark:bg-gray-800',    icon: AlertTriangle },
  auth_error:           { label: 'Auth Error',       color: 'text-amber-700 dark:text-amber-300',   bg: 'bg-amber-100 dark:bg-amber-900/40', icon: Shield },
  duplicate_error:      { label: 'Duplicate',        color: 'text-cyan-600 dark:text-cyan-400',     bg: 'bg-cyan-50 dark:bg-cyan-950',     icon: Layers },
  unknown:              { label: 'Unknown',          color: 'text-gray-500 dark:text-gray-400',     bg: 'bg-gray-50 dark:bg-gray-900',     icon: Hash },
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

type PromptType = 'fix' | 'analysis' | 'refactor'

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

function formatFullTime(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('pt-BR', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    fractionalSecondDigits: 3,
  } as any)
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60000) return `${Math.round(diff / 1000)}s atras`
  if (diff < 3600000) return `${Math.round(diff / 60000)}m atras`
  if (diff < 86400000) return `${Math.round(diff / 3600000)}h atras`
  return `${Math.round(diff / 86400000)}d atras`
}

function generatePrompt(log: LogEntry, type: PromptType): string {
  const extra = log.extra_data || {}
  const errorType = log.error_type || 'unknown'

  if (type === 'fix') {
    return log.fix_prompt || `Analise o seguinte erro ocorrido no sistema de scraping de leads.

## Informacoes do Erro
- **Nivel**: ${log.level}
- **Tipo de Erro**: ${errorType}
- **Provider/Modulo**: ${log.provider || 'system'}
- **Query/Contexto**: ${log.query || 'N/A'}
- **Mensagem**: ${log.message}
- **Excecao**: ${log.exception || 'N/A'}
${extra.endpoint ? `- **Endpoint**: ${extra.endpoint}` : ''}
${extra.source_url ? `- **URL/Fonte**: ${extra.source_url}` : ''}
${extra.execution_time_ms ? `- **Tempo de execucao**: ${extra.execution_time_ms}ms` : ''}
${extra.retry_count ? `- **Tentativas**: ${extra.retry_count}` : ''}

## Objetivo da analise
1. Identifique a causa raiz do erro
2. Proponha correcao no codigo (mostre o codigo corrigido)
3. Explique o que causou o problema
4. Sugira melhorias para evitar que o erro aconteca novamente
5. Sugira fallback provider caso este falhe`
  }

  if (type === 'analysis') {
    return `Analise detalhadamente o seguinte log do sistema de scraping.

## Log
- **ID**: ${log.id}
- **Timestamp**: ${log.created_at}
- **Nivel**: ${log.level}
- **Tipo de Erro**: ${errorType}
- **Provider**: ${log.provider || 'system'}
- **Query**: ${log.query || 'N/A'}
- **Mensagem**: ${log.message}
${log.exception ? `\n## Stack Trace\n\`\`\`\n${log.exception}\n\`\`\`` : ''}
${extra.endpoint ? `- **Endpoint**: ${extra.endpoint}` : ''}
${extra.source_url ? `- **URL**: ${extra.source_url}` : ''}
${extra.request_params ? `- **Parametros**: ${JSON.stringify(extra.request_params)}` : ''}

## Objetivo
1. Analise o padrao deste erro - e um problema recorrente ou isolado?
2. Qual o impacto deste erro na operacao do sistema?
3. Este erro pode causar efeitos colaterais em outros modulos?
4. Quais metricas devo monitorar para detectar este tipo de problema mais cedo?
5. Sugira alertas automaticos que poderiam ser implementados`
  }

  // refactor
  return `Analise o seguinte erro e sugira refatoracoes no codigo do provider "${log.provider || 'system'}".

## Contexto do Erro
- **Tipo**: ${errorType}
- **Provider**: ${log.provider || 'system'}
- **Mensagem**: ${log.message}
${log.exception ? `\n## Stack Trace\n\`\`\`\n${log.exception}\n\`\`\`` : ''}

## Objetivo da Refatoracao
1. Identifique padroes de codigo que levam a este tipo de erro
2. Sugira refatoracoes para tornar o provider mais resiliente
3. Proponha melhor tratamento de erros e retries
4. Sugira separacao de responsabilidades se necessario
5. Proponha testes unitarios para cobrir este cenario
6. Mostre o codigo refatorado completo`
}

function copyToClipboard(text: string): Promise<void> {
  return navigator.clipboard.writeText(text)
}

// ─── Components ──────────────────────────────────────────────────────────────

function LevelBadge({ level }: { level: string }) {
  const cfg = LEVEL_CONFIG[level] ?? LEVEL_CONFIG.INFO
  const Icon = cfg.Icon
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${cfg.bg} ${cfg.color} ${cfg.border} relative`}>
      {cfg.pulse && <Circle className="w-2 h-2 fill-current animate-ping absolute -left-0.5 opacity-75" />}
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  )
}

function ErrorTypeBadge({ errorType, onClick }: { errorType: string | null | undefined; onClick?: () => void }) {
  if (!errorType) return null
  const cfg = ERROR_TYPE_CONFIG[errorType] ?? ERROR_TYPE_CONFIG.unknown
  const Icon = cfg.icon
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider ${cfg.bg} ${cfg.color} border border-current/10 hover:opacity-80 transition-opacity`}
      title={`Filtrar por: ${cfg.label}`}
    >
      <Icon className="w-2.5 h-2.5" />
      {cfg.label}
    </button>
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

function CopyButton({ text, label, className = '' }: { text: string; label: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    copyToClipboard(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return (
    <button
      onClick={handleCopy}
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium border transition-all duration-200
        ${copied
          ? 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-700 text-emerald-700 dark:text-emerald-400'
          : 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
        } ${className}`}
    >
      {copied ? <><CheckCheck className="w-3 h-3" /> Copiado!</> : <><Copy className="w-3 h-3" /> {label}</>}
    </button>
  )
}

function PromptButton({ log, type, label, icon: Icon, colorClass }: {
  log: LogEntry; type: PromptType; label: string; icon: any; colorClass: string
}) {
  const [copied, setCopied] = useState(false)
  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    const prompt = generatePrompt(log, type)
    copyToClipboard(prompt).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    })
  }
  return (
    <button
      onClick={handleClick}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200
        ${copied
          ? 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-700 text-emerald-700 dark:text-emerald-400'
          : `${colorClass} hover:opacity-80`
        }`}
    >
      {copied ? <><CheckCheck className="w-3.5 h-3.5" /> Copiado!</> : <><Icon className="w-3.5 h-3.5" /> {label}</>}
    </button>
  )
}

function DetailRow({ label, value, mono = false }: { label: string; value: string | number | null | undefined; mono?: boolean }) {
  if (!value) return null
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="font-semibold text-gray-500 dark:text-gray-400 min-w-[120px] shrink-0">{label}:</span>
      <span className={`text-gray-700 dark:text-gray-300 break-all ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  )
}

function LogRow({ log, onFilterProvider, onFilterErrorType }: {
  log: LogEntry
  onFilterProvider: (p: string) => void
  onFilterErrorType: (t: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const cfg = LEVEL_CONFIG[log.level] ?? LEVEL_CONFIG.INFO
  const hasDetails = !!log.exception || !!log.fix_prompt || !!log.error_type || !!log.extra_data

  const extra = log.extra_data || {}

  return (
    <div className={`border-l-4 ${cfg.border.replace('border-', 'border-l-')} bg-white dark:bg-gray-900 rounded-r-xl mb-1.5 overflow-hidden transition-all duration-200`}>
      {/* Main row */}
      <div
        className={`flex items-start gap-3 px-4 py-3 ${hasDetails ? 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50' : ''}`}
        onClick={() => hasDetails && setExpanded(e => !e)}
      >
        {/* Level badge */}
        <div className="pt-0.5 shrink-0">
          <LevelBadge level={log.level} />
        </div>

        {/* Provider */}
        <div className={`flex items-center gap-1.5 text-xs shrink-0 min-w-[110px] ${cfg.color}`}>
          <ProviderIcon provider={log.provider} />
          <button
            onClick={(e) => { e.stopPropagation(); if (log.provider) onFilterProvider(log.provider) }}
            className="font-mono font-medium truncate max-w-[90px] hover:underline"
            title={`Filtrar por ${log.provider}`}
          >
            {log.provider ?? 'system'}
          </button>
        </div>

        {/* Error Type Badge */}
        <div className="shrink-0">
          <ErrorTypeBadge
            errorType={log.error_type}
            onClick={() => log.error_type && onFilterErrorType(log.error_type)}
          />
        </div>

        {/* Message */}
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-800 dark:text-gray-200 font-medium leading-snug break-words">
            {log.message}
          </p>
          {log.query && (
            <p className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-0.5 truncate">
              {log.query}
            </p>
          )}
        </div>

        {/* Time + indicators + expand */}
        <div className="flex items-center gap-2 shrink-0 ml-2">
          {log.fix_prompt && (
            <span title="Prompt de correcao disponivel" className="text-purple-400 dark:text-purple-500">
              <Bot className="w-3.5 h-3.5" />
            </span>
          )}
          <span className="text-[11px] text-gray-400 dark:text-gray-500 tabular-nums" title={formatTime(log.created_at)}>
            {relativeTime(log.created_at)}
          </span>
          {hasDetails && (
            <span className={`text-gray-400 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}>
              <ChevronDown className="w-4 h-4" />
            </span>
          )}
        </div>
      </div>

      {/* Expanded details panel */}
      {expanded && hasDetails && (
        <div className="px-4 pb-4 pt-0 space-y-4 border-t border-gray-100 dark:border-gray-800 mt-0">

          {/* ── Detail Grid ── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1.5 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg mt-3">
            <DetailRow label="ID" value={`#${log.id}`} mono />
            <DetailRow label="Timestamp" value={formatFullTime(log.created_at)} mono />
            <DetailRow label="Nivel" value={log.level} />
            <DetailRow label="Tipo de Erro" value={log.error_type ? (ERROR_TYPE_CONFIG[log.error_type]?.label || log.error_type) : undefined} />
            <DetailRow label="Provider" value={log.provider} mono />
            <DetailRow label="Query" value={log.query} mono />
            <DetailRow label="Endpoint" value={extra.endpoint} mono />
            <DetailRow label="URL/Fonte" value={extra.source_url} mono />
            <DetailRow label="Tempo Execucao" value={extra.execution_time_ms ? `${extra.execution_time_ms}ms` : undefined} />
            <DetailRow label="Retries" value={extra.retry_count} />
            <DetailRow label="Contexto" value={extra.context} />
            <DetailRow label="Parametros" value={extra.request_params ? JSON.stringify(extra.request_params) : undefined} mono />
          </div>

          {/* ── Exception / Stack Trace ── */}
          {log.exception && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" /> Stack Trace / Excecao
                </p>
                <CopyButton text={log.exception} label="Copiar stack trace" />
              </div>
              <pre className={`text-xs font-mono p-3 rounded-lg border ${cfg.bg} ${cfg.color} ${cfg.border} overflow-x-auto whitespace-pre-wrap leading-relaxed max-h-64`}>
                {log.exception}
              </pre>
            </div>
          )}

          {/* ── Action Buttons ── */}
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 mb-2 flex items-center gap-1">
              <Bot className="w-3 h-3" /> Prompts para IA
            </p>
            <div className="flex flex-wrap gap-2">
              <PromptButton
                log={log}
                type="fix"
                label="Gerar Prompt para Correcao"
                icon={Wrench}
                colorClass="bg-purple-50 dark:bg-purple-900/20 border-purple-200 dark:border-purple-800 text-purple-700 dark:text-purple-300"
              />
              <PromptButton
                log={log}
                type="analysis"
                label="Gerar Prompt para Analise"
                icon={BarChart3}
                colorClass="bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300"
              />
              <PromptButton
                log={log}
                type="refactor"
                label="Gerar Prompt para Refatoracao"
                icon={Sparkles}
                colorClass="bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300"
              />
              <CopyButton text={log.message} label="Copiar erro" />
              {log.exception && <CopyButton text={log.exception} label="Copiar stack trace" />}
            </div>
          </div>

          {/* ── Fix Prompt Preview ── */}
          {log.fix_prompt && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-purple-500 dark:text-purple-400 flex items-center gap-1">
                  <Bot className="w-3 h-3" /> Prompt de correcao gerado automaticamente
                </p>
                <CopyButton text={log.fix_prompt} label="Copiar prompt" className="border-purple-200 dark:border-purple-800 text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/20" />
              </div>
              <pre className="text-xs font-mono p-3 rounded-lg border bg-purple-50 dark:bg-purple-950/30 border-purple-200 dark:border-purple-800 text-purple-800 dark:text-purple-300 overflow-auto whitespace-pre-wrap leading-relaxed max-h-56">
                {log.fix_prompt}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Error Type Distribution Mini-Chart ──────────────────────────────────────

function ErrorTypeBar({ counts, activeType, onFilter }: {
  counts: Record<string, number>
  activeType: string
  onFilter: (t: string) => void
}) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1])
  const total = entries.reduce((sum, [, c]) => sum + c, 0)
  if (total === 0) return null

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
      <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
        <BarChart3 className="w-3.5 h-3.5" /> Distribuicao por Tipo de Erro
      </p>
      <div className="flex flex-wrap gap-1.5">
        {entries.map(([type, count]) => {
          const cfg = ERROR_TYPE_CONFIG[type] ?? ERROR_TYPE_CONFIG.unknown
          const pct = Math.round((count / total) * 100)
          const isActive = activeType === type
          return (
            <button
              key={type}
              onClick={() => onFilter(isActive ? '' : type)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200
                ${isActive
                  ? `${cfg.bg} ${cfg.color} border-current/20 ring-2 ring-current/20`
                  : 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-300'
                }`}
            >
              <cfg.icon className="w-3 h-3" />
              {cfg.label}
              <span className="tabular-nums font-bold">{count}</span>
              <span className="text-[9px] opacity-60">({pct}%)</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ─── Provider Distribution ───────────────────────────────────────────────────

function ProviderBar({ counts, activeProvider, onFilter }: {
  counts: Record<string, number>
  activeProvider: string
  onFilter: (p: string) => void
}) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 12)
  if (entries.length === 0) return null

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
      <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
        <Layers className="w-3.5 h-3.5" /> Logs por Provider
      </p>
      <div className="flex flex-wrap gap-1.5">
        {entries.map(([provider, count]) => {
          const isActive = activeProvider.toLowerCase() === provider.toLowerCase()
          return (
            <button
              key={provider}
              onClick={() => onFilter(isActive ? '' : provider)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200
                ${isActive
                  ? 'bg-primary-50 dark:bg-primary-900/20 border-primary-300 dark:border-primary-700 text-primary-700 dark:text-primary-300 ring-2 ring-primary-200 dark:ring-primary-800'
                  : 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-300'
                }`}
            >
              <ProviderIcon provider={provider} />
              <span className="font-mono">{provider}</span>
              <span className="tabular-nums font-bold">{count}</span>
            </button>
          )
        })}
      </div>
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
  const [errorTypeFilter, setErrorTypeFilter] = useState('')
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [showDistribution, setShowDistribution] = useState(true)

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
      if (errorTypeFilter) params.append('error_type', errorTypeFilter)
      if (search) params.append('search', search)
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)

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
  }, [page, levelFilter, providerFilter, errorTypeFilter, search, dateFrom, dateTo, router])

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
    setErrorTypeFilter('')
    setSearch('')
    setDateFrom('')
    setDateTo('')
    setPage(1)
  }

  const hasFilters = levelFilter || providerFilter || errorTypeFilter || search || dateFrom || dateTo

  const totalCounts = data?.level_counts ?? {}
  const grandTotal = Object.values(totalCounts).reduce((a, b) => a + b, 0)
  const activeFilterCount = [levelFilter, providerFilter, errorTypeFilter, search, dateFrom, dateTo].filter(Boolean).length

  return (
    <Layout>
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">

        {/* ── Header ── */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-black text-gray-900 dark:text-white flex items-center gap-2">
              <Terminal className="w-6 h-6 text-primary-600" />
              Central de Diagnostico
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              {grandTotal.toLocaleString()} entradas registradas
              {activeFilterCount > 0 && (
                <span className="ml-2 text-primary-600 dark:text-primary-400 font-medium">
                  ({activeFilterCount} filtro{activeFilterCount > 1 ? 's' : ''} ativo{activeFilterCount > 1 ? 's' : ''})
                </span>
              )}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {/* Toggle distribution charts */}
            <button
              onClick={() => setShowDistribution(v => !v)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border transition-all duration-200
                ${showDistribution
                  ? 'bg-indigo-50 dark:bg-indigo-900/30 border-indigo-300 dark:border-indigo-700 text-indigo-700 dark:text-indigo-400'
                  : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-300'
                }`}
            >
              <BarChart3 className="w-4 h-4" />
              {showDistribution ? 'Ocultar graficos' : 'Graficos'}
            </button>

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

        {/* ── Distribution Charts ── */}
        {showDistribution && data && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ErrorTypeBar
              counts={data.error_type_counts || {}}
              activeType={errorTypeFilter}
              onFilter={(t) => { setErrorTypeFilter(t); setPage(1) }}
            />
            <ProviderBar
              counts={data.provider_counts || {}}
              activeProvider={providerFilter}
              onFilter={(p) => { setProviderFilter(p); setPage(1) }}
            />
          </div>
        )}

        {/* ── Filters ── */}
        <div className="flex flex-wrap items-center gap-2 p-3 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700">
          <Filter className="w-4 h-4 text-gray-400 shrink-0" />

          {/* Level select */}
          <select
            value={levelFilter}
            onChange={e => { setLevelFilter(e.target.value); setPage(1) }}
            className="text-sm border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 focus:outline-none focus:border-primary-400"
          >
            <option value="">Todos os niveis</option>
            {LEVEL_ORDER.map(l => <option key={l} value={l}>{l}</option>)}
          </select>

          {/* Error Type select */}
          <select
            value={errorTypeFilter}
            onChange={e => { setErrorTypeFilter(e.target.value); setPage(1) }}
            className="text-sm border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 focus:outline-none focus:border-primary-400"
          >
            <option value="">Todos os tipos</option>
            {Object.entries(ERROR_TYPE_CONFIG).map(([key, cfg]) => (
              <option key={key} value={key}>{cfg.label}</option>
            ))}
          </select>

          {/* Provider input */}
          <input
            type="text"
            placeholder="Provider (ex: google_maps)"
            value={providerFilter}
            onChange={e => { setProviderFilter(e.target.value); setPage(1) }}
            className="text-sm border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:border-primary-400 w-44"
          />

          {/* Date From */}
          <div className="flex items-center gap-1">
            <Calendar className="w-3.5 h-3.5 text-gray-400" />
            <input
              type="date"
              value={dateFrom}
              onChange={e => { setDateFrom(e.target.value); setPage(1) }}
              className="text-sm border border-gray-200 dark:border-gray-700 rounded-lg px-2 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 focus:outline-none focus:border-primary-400"
              title="Data inicial"
            />
            <span className="text-xs text-gray-400">ate</span>
            <input
              type="date"
              value={dateTo}
              onChange={e => { setDateTo(e.target.value); setPage(1) }}
              className="text-sm border border-gray-200 dark:border-gray-700 rounded-lg px-2 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 focus:outline-none focus:border-primary-400"
              title="Data final"
            />
          </div>

          {/* Search */}
          <div className="relative flex-1 min-w-[180px]">
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
              <X className="w-3.5 h-3.5" /> Limpar ({activeFilterCount})
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
              <span className="w-[80px]">Nivel</span>
              <span className="w-[110px]">Provider</span>
              <span className="w-[100px]">Tipo</span>
              <span className="flex-1">Mensagem</span>
              <span>Tempo</span>
            </div>

            {/* Rows */}
            <div>
              {data?.logs.map(log => (
                <LogRow
                  key={log.id}
                  log={log}
                  onFilterProvider={(p) => { setProviderFilter(p); setPage(1) }}
                  onFilterErrorType={(t) => { setErrorTypeFilter(t); setPage(1) }}
                />
              ))}
            </div>

            {/* Pagination */}
            {data && data.total_pages > 1 && (
              <div className="flex items-center justify-between mt-5 pt-4 border-t border-gray-100 dark:border-gray-800">
                <span className="text-xs text-gray-400">
                  {((page - 1) * 50 + 1)}-{Math.min(page * 50, data.total)} de {data.total.toLocaleString()}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-30 hover:border-primary-400 hover:text-primary-600 transition-colors"
                  >
                    Anterior
                  </button>
                  <span className="px-3 py-1.5 text-xs text-gray-500">
                    {page} / {data.total_pages}
                  </span>
                  <button
                    onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
                    disabled={page === data.total_pages}
                    className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-30 hover:border-primary-400 hover:text-primary-600 transition-colors"
                  >
                    Proxima
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
