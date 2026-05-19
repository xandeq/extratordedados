import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/router'
import {
  Mail, Plus, Send, Trash2, BarChart2, ChevronRight, ChevronDown,
  CheckCircle2, Clock, MousePointerClick, Eye, AlertCircle, Zap,
  ArrowLeft, X, Loader2, TrendingUp, Users, RefreshCw, Info,
  PlayCircle, PauseCircle, Settings2, Layers, Activity,
} from 'lucide-react'
import Layout from '../components/Layout'
import api from '../lib/api'
import { useToast } from '../components/Toast'

// ─── Types ─────────────────────────────────────────────────────────────────

interface Campaign {
  id: number
  name: string
  status: 'draft' | 'active' | 'sending' | 'paused'
  created_at: string
  total_sends: number
  open_rate: number
  click_rate: number
  unsubs: number
  steps_count: number
}

interface Step {
  step_num: number
  subject: string
  body_html: string
  delay_days: number
  condition: 'always' | 'if_opened' | 'if_not_opened' | 'if_clicked'
}

interface ProviderStatus {
  provider: string
  used: number
  limit: number
  remaining: number
}

// ─── Condition labels ───────────────────────────────────────────────────────

const CONDITION_LABELS: Record<string, string> = {
  always: 'Sempre (todos)',
  if_opened: 'Se abriu o email anterior',
  if_not_opened: 'Se NÃO abriu (follow-up frio)',
  if_clicked: 'Se clicou em um link',
}

// ─── Step Editor ────────────────────────────────────────────────────────────

