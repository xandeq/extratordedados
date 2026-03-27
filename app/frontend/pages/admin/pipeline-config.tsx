import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import {
  Settings, Save, RefreshCw, Clock, MapPin, Hash,
  Mail, Link as LinkIcon, CheckSquare, Square, Plus, X, AlertCircle
} from 'lucide-react'
import api from '../../lib/api'
import { useToast } from '../../components/Toast'

// ─── Types ────────────────────────────────────────────────────────────────────

interface PipelineConfig {
  niches: string[]
  region: string
  hour: number
  minute: number
  notify_email: string | null
  healthcheck_url: string | null
}

// ─── Constants ────────────────────────────────────────────────────────────────

const PIPELINE_NICHES = [
  'restaurante', 'academia', 'clinica medica', 'dentista', 'advocacia',
  'contabilidade', 'imobiliaria', 'salao de beleza', 'farmacia', 'supermercado',
  'pizzaria', 'auto pecas', 'mecanica', 'escola', 'hotel', 'pousada',
  'sorveteria', 'padaria', 'pet shop',
]

const REGIONS = [
  { id: 'grande_vitoria_es', label: 'Grande Vitória (ES)' },
  { id: 'grande_sp', label: 'Grande São Paulo (SP)' },
  { id: 'grande_rj', label: 'Grande Rio de Janeiro (RJ)' },
  { id: 'grande_bh', label: 'Grande Belo Horizonte (MG)' },
]

// ─── Component ────────────────────────────────────────────────────────────────

