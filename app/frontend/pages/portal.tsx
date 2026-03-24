import { useState, useCallback } from 'react'
import { ChevronLeft, ChevronRight, Search as SearchIcon, Mail, Phone, Globe, Download, Bookmark } from 'lucide-react'
import api from '../lib/api'
import { useClientCredits } from '../lib/useClientCredits'
import { RevealButton } from '../components/RevealButton'
import ClientExportModal from '../components/ClientExportModal'
import UpgradeModal from '../components/UpgradeModal'

interface PortalLead {
  id: number
  company_name: string
  city: string | null
  state: string | null
  category: string | null
  email: string | null
  phone: string | null
  whatsapp: string | null
  website: string | null
  cnpj: string | null
  lead_score: number | null
  quality_grade: string | null
  source: string | null
  captured_at: string | null
  has_email: boolean
  has_phone: boolean
  has_whatsapp: boolean
  has_website: boolean
  has_cnpj: boolean
  revealed: boolean
}

function GradeBadge({ grade }: { grade: string | null }) {
  const colors: Record<string, string> = {
    A: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    B: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    C: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    D: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
    F: 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
  }
  if (!grade) return null
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${colors[grade] ?? colors.F}`}>
      {grade}
    </span>
  )
}

export default function Portal() {
  const { balance, loading: creditsLoading, refetch: refetchCredits } = useClientCredits()

  // Filter state
  const [category, setCategory] = useState('')
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [qualityGrade, setQualityGrade] = useState('')
  const [hasEmail, setHasEmail] = useState(false)
  const [hasPhone, setHasPhone] = useState(false)
  const [hasWhatsapp, setHasWhatsapp] = useState(false)
  const [hasWebsite, setHasWebsite] = useState(false)
  const [hasCnpj, setHasCnpj] = useState(false)

  // Results state
  const [leads, setLeads] = useState<PortalLead[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)

  // Export/upgrade modal state
  const [showExportModal, setShowExportModal] = useState(false)
  const [showUpgradeModal, setShowUpgradeModal] = useState(false)

  // Per-lead reveal loading state
  const [revealingId, setRevealingId] = useState<number | null>(null)

  // Save search modal state
  const [showSaveModal, setShowSaveModal] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveEmail, setSaveEmail] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState('')
  const [saveError, setSaveError] = useState('')

  const handleSearch = useCallback(async (pageNum = 1) => {
    setSearching(true)
    try {
      const params: Record<string, string | boolean | number> = { page: pageNum, per_page: 20 }
      if (category) params.category = category
      if (city) params.city = city
      if (state) params.state = state
      if (qualityGrade) params.quality_grade = qualityGrade
      if (hasEmail) params.has_email = true
      if (hasPhone) params.has_phone = true
      if (hasWhatsapp) params.has_whatsapp = true
      if (hasWebsite) params.has_website = true
      if (hasCnpj) params.has_cnpj = true

      const res = await api.get('/api/leads/search', { params })
      setLeads(res.data.leads)
      setTotal(res.data.total)
      setPage(res.data.page)
      setPages(res.data.pages)
      setSearched(true)
    } catch (err) {
      console.error('Search error:', err)
    } finally {
      setSearching(false)
    }
  }, [category, city, state, qualityGrade, hasEmail, hasPhone, hasWhatsapp, hasWebsite, hasCnpj])

  const handleReveal = useCallback(async (leadId: number) => {
    setRevealingId(leadId)
    try {
      const res = await api.post(`/api/leads/reveal/${leadId}`)
      const data = res.data
      // Update lead in-place — no page refetch
      setLeads(prev => prev.map(l =>
        l.id === leadId
          ? { ...l, email: data.email, phone: data.phone, whatsapp: data.whatsapp, revealed: true }
          : l
      ))
      // Update sidebar credit balance
      await refetchCredits()
      // Toast success
      const remaining = data.credits_remaining
      alert(`Contato revelado! ${remaining !== null && remaining !== undefined ? remaining + ' créditos restantes.' : ''}`)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 402) {
        alert('Sem créditos disponíveis. Faça upgrade para continuar.')
      } else {
        alert('Erro ao revelar contato. Tente novamente.')
      }
    } finally {
      setRevealingId(null)
    }
  }, [refetchCredits])

  const saveSearch = async () => {
    if (!saveName.trim()) { setSaveError('Informe um nome para esta busca.'); return }
    setSaving(true)
    setSaveError('')
    try {
      await api.post('/api/client/saved-searches', {
        name: saveName.trim(),
        filters: {
          category,
          city,
          state,
          quality_grade: qualityGrade,
          has_email: hasEmail,
          has_phone: hasPhone,
          has_whatsapp: hasWhatsapp,
          has_website: hasWebsite,
          has_cnpj: hasCnpj,
        },
        notify_enabled: true,
        notify_email: saveEmail.trim() || undefined,
      })
      setSaveSuccess('Busca salva! Voce sera notificado por email sobre novos leads.')
      setTimeout(() => {
        setShowSaveModal(false)
        setSaveSuccess('')
        setSaveName('')
        setSaveEmail('')
      }, 2500)
    } catch {
      setSaveError('Erro ao salvar busca.')
    } finally {
      setSaving(false)
    }
  }

  const GRADES = ['A', 'B', 'C', 'D', 'F']

  // Computed filters object — same params as handleSearch uses
  const currentFilters: Record<string, string | boolean | number> = {}
  if (category) currentFilters.category = category
  if (city) currentFilters.city = city
  if (state) currentFilters.state = state
  if (qualityGrade) currentFilters.quality_grade = qualityGrade
  if (hasEmail) currentFilters.has_email = true
  if (hasPhone) currentFilters.has_phone = true
  if (hasWhatsapp) currentFilters.has_whatsapp = true
  if (hasWebsite) currentFilters.has_website = true
  if (hasCnpj) currentFilters.has_cnpj = true

  return (
    <div className="flex gap-6 h-full animate-fade-in">
      {/* Filter Panel */}
      <aside className="w-60 flex-shrink-0">
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-4 bg-white dark:bg-gray-800 sticky top-4">
          <h2 className="text-sm font-bold text-gray-900 dark:text-white">Filtros</h2>

          <div className="space-y-3">
            <div>
              <label htmlFor="portal-category" className="block text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Segmento</label>
              <input
                id="portal-category"
                type="text"
                value={category}
                onChange={e => setCategory(e.target.value)}
                placeholder="ex: clínica médica"
                className="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label htmlFor="portal-city" className="block text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Cidade</label>
              <input
                id="portal-city"
                type="text"
                value={city}
                onChange={e => setCity(e.target.value)}
                placeholder="ex: Vitória"
                className="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label htmlFor="portal-state" className="block text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Estado</label>
              <input
                id="portal-state"
                type="text"
                value={state}
                onChange={e => setState(e.target.value)}
                placeholder="ex: ES"
                className="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {/* Quality grade chips */}
            <div>
              <span className="block text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Qualidade mínima</span>
              <div className="flex gap-1 flex-wrap">
                {GRADES.map(g => (
                  <button
                    key={g}
                    onClick={() => setQualityGrade(qualityGrade === g ? '' : g)}
                    className={`text-xs font-semibold px-2 py-1 rounded-full border transition-colors ${
                      qualityGrade === g
                        ? 'bg-blue-600 border-blue-600 text-white'
                        : 'border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:border-blue-400'
                    }`}
                  >
                    {g}
                  </button>
                ))}
              </div>
            </div>

            {/* Boolean filters */}
            <div className="space-y-2">
              {[
                { label: 'Tem Email', value: hasEmail, setter: setHasEmail, id: 'has-email' },
                { label: 'Tem Telefone', value: hasPhone, setter: setHasPhone, id: 'has-phone' },
                { label: 'Tem WhatsApp', value: hasWhatsapp, setter: setHasWhatsapp, id: 'has-whatsapp' },
                { label: 'Tem Website', value: hasWebsite, setter: setHasWebsite, id: 'has-website' },
                { label: 'Tem CNPJ', value: hasCnpj, setter: setHasCnpj, id: 'has-cnpj' },
              ].map(({ label, value, setter, id }) => (
                <label key={id} htmlFor={id} className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 cursor-pointer">
                  <input
                    id={id}
                    type="checkbox"
                    checked={value}
                    onChange={e => setter(e.target.checked)}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>

          <button
            onClick={() => handleSearch(1)}
            disabled={searching}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold transition-colors disabled:opacity-60"
          >
            <SearchIcon className="w-4 h-4" />
            {searching ? 'Buscando...' : 'Buscar Leads'}
          </button>

          <button
            onClick={() => setShowSaveModal(true)}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-lg border
                       border-blue-300 text-blue-700 dark:border-blue-600 dark:text-blue-400
                       hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
          >
            <Bookmark size={15} />
            Salvar Busca
          </button>
        </div>
      </aside>

      {/* Results */}
      <main className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">Portal de Leads</h1>
          <div className="flex items-center gap-3">
            {!creditsLoading && balance !== null && (
              <span className="text-sm text-gray-500 dark:text-gray-400">
                <span className="font-bold text-blue-600 dark:text-blue-400 tabular-nums">{balance}</span> créditos disponíveis
              </span>
            )}
            {leads.length > 0 && (
              <button
                onClick={() => setShowExportModal(true)}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-bold rounded-lg transition-colors"
              >
                <Download className="w-4 h-4" />
                Exportar
              </button>
            )}
          </div>
        </div>

        {!searched && !searching && (
          <div className="text-center py-16 text-gray-400 dark:text-gray-500">
            <SearchIcon className="w-10 h-10 mx-auto mb-3 opacity-40" />
            <p className="text-sm">Use os filtros para buscar leads na base.</p>
          </div>
        )}

        {searching && (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 animate-pulse bg-white dark:bg-gray-800">
                <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-2" />
                <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-1/2" />
              </div>
            ))}
          </div>
        )}

        {searched && !searching && leads.length === 0 && (
          <div className="text-center py-16 text-gray-400 dark:text-gray-500">
            <p className="text-base font-semibold text-gray-700 dark:text-gray-300 mb-2">Nenhum lead encontrado</p>
            <p className="text-sm">Tente outros filtros ou amplie a busca por cidade e segmento.</p>
          </div>
        )}

        {leads.length > 0 && (
          <>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
              {total.toLocaleString('pt-BR')} leads encontrados · Página {page} de {pages}
            </p>

            <div role="list" className="space-y-3">
              {leads.map(lead => (
                <div
                  key={lead.id}
                  role="listitem"
                  className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-800 hover:border-blue-400 dark:hover:border-blue-500 transition-colors cursor-default"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <GradeBadge grade={lead.quality_grade} />
                      </div>
                      <p className="font-semibold text-gray-900 dark:text-white text-sm truncate">{lead.company_name}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                        {[lead.city, lead.state].filter(Boolean).join(', ')}
                        {lead.category && ` · ${lead.category}`}
                      </p>
                      <div className="mt-2 space-y-1">
                        {lead.has_email && (
                          <p
                            className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1"
                            aria-label={lead.revealed ? undefined : 'Email mascarado — clique em Revelar para ver'}
                          >
                            <Mail className="w-3 h-3 flex-shrink-0" />
                            <span className={lead.revealed ? 'text-gray-900 dark:text-white' : 'text-gray-400 dark:text-gray-500 font-mono'}>
                              {lead.email}
                            </span>
                          </p>
                        )}
                        {lead.has_phone && (
                          <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1">
                            <Phone className="w-3 h-3 flex-shrink-0" />
                            <span className={lead.revealed ? 'text-gray-900 dark:text-white' : 'text-gray-400 dark:text-gray-500 font-mono'}>
                              {lead.phone}
                            </span>
                          </p>
                        )}
                        {lead.website && (
                          <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1">
                            <Globe className="w-3 h-3 flex-shrink-0" />
                            <a
                              href={lead.website.startsWith('http') ? lead.website : `https://${lead.website}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-blue-600 dark:text-blue-400 hover:underline truncate max-w-[200px]"
                            >
                              {lead.website}
                            </a>
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex-shrink-0">
                      <RevealButton
                        leadId={lead.id}
                        revealed={lead.revealed}
                        balance={balance}
                        onReveal={handleReveal}
                        loading={revealingId === lead.id}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between mt-6">
              <button
                onClick={() => { const p = page - 1; setPage(p); handleSearch(p) }}
                disabled={page <= 1}
                className="flex items-center gap-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft className="w-4 h-4" /> Anterior
              </button>
              <span className="text-sm text-gray-500 dark:text-gray-400">Página {page} de {pages}</span>
              <button
                onClick={() => { const p = page + 1; setPage(p); handleSearch(p) }}
                disabled={page >= pages}
                className="flex items-center gap-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Próxima <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </>
        )}
      </main>

      {showExportModal && (
        <ClientExportModal
          filters={currentFilters}
          leadsCount={total}
          creditBalance={balance}
          onClose={() => setShowExportModal(false)}
          onInsufficientCredits={() => {
            setShowExportModal(false)
            setShowUpgradeModal(true)
          }}
          onExportSuccess={(_count, _remaining) => {
            refetchCredits()
          }}
        />
      )}
      {showUpgradeModal && (
        <UpgradeModal onClose={() => setShowUpgradeModal(false)} reason="export" />
      )}

      {showSaveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl p-6 w-full max-w-sm mx-4">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Salvar Busca
            </h2>

            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
              Nome da busca *
            </label>
            <input
              type="text"
              value={saveName}
              onChange={e => setSaveName(e.target.value)}
              placeholder="Ex: Clinicas em Vitoria/ES"
              className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2
                         text-sm dark:bg-gray-700 dark:text-white mb-3"
            />

            <label className="block text-sm text-gray-700 dark:text-gray-300 mb-1">
              Email para notificacoes (opcional)
            </label>
            <input
              type="email"
              value={saveEmail}
              onChange={e => setSaveEmail(e.target.value)}
              placeholder="seu@email.com"
              className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2
                         text-sm dark:bg-gray-700 dark:text-white mb-4"
            />

            {saveError   && <p className="text-sm text-red-500 mb-2">{saveError}</p>}
            {saveSuccess && <p className="text-sm text-green-600 mb-2">{saveSuccess}</p>}

            <div className="flex gap-2 justify-end">
              <button
                onClick={() => { setShowSaveModal(false); setSaveError(''); setSaveName(''); setSaveEmail('') }}
                className="px-4 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600
                           text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                Cancelar
              </button>
              <button
                onClick={saveSearch}
                disabled={saving}
                className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700
                           disabled:opacity-50 transition-colors"
              >
                {saving ? 'Salvando...' : 'Salvar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