function StepEditor({ step, index, onChange, onRemove }: {
  step: Step
  index: number
  onChange: (s: Step) => void
  onRemove: () => void
}) {
  const [open, setOpen] = useState(index === 0)

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-700/40 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 text-xs font-bold flex items-center justify-center">
            {index + 1}
          </span>
          <span className="text-sm font-medium text-gray-800 dark:text-gray-200">
            {step.subject || `Passo ${index + 1}`}
          </span>
          {index > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
              {CONDITION_LABELS[step.condition]}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {index > 0 && (
            <button
              onClick={e => { e.stopPropagation(); onRemove() }}
              className="p-1 hover:bg-red-100 dark:hover:bg-red-900/30 rounded text-red-500 transition-colors"
              title="Remover passo"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          {open ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
        </div>
      </button>

      {open && (
        <div className="p-4 space-y-4 bg-white dark:bg-gray-800">
          {index > 0 && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                  Aguardar (dias após passo anterior)
                </label>
                <input
                  type="number"
                  min={1}
                  value={step.delay_days}
                  onChange={e => onChange({ ...step, delay_days: parseInt(e.target.value) || 1 })}
                  className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                  Condição de envio
                </label>
                <select
                  value={step.condition}
                  onChange={e => onChange({ ...step, condition: e.target.value as Step['condition'] })}
                  className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {Object.entries(CONDITION_LABELS).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Assunto do email
            </label>
            <input
              type="text"
              placeholder="Ex: Você viu nossa oferta especial?"
              value={step.subject}
              onChange={e => onChange({ ...step, subject: e.target.value })}
              className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Corpo do email (HTML)
            </label>
            <textarea
              rows={8}
              placeholder={`<p>Olá {nome},</p>\n<p>Seu conteúdo aqui...</p>\n<p>Atenciosamente,<br/>Sua equipe</p>`}
              value={step.body_html}
              onChange={e => onChange({ ...step, body_html: e.target.value })}
              className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono resize-y"
            />
            <p className="text-[11px] text-gray-400 mt-1">
              Pode usar HTML. Links serão rastreados automaticamente. Pixel de abertura é injetado automaticamente.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Campaign Create Wizard ─────────────────────────────────────────────────

function CreateCampaignModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { addToast: showToast } = useToast()
  const [name, setName] = useState('')
  const [fromName, setFromName] = useState('')
  const [steps, setSteps] = useState<Step[]>([{
    step_num: 1,
    subject: '',
    body_html: '',
    delay_days: 0,
    condition: 'always',
  }])
  const [limit, setLimit] = useState(200)
  const [saving, setSaving] = useState(false)

  const addStep = () => {
    setSteps(prev => [...prev, {
      step_num: prev.length + 1,
      subject: '',
      body_html: '',
      delay_days: 3,
      condition: 'if_not_opened',
    }])
  }

  const updateStep = (i: number, s: Step) => {
    setSteps(prev => prev.map((x, idx) => idx === i ? s : x))
  }

  const removeStep = (i: number) => {
    setSteps(prev => prev.filter((_, idx) => idx !== i))
  }

  const handleSave = async () => {
    if (!name.trim()) { showToast('Nome da campanha é obrigatório', 'error'); return }
    if (!steps[0].subject || !steps[0].body_html) {
      showToast('Passo 1 precisa de assunto e corpo', 'error'); return
    }
    setSaving(true)
    try {
      await api.post('/api/campaigns', {
        name,
        from_name: fromName.trim() || undefined,
        steps: steps.map((s, i) => ({ ...s, step_num: i + 1 })),
        target_filter: { limit },
      })
      showToast('Campanha criada!', 'success')
      onCreated()
      onClose()
    } catch {
      showToast('Erro ao criar campanha', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Mail className="w-5 h-5 text-blue-600" />
            Nova Campanha
          </h2>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors">
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-4 space-y-5">
          {/* Name + Sender */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1.5">
                Nome da campanha
              </label>
              <input
                type="text"
                placeholder="Ex: Follow-up Leads Novos — Abril"
                value={name}
                onChange={e => setName(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1.5">
                Nome do remetente <span className="font-normal text-gray-400">(opcional)</span>
              </label>
              <input
                type="text"
                placeholder="Ex: Alexandre Queiroz"
                value={fromName}
                onChange={e => setFromName(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Audience */}
          <div className="p-4 rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800">
            <h3 className="text-sm font-semibold text-blue-800 dark:text-blue-300 mb-2 flex items-center gap-2">
              <Users className="w-4 h-4" />
              Público-alvo
            </h3>
            <div className="flex items-center gap-3">
              <label className="text-sm text-blue-700 dark:text-blue-400">Máximo de leads:</label>
              <input
                type="number"
                min={10}
                max={2000}
                value={limit}
                onChange={e => setLimit(parseInt(e.target.value) || 200)}
                className="w-24 px-3 py-1.5 text-sm rounded-lg border border-blue-200 dark:border-blue-700 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <span className="text-xs text-blue-600 dark:text-blue-400">leads com email válido</span>
            </div>
          </div>

          {/* Steps */}
          <div>
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
              <Layers className="w-4 h-4 text-purple-600" />
              Passos da sequência ({steps.length})
            </h3>
            <div className="space-y-3">
              {steps.map((s, i) => (
                <StepEditor
                  key={i}
                  step={s}
                  index={i}
                  onChange={s => updateStep(i, s)}
                  onRemove={() => removeStep(i)}
                />
              ))}
            </div>
            <button
              onClick={addStep}
              className="mt-3 flex items-center gap-2 text-sm text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-medium transition-colors"
            >
              <Plus className="w-4 h-4" />
              Adicionar passo de automação
            </button>
          </div>

          {/* Info */}
          <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-100 dark:border-amber-800">
            <Info className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" />
            <p className="text-xs text-amber-700 dark:text-amber-400">
              A sequência é automática: após o envio inicial, os passos seguintes são disparados a cada 2h pelo servidor,
              com base na condição de cada passo (abriu / não abriu / clicou).
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-700">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors">
            Cancelar
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2 text-sm font-semibold bg-blue-600 hover:bg-blue-700 text-white rounded-xl transition-colors disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Criar Campanha
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Campaign Card ──────────────────────────────────────────────────────────

function CampaignCard({ campaign, onSend, onDelete, onViewStats }: {
  campaign: Campaign
  onSend: (id: number) => void
  onDelete: (id: number) => void
  onViewStats: (id: number) => void
}) {
  const statusColors: Record<string, string> = {
    draft: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300',
    active: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
    sending: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
    paused: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400',
  }
  const statusLabel: Record<string, string> = {
    draft: 'Rascunho', active: 'Ativa', sending: 'Enviando...', paused: 'Pausada',
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-white">{campaign.name}</h3>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium flex items-center gap-1 ${statusColors[campaign.status]}`}>
              {campaign.status === 'sending' && (
                <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
              )}
              {statusLabel[campaign.status] || campaign.status}
            </span>
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {campaign.steps_count} passo{campaign.steps_count !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
        <Mail className="w-8 h-8 text-blue-500 opacity-20" />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="text-center p-2 rounded-xl bg-gray-50 dark:bg-gray-700/50">
          <div className="text-lg font-bold text-gray-900 dark:text-white">{campaign.total_sends}</div>
          <div className="text-[11px] text-gray-400">Enviados</div>
        </div>
        <div className="text-center p-2 rounded-xl bg-gray-50 dark:bg-gray-700/50">
          <div className="text-lg font-bold text-blue-600 dark:text-blue-400">{campaign.open_rate}%</div>
          <div className="text-[11px] text-gray-400">Abertura</div>
        </div>
        <div className="text-center p-2 rounded-xl bg-gray-50 dark:bg-gray-700/50">
          <div className="text-lg font-bold text-green-600 dark:text-green-400">{campaign.click_rate}%</div>
          <div className="text-[11px] text-gray-400">Cliques</div>
        </div>
      </div>

      {/* Progress bar */}
      {campaign.total_sends > 0 && (
        <div className="mb-4">
          <div className="flex justify-between text-[11px] text-gray-400 mb-1">
            <span>Taxa de abertura</span>
            <span>{campaign.open_rate}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-gray-100 dark:bg-gray-700">
            <div
              className="h-full rounded-full bg-blue-500 transition-all"
              style={{ width: `${Math.min(100, campaign.open_rate)}%` }}
            />
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2">
        {campaign.status === 'draft' && (
          <button
            onClick={() => onSend(campaign.id)}
            className="flex-1 flex items-center justify-center gap-2 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-xl transition-colors"
          >
            <Send className="w-3.5 h-3.5" />
            Enviar agora
          </button>
        )}
        {campaign.status === 'active' && (
          <button
            onClick={() => onViewStats(campaign.id)}
            className="flex-1 flex items-center justify-center gap-2 py-2 text-sm font-semibold text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-700 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-xl transition-colors"
          >
            <BarChart2 className="w-3.5 h-3.5" />
            Ver stats
          </button>
        )}
        {campaign.status === 'draft' && (
          <button
            onClick={() => onViewStats(campaign.id)}
            className="flex items-center gap-1 px-3 py-2 text-sm text-gray-500 dark:text-gray-400 border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-xl transition-colors"
          >
            <BarChart2 className="w-3.5 h-3.5" />
          </button>
        )}
        <button
          onClick={() => onDelete(campaign.id)}
          className="flex items-center gap-1 px-3 py-2 text-sm text-red-500 border border-red-100 dark:border-red-900/30 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-xl transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}

// ─── Stats Modal ────────────────────────────────────────────────────────────

function StatsModal({ campaignId, onClose }: { campaignId: number; onClose: () => void }) {
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/api/campaigns/${campaignId}/stats`)
      .then(r => setStats(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [campaignId])

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <BarChart2 className="w-5 h-5 text-blue-600" />
            Estatísticas da Campanha
          </h2>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors">
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        <div className="p-6">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
            </div>
          ) : stats ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: 'Total enviados', value: stats.sent, icon: Send, color: 'text-blue-600' },
                  { label: 'Taxa abertura', value: `${stats.open_rate}%`, icon: Eye, color: 'text-green-600' },
                  { label: 'Taxa de cliques', value: `${stats.click_rate}%`, icon: MousePointerClick, color: 'text-purple-600' },
                  { label: 'Descadastros', value: stats.unsubscribed, icon: X, color: 'text-red-500' },
                  { label: 'Falhas', value: stats.failed, icon: AlertCircle, color: 'text-orange-500' },
                  { label: 'Total na lista', value: stats.total, icon: Users, color: 'text-gray-600' },
                ].map(({ label, value, icon: Icon, color }) => (
                  <div key={label} className="p-3 rounded-xl bg-gray-50 dark:bg-gray-700/50">
                    <div className={`flex items-center gap-1.5 text-xs font-medium mb-1 ${color}`}>
                      <Icon className="w-3.5 h-3.5" />
                      {label}
                    </div>
                    <div className="text-2xl font-bold text-gray-900 dark:text-white">{value}</div>
                  </div>
                ))}
              </div>

              {/* Benchmarks */}
              <div className="p-3 rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800">
                <p className="text-xs font-semibold text-blue-800 dark:text-blue-300 mb-2">Benchmarks de mercado (B2B Brasil)</p>
                <div className="space-y-1 text-xs text-blue-700 dark:text-blue-400">
                  <div className="flex justify-between"><span>Abertura média</span><span className="font-medium">20–25%</span></div>
                  <div className="flex justify-between"><span>Cliques médio</span><span className="font-medium">2–5%</span></div>
                  <div className="flex justify-between"><span>Descadastro aceitável</span><span className="font-medium">&lt; 0.5%</span></div>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">Não foi possível carregar as stats.</p>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Provider Health ────────────────────────────────────────────────────────

function ProviderHealth({ providers }: { providers: ProviderStatus[] }) {
  const total = providers.reduce((a, p) => a + p.remaining, 0)
  const providerIcons: Record<string, string> = {
    brevo: '💌',
    mailjet: '✉️',
    resend: '📨',
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-5">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
        <Zap className="w-4 h-4 text-yellow-500" />
        Capacidade de Envio Hoje
      </h3>
      <div className="space-y-3">
        {providers.map(p => {
          const pct = Math.round((p.used / p.limit) * 100)
          const barColor = pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-yellow-500' : 'bg-green-500'
          return (
            <div key={p.provider}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="font-medium text-gray-700 dark:text-gray-300 capitalize">
                  {providerIcons[p.provider] || '📧'} {p.provider}
                </span>
                <span className="text-gray-500 dark:text-gray-400 tabular-nums">
                  {p.used}/{p.limit}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-gray-100 dark:bg-gray-700">
                <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700 flex items-center justify-between">
        <span className="text-xs text-gray-500 dark:text-gray-400">Total disponível hoje</span>
        <span className="text-sm font-bold text-green-600 dark:text-green-400">{total} emails</span>
      </div>
    </div>
  )
}

// ─── Next Action Guide ──────────────────────────────────────────────────────

function NextActionGuide({ campaigns }: { campaigns: Campaign[] }) {
  const hasDraft = campaigns.some(c => c.status === 'draft')
  const hasNoCampaigns = campaigns.length === 0
  const hasActive = campaigns.some(c => c.status === 'active')
  const lowOpenRate = campaigns.filter(c => c.status === 'active' && c.open_rate < 15 && c.total_sends > 0)

  const actions = []

  if (hasNoCampaigns) {
    actions.push({
      icon: Plus,
      color: 'text-blue-600',
      bg: 'bg-blue-50 dark:bg-blue-900/20 border-blue-100 dark:border-blue-800',
      title: 'Crie sua primeira campanha',
      desc: 'Clique em "Nova Campanha" para começar a nutrir seus leads.',
    })
  }

  if (hasDraft) {
    actions.push({
      icon: Send,
      color: 'text-green-600',
      bg: 'bg-green-50 dark:bg-green-900/20 border-green-100 dark:border-green-800',
      title: 'Rascunhos aguardando envio',
      desc: 'Você tem campanhas prontas. Clique em "Enviar agora" para disparar.',
    })
  }

  if (lowOpenRate.length > 0) {
    actions.push({
      icon: TrendingUp,
      color: 'text-orange-600',
      bg: 'bg-orange-50 dark:bg-orange-900/20 border-orange-100 dark:border-orange-800',
      title: 'Taxa de abertura abaixo de 15%',
      desc: `${lowOpenRate.map(c => c.name).join(', ')} — Tente assuntos mais personalizados.`,
    })
  }

  if (hasActive && !hasDraft && lowOpenRate.length === 0) {
    actions.push({
      icon: CheckCircle2,
      color: 'text-green-600',
      bg: 'bg-green-50 dark:bg-green-900/20 border-green-100 dark:border-green-800',
      title: 'Tudo em ordem!',
      desc: 'Suas campanhas estão ativas e saudáveis. A automação roda a cada 2h.',
    })
  }

  if (actions.length === 0) return null

  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-5">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
        <Activity className="w-4 h-4 text-blue-600" />
        Próximas Ações
      </h3>
      <div className="space-y-2">
        {actions.map((a, i) => {
          const Icon = a.icon
          return (
            <div key={i} className={`flex items-start gap-3 p-3 rounded-xl border ${a.bg}`}>
              <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${a.color}`} />
              <div>
                <p className={`text-xs font-semibold ${a.color}`}>{a.title}</p>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">{a.desc}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Main Page ──────────────────────────────────────────────────────────────

export default function Campanhas() {
  const router = useRouter()
  const { addToast: showToast } = useToast()
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [statsId, setStatsId] = useState<number | null>(null)
  const [sendingId, setSendingId] = useState<number | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const [campRes, provRes] = await Promise.all([
        api.get('/api/campaigns'),
        api.get('/api/campaigns/provider-status').catch(() => ({ data: [] })),
      ])
      setCampaigns(campRes.data)
      setProviders(provRes.data)
    } catch {
      showToast('Erro ao carregar campanhas', 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  // Auto-poll every 5s while any campaign is sending
  useEffect(() => {
    const hasSending = campaigns.some(c => c.status === 'sending')
    if (!hasSending) return
    const tid = setInterval(fetchData, 5000)
    return () => clearInterval(tid)
  }, [campaigns, fetchData])

  const handleSend = async (id: number) => {
    if (!confirm('Enviar campanha agora para todos os leads elegíveis?')) return
    setSendingId(id)
    try {
      const res = await api.post(`/api/campaigns/${id}/send`)
      const msg = res.data.message || `Envio iniciado para ${res.data.leads_to_process ?? '?'} leads`
      showToast(msg, 'success')
      setTimeout(fetchData, 2000)
    } catch (err: any) {
      const msg = err?.response?.data?.error || 'Erro ao enviar campanha'
      showToast(msg, 'error')
    } finally {
      setSendingId(null)
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Apagar esta campanha permanentemente?')) return
    try {
      await api.delete(`/api/campaigns/${id}`)
      showToast('Campanha removida', 'success')
      fetchData()
    } catch {
      showToast('Erro ao remover', 'error')
    }
  }

  const totalSent = campaigns.reduce((a, c) => a + c.total_sends, 0)
  const avgOpen = campaigns.filter(c => c.total_sends > 0).reduce((a, c) => a + c.open_rate, 0) /
    (campaigns.filter(c => c.total_sends > 0).length || 1)

  return (
    <Layout>
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-4 md:p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <Mail className="w-6 h-6 text-blue-600" />
              Campanhas de Email
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Automação de email marketing para seus {campaigns.length > 0 ? 'leads' : 'leads extraídos'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchData}
              className="p-2 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-xl transition-colors"
              title="Atualizar"
            >
              <RefreshCw className="w-4 h-4 text-gray-500" />
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-xl transition-colors shadow-sm"
            >
              <Plus className="w-4 h-4" />
              Nova Campanha
            </button>
          </div>
        </div>

        {/* Overview Stats */}
        {campaigns.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            {[
              { label: 'Campanhas', value: campaigns.length, icon: Mail, color: 'text-blue-600' },
              { label: 'Total enviados', value: totalSent, icon: Send, color: 'text-green-600' },
              { label: 'Abertura média', value: `${avgOpen.toFixed(1)}%`, icon: Eye, color: 'text-purple-600' },
              { label: 'Ativas', value: campaigns.filter(c => c.status === 'active').length, icon: Activity, color: 'text-orange-600' },
            ].map(({ label, value, icon: Icon, color }) => (
              <div key={label} className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-4">
                <div className={`flex items-center gap-1.5 text-xs font-medium mb-1 ${color}`}>
                  <Icon className="w-3.5 h-3.5" />
                  {label}
                </div>
                <div className="text-2xl font-bold text-gray-900 dark:text-white">{value}</div>
              </div>
            ))}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          {/* Campaign List */}
          <div className="lg:col-span-2">
            {loading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
              </div>
            ) : campaigns.length === 0 ? (
              <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-12 text-center">
                <Mail className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                  Nenhuma campanha ainda
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
                  Crie sua primeira campanha e comece a nutrir seus leads com email marketing automatizado.
                </p>
                <button
                  onClick={() => setShowCreate(true)}
                  className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-xl transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  Criar primeira campanha
                </button>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                {campaigns.map(c => (
                  <CampaignCard
                    key={c.id}
                    campaign={c}
                    onSend={handleSend}
                    onDelete={handleDelete}
                    onViewStats={setStatsId}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div className="space-y-4">
            <NextActionGuide campaigns={campaigns} />
            {providers.length > 0 && <ProviderHealth providers={providers} />}

            {/* Automation info */}
            <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
                <Clock className="w-4 h-4 text-purple-600" />
                Como funciona a automação
              </h3>
              <div className="space-y-3">
                {[
                  { step: '1', text: 'Você cria campanha e define passos (ex: envio inicial + follow-up)' },
                  { step: '2', text: 'Clica em "Enviar agora" para disparar o Passo 1 para todos os leads' },
                  { step: '3', text: 'A cada 2h o servidor analisa aberturas e cliques' },
                  { step: '4', text: 'Passos seguintes são enviados automaticamente conforme condição' },
                ].map(({ step, text }) => (
                  <div key={step} className="flex items-start gap-3">
                    <span className="w-5 h-5 rounded-full bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                      {step}
                    </span>
                    <p className="text-xs text-gray-600 dark:text-gray-400">{text}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* WhatsApp coming soon */}
            <div className="bg-gradient-to-br from-green-50 to-emerald-50 dark:from-green-900/20 dark:to-emerald-900/20 rounded-2xl border border-green-100 dark:border-green-800 p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xl">💬</span>
                <h3 className="text-sm font-semibold text-green-800 dark:text-green-300">WhatsApp em breve</h3>
                <span className="text-[10px] px-1.5 py-0.5 bg-green-200 dark:bg-green-800 text-green-800 dark:text-green-200 rounded-full font-bold">BETA</span>
              </div>
              <p className="text-xs text-green-700 dark:text-green-400">
                Integração com WhatsApp Business API para enviar mensagens automáticas baseadas no comportamento dos leads.
              </p>
            </div>
          </div>
        </div>
      </div>

      {showCreate && (
        <CreateCampaignModal
          onClose={() => setShowCreate(false)}
          onCreated={fetchData}
        />
      )}

      {statsId !== null && (
        <StatsModal
          campaignId={statsId}
          onClose={() => setStatsId(null)}
        />
      )}
    </Layout>
  )
}