export default function PipelineConfigPage() {
  const router = useRouter()
  const { addToast } = useToast()

  const [config, setConfig] = useState<PipelineConfig>({
    niches: [],
    region: 'grande_vitoria_es',
    hour: 3,
    minute: 0,
    notify_email: '',
    healthcheck_url: '',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [customNiche, setCustomNiche] = useState('')
  const [regions, setRegions] = useState<Array<{
    id: number;
    name: string;
    city: string;
    state: string;
    active: boolean;
    last_used_at: string | null;
    leads_last_30d: number;
  }>>([])
  const [regionsLoading, setRegionsLoading] = useState(false)

  useEffect(() => {
    setRegionsLoading(true)
    api.get('/api/admin/regions')
      .then(res => setRegions(res.data.regions || []))
      .catch(() => setRegions([]))
      .finally(() => setRegionsLoading(false))
  }, [])

  const isRecentlyUsed = (lastUsedAt: string | null): boolean => {
    if (!lastUsedAt) return false
    const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
    return new Date(lastUsedAt) > sevenDaysAgo
  }

  useEffect(() => {
    api.get('/api/admin/pipeline-config')
      .then((res) => {
        const d = res.data
        setConfig({
          niches: d.niches || [],
          region: d.region || 'grande_vitoria_es',
          hour: d.hour ?? 3,
          minute: d.minute ?? 0,
          notify_email: d.notify_email || '',
          healthcheck_url: d.healthcheck_url || '',
        })
      })
      .catch((err) => {
        const status = err?.response?.status
        if (status === 401) router.push('/login')
        else if (status === 403) router.push('/dashboard')
        else addToast('Erro ao carregar configuração', 'error')
      })
      .finally(() => setLoading(false))
  }, [router, addToast])

  function toggleNiche(niche: string) {
    setConfig((prev) => {
      const has = prev.niches.includes(niche)
      return {
        ...prev,
        niches: has ? prev.niches.filter((n) => n !== niche) : [...prev.niches, niche],
      }
    })
  }

  function addCustomNiche() {
    const val = customNiche.trim().toLowerCase()
    if (!val) return
    if (config.niches.includes(val)) {
      addToast('Nicho já selecionado', 'error')
      return
    }
    setConfig((prev) => ({ ...prev, niches: [...prev.niches, val] }))
    setCustomNiche('')
  }

  async function handleSave() {
    setSaving(true)
    try {
      const payload = {
        niches: config.niches,
        region: config.region,
        hour: Number(config.hour),
        minute: Number(config.minute),
        notify_email: config.notify_email?.trim() || null,
        healthcheck_url: config.healthcheck_url?.trim() || null,
      }
      await api.put('/api/admin/pipeline-config', payload)
      addToast('Configuração salva', 'success')
    } catch {
      addToast('Erro ao salvar', 'error')
    } finally {
      setSaving(false)
    }
  }

  // All predefined + any custom niches in current config not in PIPELINE_NICHES
  const extraNiches = config.niches.filter((n) => !PIPELINE_NICHES.includes(n))
  const allDisplayNiches = [...PIPELINE_NICHES, ...extraNiches]

  return (
    <div className="space-y-6 animate-fade-in max-w-4xl">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-1">
            <Link href="/admin" className="hover:text-gray-700 dark:hover:text-gray-200 transition-colors">
              ← Admin
            </Link>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Settings className="w-6 h-6 text-orange-500" />
            Pipeline Automático
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Configure nichos, região, horário e notificações do pipeline diário
          </p>
        </div>
      </div>

      {loading ? (
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 animate-pulse">
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/4 mb-4" />
              <div className="grid grid-cols-4 gap-2">
                {[...Array(8)].map((_, j) => (
                  <div key={j} className="h-8 bg-gray-200 dark:bg-gray-700 rounded" />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-5">

          {/* ── Niches ── */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <div className="flex items-center gap-2 mb-4">
              <Hash className="w-4 h-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Nichos do Pipeline</h3>
              <span className="ml-auto text-xs text-gray-400 dark:text-gray-500">
                {config.niches.length} selecionado{config.niches.length !== 1 ? 's' : ''}
              </span>
            </div>

            <div className="flex flex-wrap gap-2 mb-4">
              {allDisplayNiches.map((niche) => {
                const active = config.niches.includes(niche)
                return (
                  <button
                    key={niche}
                    type="button"
                    onClick={() => toggleNiche(niche)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                      active
                        ? 'bg-blue-600 text-white hover:bg-blue-700'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                    }`}
                  >
                    {active ? (
                      <CheckSquare className="w-3.5 h-3.5" />
                    ) : (
                      <Square className="w-3.5 h-3.5" />
                    )}
                    {niche}
                  </button>
                )
              })}
            </div>

            {/* Custom niche input */}
            <div className="flex gap-2">
              <input
                type="text"
                value={customNiche}
                onChange={(e) => setCustomNiche(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addCustomNiche()}
                placeholder="Adicionar nicho personalizado..."
                className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
              />
              <button
                type="button"
                onClick={addCustomNiche}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Adicionar
              </button>
            </div>

            {config.niches.length === 0 && (
              <div className="mt-3 flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
                <AlertCircle className="w-3.5 h-3.5" />
                Nenhum nicho selecionado — o pipeline usará os padrões do sistema
              </div>
            )}
          </div>

          {/* ── Region ── */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <div className="flex items-center gap-2 mb-4">
              <MapPin className="w-4 h-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Região</h3>
            </div>
            <select
              value={config.region}
              onChange={(e) => setConfig((prev) => ({ ...prev, region: e.target.value }))}
              className="w-full md:w-80 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
            >
              {REGIONS.map((r) => (
                <option key={r.id} value={r.id}>{r.label}</option>
              ))}
            </select>
          </div>

          {/* ── Cobertura de Cidades — ES ── */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <MapPin className="w-4 h-4 text-gray-400" />
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Cobertura de Cidades — ES</h3>
              </div>
              <span className="text-xs text-gray-400 dark:text-gray-500">
                {regions.filter(r => isRecentlyUsed(r.last_used_at)).length}/{regions.length} visitadas (7 dias)
              </span>
            </div>
            {regionsLoading ? (
              <p className="text-sm text-gray-400 dark:text-gray-500">Carregando cidades...</p>
            ) : regions.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-gray-500">Nenhuma cidade cadastrada. Execute populate_es_cities.sql no VPS.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {regions.map(region => (
                  <span
                    key={region.id}
                    title={`${region.name} — ${region.leads_last_30d} leads (30d) | Último uso: ${region.last_used_at ? new Date(region.last_used_at).toLocaleDateString('pt-BR') : 'nunca'}`}
                    className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium ${
                      !region.active
                        ? 'bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500'
                        : isRecentlyUsed(region.last_used_at)
                        ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full mr-1 flex-shrink-0 ${
                        !region.active
                          ? 'bg-gray-400 dark:bg-gray-500'
                          : isRecentlyUsed(region.last_used_at)
                          ? 'bg-green-500 dark:bg-green-400'
                          : 'bg-gray-400 dark:bg-gray-500'
                      }`}
                    />
                    {region.name}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* ── Schedule ── */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <div className="flex items-center gap-2 mb-4">
              <Clock className="w-4 h-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Horário de Execução</h3>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
              Fuso horário: America/Sao_Paulo
            </p>
            <div className="flex items-center gap-3">
              <div>
                <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Hora (0-23)</label>
                <input
                  type="number"
                  min={0}
                  max={23}
                  value={config.hour}
                  onChange={(e) => setConfig((prev) => ({ ...prev, hour: Math.min(23, Math.max(0, Number(e.target.value))) }))}
                  className="w-24 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
                />
              </div>
              <span className="text-lg font-bold text-gray-400 mt-5">:</span>
              <div>
                <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Minuto (0-59)</label>
                <input
                  type="number"
                  min={0}
                  max={59}
                  value={config.minute}
                  onChange={(e) => setConfig((prev) => ({ ...prev, minute: Math.min(59, Math.max(0, Number(e.target.value))) }))}
                  className="w-24 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
                />
              </div>
              <div className="mt-5 text-sm text-gray-500 dark:text-gray-400">
                → Executa diariamente às{' '}
                <span className="font-mono font-semibold text-gray-900 dark:text-white">
                  {String(config.hour).padStart(2, '0')}:{String(config.minute).padStart(2, '0')}
                </span>
              </div>
            </div>
          </div>

          {/* ── Notifications ── */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <div className="flex items-center gap-2 mb-4">
              <Mail className="w-4 h-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Notificações</h3>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Email de notificação (relatório pós-pipeline)
                </label>
                <input
                  type="email"
                  value={config.notify_email || ''}
                  onChange={(e) => setConfig((prev) => ({ ...prev, notify_email: e.target.value }))}
                  placeholder="seu@email.com"
                  className="w-full md:w-96 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
                />
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">Deixe em branco para desativar</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  <span className="flex items-center gap-1.5">
                    <LinkIcon className="w-3.5 h-3.5" />
                    Healthcheck URL (healthchecks.io)
                  </span>
                </label>
                <input
                  type="text"
                  value={config.healthcheck_url || ''}
                  onChange={(e) => setConfig((prev) => ({ ...prev, healthcheck_url: e.target.value }))}
                  placeholder="https://hc-ping.com/uuid"
                  className="w-full md:w-96 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
                />
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">Deixe em branco para desativar</p>
              </div>
            </div>
          </div>

          {/* ── Save button ── */}
          <div className="flex items-center justify-end gap-3">
            <Link
              href="/admin"
              className="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors no-underline"
            >
              Cancelar
            </Link>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-5 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <Save className="w-4 h-4" />
              )}
              {saving ? 'Salvando...' : 'Salvar configuração'}
            </button>
          </div>

        </div>
      )}
    </div>
  )
}
