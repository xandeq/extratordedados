import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import { Globe, FileJson, FileText, ClipboardList, Zap, Info, Loader2, Search, Save, Trash2, MapPin, Key, ChevronDown, ChevronUp, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react'
import api from '../lib/api'
import { useToast } from '../components/Toast'

interface ExtractedContact {
  id: number
  email: string
  phone: string
  company_name: string
  website: string
  selected: boolean
}

interface Region {
  id: string
  name: string
  state: string
  cities: string[]
}

interface ApiConfig {
  provider: string
  is_active: boolean
  has_key: boolean
  credits_used: number
  credits_limit: number
  credits_remaining: number
}

type Tab = 'search' | 'api-search' | 'url' | 'json' | 'text' | 'paste'

const tabItems: { key: Tab; label: string; icon: any }[] = [
  { key: 'search', label: 'Busca', icon: Search },
  { key: 'api-search', label: 'Busca API', icon: Zap },
  { key: 'url', label: 'URL Unica', icon: Globe },
  { key: 'json', label: 'JSON / Lote', icon: FileJson },
  { key: 'text', label: 'URLs Texto', icon: FileText },
  { key: 'paste', label: 'Extrair de Texto', icon: ClipboardList },
]

const formatPhone = (p: string): string => {
  const d = p.replace(/\D/g, '')
  if (d.length === 13 && d.startsWith('55')) return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 9)}-${d.slice(9)}`
  if (d.length === 12 && d.startsWith('55')) return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 8)}-${d.slice(8)}`
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`
  if (d.length === 9) return `${d.slice(0, 5)}-${d.slice(5)}`
  if (d.length === 8) return `${d.slice(0, 4)}-${d.slice(4)}`
  return p
}

export default function Scrape() {
  const router = useRouter()
  const { addToast } = useToast()
  const [tab, setTab] = useState<Tab>('search')
  const [url, setUrl] = useState('')
  const [jsonInput, setJsonInput] = useState('')
  const [textInput, setTextInput] = useState('')
  const [batchName, setBatchName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [parsedCount, setParsedCount] = useState(0)

  // Search states
  const [searchNiche, setSearchNiche] = useState('')
  const [searchRegion, setSearchRegion] = useState('')
  const [searchCity, setSearchCity] = useState('')
  const [searchState, setSearchState] = useState('')
  const [searchMaxPages, setSearchMaxPages] = useState(2)
  const [regions, setRegions] = useState<Region[]>([])
  const [searchMode, setSearchMode] = useState<'region' | 'manual'>('region')

  // Load regions on mount
  useEffect(() => {
    api.get('/api/regions')
      .then((res) => setRegions(res.data.regions || []))
      .catch(() => {})
  }, [])

  // API Search states
  const [apiConfigs, setApiConfigs] = useState<ApiConfig[]>([])
  const [apiConfigsLoading, setApiConfigsLoading] = useState(false)
  const [showApiSettings, setShowApiSettings] = useState(false)
  const [hunterKey, setHunterKey] = useState('')
  const [snovClientId, setSnovClientId] = useState('')
  const [snovSecret, setSnovSecret] = useState('')
  const [bingApiKey, setBingApiKey] = useState('')
  const [googleCseKey, setGoogleCseKey] = useState('')
  const [googleCseCx, setGoogleCseCx] = useState('')
  const [savingApiConfig, setSavingApiConfig] = useState<string | null>(null)
  const [apiSearchNiche, setApiSearchNiche] = useState('')
  const [apiSearchRegion, setApiSearchRegion] = useState('')
  const [apiSearchCity, setApiSearchCity] = useState('')
  const [apiSearchState, setApiSearchState] = useState('')
  const [apiSearchMaxPages, setApiSearchMaxPages] = useState(2)
  const [apiSearchMode, setApiSearchMode] = useState<'region' | 'manual'>('region')

  // Load API configs when tab switches to api-search
  useEffect(() => {
    if (tab === 'api-search') {
      loadApiConfigs()
    }
  }, [tab])

  const loadApiConfigs = async () => {
    setApiConfigsLoading(true)
    try {
      const res = await api.get('/api/api-config')
      setApiConfigs(res.data.configs || [])
    } catch {
      // silently fail
    } finally {
      setApiConfigsLoading(false)
    }
  }

  const handleSaveApiConfig = async (provider: string) => {
    setSavingApiConfig(provider)
    setError('')
    try {
      const payload: any = { provider }
      if (provider === 'hunter') {
        if (!hunterKey.trim()) { setError('Informe a API key do Hunter.io'); setSavingApiConfig(null); return }
        payload.api_key = hunterKey.trim()
      } else if (provider === 'snov') {
        if (!snovClientId.trim() || !snovSecret.trim()) { setError('Informe o Client ID e Secret do Snov.io'); setSavingApiConfig(null); return }
        payload.api_key = snovClientId.trim()
        payload.api_secret = snovSecret.trim()
      } else if (provider === 'bing_api') {
        if (!bingApiKey.trim()) { setError('Informe a API key do Bing Web Search'); setSavingApiConfig(null); return }
        payload.api_key = bingApiKey.trim()
      } else if (provider === 'google_cse') {
        if (!googleCseKey.trim() || !googleCseCx.trim()) { setError('Informe a API Key e o Search Engine ID do Google CSE'); setSavingApiConfig(null); return }
        payload.api_key = googleCseKey.trim()
        payload.api_secret = googleCseCx.trim()
      }
      await api.post('/api/api-config', payload)
      const providerNames: Record<string, string> = { hunter: 'Hunter.io', snov: 'Snov.io', bing_api: 'Bing Web Search', google_cse: 'Google Custom Search' }
      addToast(`API ${providerNames[provider] || provider} configurada com sucesso!`, 'success')
      setHunterKey('')
      setSnovClientId('')
      setSnovSecret('')
      setBingApiKey('')
      setGoogleCseKey('')
      setGoogleCseCx('')
      await loadApiConfigs()
    } catch (err: any) {
      setError(err.response?.data?.error || `Erro ao salvar config ${provider}`)
    } finally {
      setSavingApiConfig(null)
    }
  }

  const handleDeleteApiConfig = async (provider: string) => {
    try {
      await api.delete(`/api/api-config/${provider}`)
      const providerNames: Record<string, string> = { hunter: 'Hunter.io', snov: 'Snov.io', bing_api: 'Bing Web Search', google_cse: 'Google Custom Search' }
      addToast(`API ${providerNames[provider] || provider} removida`, 'success')
      await loadApiConfigs()
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao remover config')
    }
  }

  const handleApiSearchSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!apiSearchNiche.trim()) { setError('Informe o nicho/segmento'); return }
    if (apiSearchMode === 'region' && !apiSearchRegion) { setError('Selecione uma regiao'); return }
    if (apiSearchMode === 'manual' && (!apiSearchCity.trim() || !apiSearchState.trim())) {
      setError('Informe cidade e estado'); return
    }

    setLoading(true)
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }

    try {
      const payload: any = {
        niche: apiSearchNiche,
        max_pages: apiSearchMaxPages,
      }
      if (apiSearchMode === 'region') {
        payload.region = apiSearchRegion
      } else {
        payload.city = apiSearchCity
        payload.state = apiSearchState
      }

      const response = await api.post('/api/search-api', payload)
      const { batch_id, total_cities } = response.data
      addToast(`Busca API iniciada! ${total_cities} cidade(s) sendo processada(s)`, 'success')
      setTimeout(() => router.push(`/batch/${batch_id}`), 1000)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao iniciar busca API')
      if (err.response?.status === 401) router.push('/login')
    } finally {
      setLoading(false)
    }
  }

  const getApiConfig = (provider: string): ApiConfig | undefined => {
    return apiConfigs.find(c => c.provider === provider)
  }

  // Paste / Extract states
  const [pasteInput, setPasteInput] = useState('')
  const [extractedContacts, setExtractedContacts] = useState<ExtractedContact[]>([])
  const [extracting, setExtracting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [pasteBatchName, setPasteBatchName] = useState('')

  const parseJsonUrls = (input: string): string[] => {
    try {
      const data = JSON.parse(input)
      if (!Array.isArray(data)) return []
      return data
        .map((item: any) => {
          if (typeof item === 'string') return item.trim()
          if (typeof item === 'object' && item !== null) {
            return (item.website || item.url || '').trim()
          }
          return ''
        })
        .filter((u: string) => u.length > 0)
    } catch {
      return []
    }
  }

  const parseTextUrls = (input: string): string[] => {
    return input
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0 && (line.includes('.') || line.startsWith('http')))
  }

  const handleJsonChange = (value: string) => {
    setJsonInput(value)
    setParsedCount(parseJsonUrls(value).length)
  }

  const handleTextChange = (value: string) => {
    setTextInput(value)
    setParsedCount(parseTextUrls(value).length)
  }

  // ===== Text extraction logic =====
  const extractFromText = (text: string): ExtractedContact[] => {
    const lines = text.split('\n')
    const emailRegex = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g
    const phoneRegex = /(?:\+?55\s?)?(?:\(?\d{2}\)?[\s.\-]?)?\d{4,5}[\s.\-]?\d{4}/g
    const urlFullRegex = /https?:\/\/[^\s<>"'{}|\\^`[\]]+/gi
    const domainRegex = /(?:www\.)?[a-zA-Z0-9\-]+\.(?:com\.br|com|net\.br|org\.br|net|org|io|app|dev|br|me|info)\b/gi

    interface Hit { value: string; line: number }
    const emailHits: Hit[] = []
    const phoneHits: Hit[] = []
    const urlHits: Hit[] = []

    lines.forEach((line, idx) => {
      // Emails
      const emails: string[] = line.match(emailRegex) || []
      emails.forEach((e) => {
        const lower = e.toLowerCase()
        if (!emailHits.find((h) => h.value === lower)) {
          emailHits.push({ value: lower, line: idx })
        }
      })

      // Phones - clean and validate
      const phones: string[] = line.match(phoneRegex) || []
      phones.forEach((p) => {
        const digits = p.replace(/\D/g, '')
        // Must be 8-13 digits (local to international)
        if (digits.length >= 8 && digits.length <= 13) {
          if (!phoneHits.find((h) => h.value === digits)) {
            phoneHits.push({ value: digits, line: idx })
          }
        }
      })

      // URLs
      const urls: string[] = line.match(urlFullRegex) || []
      urls.forEach((u) => {
        if (!urlHits.find((h) => h.value === u)) {
          urlHits.push({ value: u, line: idx })
        }
      })

      // Domain-only (no http)
      if (urls.length === 0) {
        const domains: string[] = line.match(domainRegex) || []
        domains.forEach((d) => {
          const clean = d.replace(/^www\./, '')
          if (!urlHits.find((h) => h.value.includes(clean))) {
            urlHits.push({ value: `https://${clean}`, line: idx })
          }
        })
      }
    })

    const contacts: ExtractedContact[] = []
    const usedPhones = new Set<number>()
    const usedUrls = new Set<number>()

    // Helper: find company name from nearby lines
    const findCompanyName = (aroundLine: number): string => {
      for (let i = aroundLine - 1; i >= Math.max(0, aroundLine - 4); i--) {
        const l = lines[i].trim()
        if (
          l &&
          l.length > 2 &&
          l.length < 120 &&
          !emailRegex.test(l) &&
          !urlFullRegex.test(l) &&
          !/^https?:/.test(l) &&
          !/^www\./.test(l) &&
          !/^\(?\d{2}\)?[\s.\-]?\d{4,5}[\s.\-]?\d{4}/.test(l)
        ) {
          // Reset regex lastIndex
          emailRegex.lastIndex = 0
          urlFullRegex.lastIndex = 0
          // Clean up leading bullets, numbers, etc.
          const cleaned = l.replace(/^[\d.)\-·•\s]+/, '').trim()
          if (cleaned.length > 2) return cleaned
        }
      }
      // Reset regex lastIndex
      emailRegex.lastIndex = 0
      urlFullRegex.lastIndex = 0
      return ''
    }

    // Derive company name from email domain when text extraction fails
    const GENERIC_PROVIDERS = new Set([
      'gmail.com', 'googlemail.com', 'outlook.com', 'outlook.com.br',
      'hotmail.com', 'hotmail.com.br', 'yahoo.com', 'yahoo.com.br',
      'live.com', 'msn.com', 'aol.com', 'icloud.com', 'me.com',
      'protonmail.com', 'proton.me', 'zoho.com', 'mail.com', 'gmx.com',
      'uol.com.br', 'bol.com.br', 'terra.com.br', 'ig.com.br',
      'r7.com', 'globo.com', 'globomail.com', 'zipmail.com.br',
      'oi.com.br', 'veloxmail.com.br',
    ])

    const deriveCompanyName = (email: string): string => {
      if (!email || !email.includes('@')) return ''
      const [localPart, domain] = email.toLowerCase().split('@')
      if (!domain) return ''

      const normalize = (raw: string): string => {
        let name = raw
          .replace(/\d+$/g, '')           // remove trailing numbers: "joao123" -> "joao"
          .replace(/[._\-]+/g, ' ')       // dots, underscores, hyphens -> spaces
          .replace(/\s+/g, ' ')           // collapse multiple spaces
          .trim()
        if (!name) return ''
        // Title case
        return name
          .split(' ')
          .filter(w => w.length > 0)
          .map(w => w.charAt(0).toUpperCase() + w.slice(1))
          .join(' ')
      }

      if (GENERIC_PROVIDERS.has(domain)) {
        // Generic provider: use local part as name
        return normalize(localPart)
      } else {
        // Business domain: use first part of domain
        const domainName = domain.split('.')[0]
        return normalize(domainName)
      }
    }

    // Group: for each email, find nearby phone & URL
    emailHits.forEach(({ value: email, line }) => {
      let phone = ''
      let phoneIdx = -1
      phoneHits.forEach((ph, i) => {
        if (!usedPhones.has(i) && Math.abs(ph.line - line) <= 5) {
          if (phoneIdx < 0 || Math.abs(ph.line - line) < Math.abs(phoneHits[phoneIdx].line - line)) {
            phone = ph.value
            phoneIdx = i
          }
        }
      })
      if (phoneIdx >= 0) usedPhones.add(phoneIdx)

      let website = ''
      let urlIdx = -1
      urlHits.forEach((u, i) => {
        if (!usedUrls.has(i) && Math.abs(u.line - line) <= 5) {
          if (urlIdx < 0 || Math.abs(u.line - line) < Math.abs(urlHits[urlIdx].line - line)) {
            website = u.value
            urlIdx = i
          }
        }
      })
      if (urlIdx >= 0) usedUrls.add(urlIdx)

      const textCompany = findCompanyName(line)
      contacts.push({
        id: contacts.length + 1,
        email,
        phone: phone ? formatPhone(phone) : '',
        company_name: textCompany || deriveCompanyName(email),
        website,
        selected: true,
      })
    })

    // Add phones without associated email
    phoneHits.forEach((ph, i) => {
      if (!usedPhones.has(i)) {
        let website = ''
        urlHits.forEach((u, j) => {
          if (!usedUrls.has(j) && Math.abs(u.line - ph.line) <= 5) {
            website = u.value
            usedUrls.add(j)
          }
        })

        contacts.push({
          id: contacts.length + 1,
          email: '',
          phone: formatPhone(ph.value),
          company_name: findCompanyName(ph.line) || '',
          website,
          selected: true,
        })
      }
    })

    return contacts
  }

  const handleExtract = () => {
    if (!pasteInput.trim()) return
    setExtracting(true)
    setError('')

    // Small timeout for UI feedback
    setTimeout(() => {
      try {
        const results = extractFromText(pasteInput)
        setExtractedContacts(results)
        if (results.length === 0) {
          setError('Nenhum email ou telefone encontrado no texto. Verifique o conteudo colado.')
        } else {
          addToast(`${results.length} contato(s) encontrado(s)!`, 'success')
        }
      } catch (err) {
        setError('Erro ao processar o texto. Tente novamente.')
      } finally {
        setExtracting(false)
      }
    }, 300)
  }

  const toggleSelectAll = () => {
    const allSelected = extractedContacts.every((c) => c.selected)
    setExtractedContacts(extractedContacts.map((c) => ({ ...c, selected: !allSelected })))
  }

  const toggleSelect = (idx: number) => {
    setExtractedContacts(
      extractedContacts.map((c, i) => (i === idx ? { ...c, selected: !c.selected } : c))
    )
  }

  const removeContact = (idx: number) => {
    setExtractedContacts(extractedContacts.filter((_, i) => i !== idx))
  }

  const handleSaveLeads = async () => {
    const selected = extractedContacts.filter((c) => c.selected)
    if (selected.length === 0) {
      setError('Selecione ao menos um contato para salvar')
      return
    }

    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }

    setSaving(true)
    setError('')

    try {
      const contacts = selected.map((c) => ({
        email: c.email,
        phone: c.phone.replace(/\D/g, ''),
        company_name: c.company_name,
        website: c.website,
        whatsapp: c.phone.replace(/\D/g, ''),
        contact_name: '',
      }))

      const response = await api.post('/api/leads/import', {
        contacts,
        batch_name: pasteBatchName.trim() || undefined,
      })

      const { batch_id, imported, skipped } = response.data
      addToast(
        `${imported} lead(s) importado(s)${skipped > 0 ? `, ${skipped} duplicado(s) ignorado(s)` : ''}`,
        'success'
      )

      // Reset state
      setPasteInput('')
      setExtractedContacts([])
      setPasteBatchName('')

      // Navigate to batch
      setTimeout(() => router.push(`/batch/${batch_id}`), 1000)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao salvar leads')
      if (err.response?.status === 401) router.push('/login')
    } finally {
      setSaving(false)
    }
  }

  // ===== Search handler =====
  const handleSearchSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!searchNiche.trim()) { setError('Informe o nicho/segmento'); return }
    if (searchMode === 'region' && !searchRegion) { setError('Selecione uma regiao'); return }
    if (searchMode === 'manual' && (!searchCity.trim() || !searchState.trim())) {
      setError('Informe cidade e estado'); return
    }

    setLoading(true)
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }

    try {
      const payload: any = {
        niche: searchNiche,
        max_pages: searchMaxPages,
      }
      if (searchMode === 'region') {
        payload.region = searchRegion
      } else {
        payload.city = searchCity
        payload.state = searchState
      }

      const response = await api.post('/api/search', payload)
      const { batch_id, name, total_cities } = response.data
      addToast(`Busca iniciada! ${total_cities} cidade(s) sendo processada(s)`, 'success')
      setTimeout(() => router.push(`/batch/${batch_id}`), 1000)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao iniciar busca')
      if (err.response?.status === 401) router.push('/login')
    } finally {
      setLoading(false)
    }
  }

  // ===== Existing handlers =====
  const handleSingleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }

    try {
      const response = await api.post('/api/scrape', { url })
      addToast('Scraping concluido!', 'success')
      setUrl('')
      setTimeout(() => router.push(`/results/${response.data.job_id}`), 1000)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao iniciar scraping')
      if (err.response?.status === 401) router.push('/login')
    } finally {
      setLoading(false)
    }
  }

  const handleBatchSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!batchName.trim()) { setError('Nome do lote e obrigatorio'); return }

    let urls: string[] = []
    if (tab === 'json') urls = parseJsonUrls(jsonInput)
    else if (tab === 'text') urls = parseTextUrls(textInput)

    if (urls.length === 0) { setError('Nenhuma URL valida encontrada'); return }
    if (urls.length > 500) { setError('Maximo de 500 URLs por lote'); return }

    setLoading(true)
    const token = localStorage.getItem('token')
    if (!token) { router.push('/login'); return }

    try {
      const response = await api.post('/api/batch', { name: batchName, urls })
      addToast(`Lote criado! ${response.data.total_urls} URLs em processamento`, 'success')
      setTimeout(() => router.push(`/batch/${response.data.batch_id}`), 1000)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao criar lote')
      if (err.response?.status === 401) router.push('/login')
    } finally {
      setLoading(false)
    }
  }

  const selectedCount = extractedContacts.filter((c) => c.selected).length

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Nova Extracao</h1>
        <p className="text-sm text-gray-500 mt-0.5">Escolha o formato e inicie a extracao de leads</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-gray-100 rounded-xl">
        {tabItems.map((t) => {
          const Icon = t.icon
          const active = tab === t.key
          return (
            <button
              key={t.key}
              onClick={() => { setTab(t.key); setParsedCount(0); setError('') }}
              className={`
                flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all
                ${active
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
                }
              `}
            >
              <Icon className="w-4 h-4" />
              <span className="hidden sm:inline">{t.label}</span>
            </button>
          )
        })}
      </div>

      {error && (
        <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Busca por Motor de Busca */}
      {tab === 'search' && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-1">Buscar Leads por Nicho + Cidade</h2>
          <p className="text-sm text-gray-500 mb-5">
            Busca automatica em DuckDuckGo/Bing por empresas do nicho na regiao selecionada.
            Cada resultado e visitado e seus dados extraidos.
          </p>

          <form onSubmit={handleSearchSubmit} className="space-y-4">
            {/* Nicho */}
            <div>
              <label htmlFor="searchNiche" className="block text-sm font-medium text-gray-700 mb-1.5">
                Nicho / Segmento
              </label>
              <input
                id="searchNiche"
                type="text"
                value={searchNiche}
                onChange={(e) => setSearchNiche(e.target.value)}
                placeholder="Ex: dentista, advogado, pet shop, restaurante..."
                required
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
              />
            </div>

            {/* Mode toggle */}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setSearchMode('region')}
                className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-medium transition-all border ${
                  searchMode === 'region'
                    ? 'bg-primary-50 border-primary-200 text-primary-700'
                    : 'bg-gray-50 border-gray-200 text-gray-500 hover:text-gray-700'
                }`}
              >
                <MapPin className="w-3.5 h-3.5 inline mr-1.5" />
                Regiao Pre-definida
              </button>
              <button
                type="button"
                onClick={() => setSearchMode('manual')}
                className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-medium transition-all border ${
                  searchMode === 'manual'
                    ? 'bg-primary-50 border-primary-200 text-primary-700'
                    : 'bg-gray-50 border-gray-200 text-gray-500 hover:text-gray-700'
                }`}
              >
                Cidade/Estado Manual
              </button>
            </div>

            {/* Region select */}
            {searchMode === 'region' && (
              <div>
                <label htmlFor="searchRegion" className="block text-sm font-medium text-gray-700 mb-1.5">
                  Regiao
                </label>
                <select
                  id="searchRegion"
                  value={searchRegion}
                  onChange={(e) => setSearchRegion(e.target.value)}
                  className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                >
                  <option value="">Selecione uma regiao...</option>
                  {regions.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name} ({r.cities.length} cidades)
                    </option>
                  ))}
                </select>
                {searchRegion && regions.find((r) => r.id === searchRegion) && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {regions.find((r) => r.id === searchRegion)?.cities.map((city) => (
                      <span key={city} className="px-2.5 py-1 bg-gray-100 text-gray-600 rounded-lg text-xs font-medium">
                        {city}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Manual city/state */}
            {searchMode === 'manual' && (
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label htmlFor="searchCity" className="block text-sm font-medium text-gray-700 mb-1.5">
                    Cidade
                  </label>
                  <input
                    id="searchCity"
                    type="text"
                    value={searchCity}
                    onChange={(e) => setSearchCity(e.target.value)}
                    placeholder="Ex: Vitoria"
                    className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                  />
                </div>
                <div>
                  <label htmlFor="searchState" className="block text-sm font-medium text-gray-700 mb-1.5">
                    Estado
                  </label>
                  <input
                    id="searchState"
                    type="text"
                    value={searchState}
                    onChange={(e) => setSearchState(e.target.value.toUpperCase().slice(0, 2))}
                    placeholder="ES"
                    maxLength={2}
                    className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                  />
                </div>
              </div>
            )}

            {/* Max pages */}
            <div>
              <label htmlFor="searchMaxPages" className="block text-sm font-medium text-gray-700 mb-1.5">
                Paginas de resultado (1-3)
              </label>
              <select
                id="searchMaxPages"
                value={searchMaxPages}
                onChange={(e) => setSearchMaxPages(Number(e.target.value))}
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
              >
                <option value={1}>1 pagina (~10 resultados por cidade)</option>
                <option value={2}>2 paginas (~20 resultados por cidade)</option>
                <option value={3}>3 paginas (~30 resultados por cidade) - mais lento</option>
              </select>
              <p className="mt-1.5 text-xs text-gray-400">
                Mais paginas = mais resultados, porem mais lento e maior risco de bloqueio
              </p>
            </div>

            {/* Safety info */}
            <div className="px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-amber-700 text-sm">
              <strong>Modo Seguro:</strong> Delays aleatorios entre buscas (5-15s), rotacao de User-Agent,
              deteccao de CAPTCHA. O processo pode levar varios minutos dependendo da regiao.
            </div>

            <button
              type="submit"
              disabled={loading}
              className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed shadow-sm"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              {loading ? 'Iniciando busca...' : 'Iniciar Busca Automatica'}
            </button>
          </form>
        </div>
      )}

      {/* Busca API (Hunter.io / Snov.io) */}
      {tab === 'api-search' && (
        <div className="space-y-4">
          {/* Credit Status */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-semibold text-gray-900">Busca via API</h2>
              <div className="flex gap-1.5 flex-wrap">
                {apiConfigsLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
                ) : (
                  <>
                    {[
                      { key: 'bing_api', label: 'Bing', threshold: 100 },
                      { key: 'google_cse', label: 'Google', threshold: 20 },
                      { key: 'hunter', label: 'Hunter', threshold: 5 },
                      { key: 'snov', label: 'Snov', threshold: 10 },
                    ].map(({ key, label, threshold }) => {
                      const cfg = getApiConfig(key)
                      return cfg && cfg.is_active ? (
                        <span key={key} className={`px-2 py-0.5 rounded-lg text-[11px] font-semibold border ${
                          cfg.credits_remaining > threshold
                            ? 'bg-green-50 text-green-700 border-green-200'
                            : cfg.credits_remaining > 0
                            ? 'bg-amber-50 text-amber-700 border-amber-200'
                            : 'bg-red-50 text-red-700 border-red-200'
                        }`}>
                          {label}: {cfg.credits_remaining}/{cfg.credits_limit}
                        </span>
                      ) : (
                        <span key={key} className="px-2 py-0.5 rounded-lg text-[11px] font-medium bg-gray-100 text-gray-400 border border-gray-200">
                          {label}: -
                        </span>
                      )
                    })}
                    <span className="px-2 py-0.5 rounded-lg text-[11px] font-semibold bg-teal-50 text-teal-700 border border-teal-200">
                      Diretorios: ilimitado
                    </span>
                  </>
                )}
              </div>
            </div>
            <p className="text-sm text-gray-500">
              Multi-fonte: Diretorios BR (GuiaMais, TeleListas, Apontador) + Bing API + Google CSE + scraping.
              Enriquecimento de emails via Hunter.io + Snov.io. Nenhuma API obrigatoria - diretorios sempre funcionam!
            </p>
          </div>

          {/* API Settings (collapsible) */}
          <div className="bg-white rounded-xl border border-gray-200">
            <button
              onClick={() => setShowApiSettings(!showApiSettings)}
              className="w-full flex items-center justify-between px-5 py-3.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors rounded-xl"
            >
              <span className="flex items-center gap-2">
                <Key className="w-4 h-4 text-gray-400" />
                Configurar API Keys
              </span>
              {showApiSettings ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
            </button>
            {showApiSettings && (
              <div className="border-t border-gray-200 p-5 space-y-5">
                {/* Section: Search APIs */}
                <div className="pb-2 border-b border-gray-100">
                  <p className="text-xs font-bold text-gray-500 uppercase tracking-wider">APIs de Busca (encontrar dominios)</p>
                </div>

                {/* Bing Web Search API */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-semibold text-gray-800">Bing Web Search API</label>
                    {getApiConfig('bing_api')?.is_active ? (
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
                        <span className="text-xs text-green-600 font-medium">Configurada</span>
                        <button
                          onClick={() => handleDeleteApiConfig('bing_api')}
                          className="text-xs text-red-400 hover:text-red-600 ml-1"
                        >
                          Remover
                        </button>
                      </div>
                    ) : (
                      <span className="text-xs text-gray-400">Nao configurada</span>
                    )}
                  </div>
                  {!getApiConfig('bing_api')?.is_active && (
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={bingApiKey}
                        onChange={(e) => setBingApiKey(e.target.value)}
                        placeholder="Bing API Key (Ocp-Apim-Subscription-Key)"
                        className="flex-1 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                      />
                      <button
                        onClick={() => handleSaveApiConfig('bing_api')}
                        disabled={savingApiConfig === 'bing_api'}
                        className="px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-60 whitespace-nowrap"
                      >
                        {savingApiConfig === 'bing_api' ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Salvar'}
                      </button>
                    </div>
                  )}
                  <p className="text-xs text-gray-400">1.000 buscas/mes gratis, sem CAPTCHA. Azure Portal &gt; Bing Search v7</p>
                </div>

                {/* Google Custom Search API */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-semibold text-gray-800">Google Custom Search API</label>
                    {getApiConfig('google_cse')?.is_active ? (
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
                        <span className="text-xs text-green-600 font-medium">Configurada</span>
                        <button
                          onClick={() => handleDeleteApiConfig('google_cse')}
                          className="text-xs text-red-400 hover:text-red-600 ml-1"
                        >
                          Remover
                        </button>
                      </div>
                    ) : (
                      <span className="text-xs text-gray-400">Nao configurada</span>
                    )}
                  </div>
                  {!getApiConfig('google_cse')?.is_active && (
                    <div className="space-y-2">
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={googleCseKey}
                          onChange={(e) => setGoogleCseKey(e.target.value)}
                          placeholder="API Key (Google Cloud Console)"
                          className="flex-1 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                        />
                        <input
                          type="text"
                          value={googleCseCx}
                          onChange={(e) => setGoogleCseCx(e.target.value)}
                          placeholder="Search Engine ID (cx)"
                          className="flex-1 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                        />
                      </div>
                      <button
                        onClick={() => handleSaveApiConfig('google_cse')}
                        disabled={savingApiConfig === 'google_cse'}
                        className="px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-60"
                      >
                        {savingApiConfig === 'google_cse' ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Validar e Salvar'}
                      </button>
                    </div>
                  )}
                  <p className="text-xs text-gray-400">100 buscas/dia gratis. Google Cloud Console + Programmable Search Engine</p>
                </div>

                {/* Section: Email Enrichment APIs */}
                <div className="pt-2 pb-2 border-b border-gray-100">
                  <p className="text-xs font-bold text-gray-500 uppercase tracking-wider">APIs de Enriquecimento (buscar emails por dominio)</p>
                </div>

                {/* Hunter.io */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-semibold text-gray-800">Hunter.io</label>
                    {getApiConfig('hunter')?.is_active ? (
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
                        <span className="text-xs text-green-600 font-medium">Configurada</span>
                        <button
                          onClick={() => handleDeleteApiConfig('hunter')}
                          className="text-xs text-red-400 hover:text-red-600 ml-1"
                        >
                          Remover
                        </button>
                      </div>
                    ) : (
                      <span className="text-xs text-gray-400">Nao configurada</span>
                    )}
                  </div>
                  {!getApiConfig('hunter')?.is_active && (
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={hunterKey}
                        onChange={(e) => setHunterKey(e.target.value)}
                        placeholder="API Key do Hunter.io"
                        className="flex-1 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                      />
                      <button
                        onClick={() => handleSaveApiConfig('hunter')}
                        disabled={savingApiConfig === 'hunter'}
                        className="px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-60 whitespace-nowrap"
                      >
                        {savingApiConfig === 'hunter' ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Salvar'}
                      </button>
                    </div>
                  )}
                  <p className="text-xs text-gray-400">25 buscas/mes gratis. Obtenha em hunter.io/api</p>
                </div>

                {/* Snov.io */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-semibold text-gray-800">Snov.io</label>
                    {getApiConfig('snov')?.is_active ? (
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
                        <span className="text-xs text-green-600 font-medium">Configurada</span>
                        <button
                          onClick={() => handleDeleteApiConfig('snov')}
                          className="text-xs text-red-400 hover:text-red-600 ml-1"
                        >
                          Remover
                        </button>
                      </div>
                    ) : (
                      <span className="text-xs text-gray-400">Nao configurada</span>
                    )}
                  </div>
                  {!getApiConfig('snov')?.is_active && (
                    <div className="space-y-2">
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={snovClientId}
                          onChange={(e) => setSnovClientId(e.target.value)}
                          placeholder="Client ID"
                          className="flex-1 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                        />
                        <input
                          type="text"
                          value={snovSecret}
                          onChange={(e) => setSnovSecret(e.target.value)}
                          placeholder="Client Secret"
                          className="flex-1 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                        />
                      </div>
                      <button
                        onClick={() => handleSaveApiConfig('snov')}
                        disabled={savingApiConfig === 'snov'}
                        className="px-4 py-2.5 bg-primary-600 hover:bg-primary-700 text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-60"
                      >
                        {savingApiConfig === 'snov' ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Validar e Salvar'}
                      </button>
                    </div>
                  )}
                  <p className="text-xs text-gray-400">50 creditos/mes gratis. Obtenha em snov.io/app/api</p>
                </div>
              </div>
            )}
          </div>

          {/* API Search Form */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-1">Buscar Leads por Nicho + Cidade (Multi-Fonte)</h2>
            <p className="text-sm text-gray-500 mb-5">
              Combina diretorios BR + APIs oficiais + scraping. Quanto mais APIs configuradas, mais leads!
            </p>

            <form onSubmit={handleApiSearchSubmit} className="space-y-4">
              {/* Nicho */}
              <div>
                <label htmlFor="apiSearchNiche" className="block text-sm font-medium text-gray-700 mb-1.5">
                  Nicho / Segmento
                </label>
                <input
                  id="apiSearchNiche"
                  type="text"
                  value={apiSearchNiche}
                  onChange={(e) => setApiSearchNiche(e.target.value)}
                  placeholder="Ex: dentista, advogado, pet shop, restaurante..."
                  required
                  className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                />
              </div>

              {/* Mode toggle */}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setApiSearchMode('region')}
                  className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-medium transition-all border ${
                    apiSearchMode === 'region'
                      ? 'bg-primary-50 border-primary-200 text-primary-700'
                      : 'bg-gray-50 border-gray-200 text-gray-500 hover:text-gray-700'
                  }`}
                >
                  <MapPin className="w-3.5 h-3.5 inline mr-1.5" />
                  Regiao Pre-definida
                </button>
                <button
                  type="button"
                  onClick={() => setApiSearchMode('manual')}
                  className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-medium transition-all border ${
                    apiSearchMode === 'manual'
                      ? 'bg-primary-50 border-primary-200 text-primary-700'
                      : 'bg-gray-50 border-gray-200 text-gray-500 hover:text-gray-700'
                  }`}
                >
                  Cidade/Estado Manual
                </button>
              </div>

              {/* Region select */}
              {apiSearchMode === 'region' && (
                <div>
                  <label htmlFor="apiSearchRegion" className="block text-sm font-medium text-gray-700 mb-1.5">
                    Regiao
                  </label>
                  <select
                    id="apiSearchRegion"
                    value={apiSearchRegion}
                    onChange={(e) => setApiSearchRegion(e.target.value)}
                    className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                  >
                    <option value="">Selecione uma regiao...</option>
                    {regions.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name} ({r.cities.length} cidades)
                      </option>
                    ))}
                  </select>
                  {apiSearchRegion && regions.find((r) => r.id === apiSearchRegion) && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {regions.find((r) => r.id === apiSearchRegion)?.cities.map((city) => (
                        <span key={city} className="px-2.5 py-1 bg-gray-100 text-gray-600 rounded-lg text-xs font-medium">
                          {city}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Manual city/state */}
              {apiSearchMode === 'manual' && (
                <div className="grid grid-cols-3 gap-3">
                  <div className="col-span-2">
                    <label htmlFor="apiSearchCity" className="block text-sm font-medium text-gray-700 mb-1.5">
                      Cidade
                    </label>
                    <input
                      id="apiSearchCity"
                      type="text"
                      value={apiSearchCity}
                      onChange={(e) => setApiSearchCity(e.target.value)}
                      placeholder="Ex: Vitoria"
                      className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                    />
                  </div>
                  <div>
                    <label htmlFor="apiSearchState" className="block text-sm font-medium text-gray-700 mb-1.5">
                      Estado
                    </label>
                    <input
                      id="apiSearchState"
                      type="text"
                      value={apiSearchState}
                      onChange={(e) => setApiSearchState(e.target.value.toUpperCase().slice(0, 2))}
                      placeholder="ES"
                      maxLength={2}
                      className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                    />
                  </div>
                </div>
              )}

              {/* Max pages */}
              <div>
                <label htmlFor="apiSearchMaxPages" className="block text-sm font-medium text-gray-700 mb-1.5">
                  Paginas de resultado (1-3)
                </label>
                <select
                  id="apiSearchMaxPages"
                  value={apiSearchMaxPages}
                  onChange={(e) => setApiSearchMaxPages(Number(e.target.value))}
                  className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                >
                  <option value={1}>1 pagina (~10 resultados por cidade)</option>
                  <option value={2}>2 paginas (~20 resultados por cidade)</option>
                  <option value={3}>3 paginas (~30 resultados por cidade) - mais lento</option>
                </select>
              </div>

              {/* Info box */}
              <div className="px-4 py-3 bg-purple-50 border border-purple-200 rounded-xl text-purple-700 text-sm space-y-1">
                <p className="font-semibold">Fluxo multi-fonte:</p>
                <ol className="list-decimal list-inside text-xs space-y-0.5">
                  <li><strong>Fase 0:</strong> Scraping de diretorios BR (GuiaMais, TeleListas, Apontador) - sempre funciona!</li>
                  <li><strong>Fase 1:</strong> Busca dominios: Bing API &rarr; Google CSE &rarr; DDG scraping &rarr; Bing scraping</li>
                  <li><strong>Fase 2:</strong> Para cada dominio: Hunter.io &rarr; Snov.io &rarr; scraping como fallback</li>
                </ol>
                <p className="text-[11px] text-purple-500 mt-1">Nenhuma API e obrigatoria. Diretorios + scraping funcionam sem nenhuma chave configurada.</p>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed shadow-sm"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                {loading ? 'Iniciando busca API...' : 'Iniciar Busca com API'}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* URL Unica */}
      {tab === 'url' && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-1">Extrair de uma URL</h2>
          <p className="text-sm text-gray-500 mb-5">Insira o endereco do site para extrair emails e dados de contato</p>

          <form onSubmit={handleSingleSubmit} className="space-y-4">
            <div>
              <label htmlFor="url" className="block text-sm font-medium text-gray-700 mb-1.5">
                URL do Site
              </label>
              <input
                id="url"
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://exemplo.com.br"
                required
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
              />
              <p className="mt-1.5 text-xs text-gray-400">Faz deep crawl automatico: /contato, /sobre, sitemap.xml</p>
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed shadow-sm"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              {loading ? 'Processando...' : 'Iniciar Scraping'}
            </button>
          </form>
        </div>
      )}

      {/* JSON */}
      {tab === 'json' && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-1">Importar JSON (Apify / Lista)</h2>
          <p className="text-sm text-gray-500 mb-5">Cole o resultado do Apify ou lista JSON de URLs para processar em lote</p>

          <form onSubmit={handleBatchSubmit} className="space-y-4">
            <div>
              <label htmlFor="batchName" className="block text-sm font-medium text-gray-700 mb-1.5">
                Nome do Lote
              </label>
              <input
                id="batchName"
                type="text"
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
                placeholder="Ex: Dentistas SP - Marco 2026"
                required
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
              />
            </div>
            <div>
              <label htmlFor="jsonInput" className="block text-sm font-medium text-gray-700 mb-1.5">
                Cole o JSON aqui
              </label>
              <textarea
                id="jsonInput"
                value={jsonInput}
                onChange={(e) => handleJsonChange(e.target.value)}
                placeholder={'[\n  {"website": "https://empresa1.com.br"},\n  {"website": "https://empresa2.com.br"}\n]'}
                rows={8}
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm font-mono resize-y"
              />
              <p className="mt-1.5 text-xs text-gray-400">
                Aceita formato Apify {`[{"website":"..."}]`} ou array de strings {`["url1","url2"]`}
              </p>
            </div>
            {parsedCount > 0 && (
              <div className="px-4 py-2.5 bg-primary-50 border border-primary-100 rounded-xl text-primary-700 text-sm font-medium">
                {parsedCount} URL{parsedCount !== 1 ? 's' : ''} detectada{parsedCount !== 1 ? 's' : ''}
              </div>
            )}
            <button
              type="submit"
              disabled={loading || parsedCount === 0}
              className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed shadow-sm"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              {loading ? 'Criando lote...' : `Iniciar Extracao em Lote (${parsedCount} URLs)`}
            </button>
          </form>
        </div>
      )}

      {/* URLs Texto */}
      {tab === 'text' && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-1">Lista de URLs (uma por linha)</h2>
          <p className="text-sm text-gray-500 mb-5">Cole URLs simples, uma por linha, para processar em lote</p>

          <form onSubmit={handleBatchSubmit} className="space-y-4">
            <div>
              <label htmlFor="batchNameText" className="block text-sm font-medium text-gray-700 mb-1.5">
                Nome do Lote
              </label>
              <input
                id="batchNameText"
                type="text"
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
                placeholder="Ex: Leads Google Maps - Restaurantes"
                required
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
              />
            </div>
            <div>
              <label htmlFor="textInput" className="block text-sm font-medium text-gray-700 mb-1.5">
                Cole as URLs (uma por linha)
              </label>
              <textarea
                id="textInput"
                value={textInput}
                onChange={(e) => handleTextChange(e.target.value)}
                placeholder={'https://empresa1.com.br\nhttps://empresa2.com.br\nhttps://empresa3.com.br'}
                rows={8}
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm font-mono resize-y"
              />
              <p className="mt-1.5 text-xs text-gray-400">Uma URL por linha. O sistema adiciona https:// automaticamente se necessario</p>
            </div>
            {parsedCount > 0 && (
              <div className="px-4 py-2.5 bg-primary-50 border border-primary-100 rounded-xl text-primary-700 text-sm font-medium">
                {parsedCount} URL{parsedCount !== 1 ? 's' : ''} detectada{parsedCount !== 1 ? 's' : ''}
              </div>
            )}
            <button
              type="submit"
              disabled={loading || parsedCount === 0}
              className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed shadow-sm"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              {loading ? 'Criando lote...' : `Iniciar Extracao em Lote (${parsedCount} URLs)`}
            </button>
          </form>
        </div>
      )}

      {/* Extrair de Texto (Paste) */}
      {tab === 'paste' && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-1">Extrair de Texto</h2>
          <p className="text-sm text-gray-500 mb-5">
            Cole qualquer texto (resultados do Google, lista de contatos, planilha, etc.)
            e extraia emails, telefones e dados automaticamente
          </p>

          <div className="space-y-4">
            <div>
              <label htmlFor="pasteInput" className="block text-sm font-medium text-gray-700 mb-1.5">
                Cole o texto aqui
              </label>
              <textarea
                id="pasteInput"
                value={pasteInput}
                onChange={(e) => setPasteInput(e.target.value)}
                placeholder={`Cole aqui resultados do Google, listas de empresas, textos com emails e telefones...\n\nExemplo:\nEmpresa ABC\ncontato@empresaabc.com.br\n(27) 3333-4444\n\nEmpresa XYZ\ninfo@xyz.com.br\n(11) 98765-4321`}
                rows={10}
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm resize-y"
              />
            </div>

            <button
              onClick={handleExtract}
              disabled={!pasteInput.trim() || extracting}
              className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed shadow-sm"
            >
              {extracting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              {extracting ? 'Extraindo...' : 'Extrair Dados do Texto'}
            </button>
          </div>

          {/* Extraction Results */}
          {extractedContacts.length > 0 && (
            <div className="mt-6 space-y-4">
              {/* Stats badges */}
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="px-3 py-1.5 bg-green-50 border border-green-200 text-green-700 rounded-lg font-medium">
                  {extractedContacts.filter((c) => c.email).length} emails
                </span>
                <span className="px-3 py-1.5 bg-blue-50 border border-blue-200 text-blue-700 rounded-lg font-medium">
                  {extractedContacts.filter((c) => c.phone).length} telefones
                </span>
                <span className="px-3 py-1.5 bg-purple-50 border border-purple-200 text-purple-700 rounded-lg font-medium">
                  {extractedContacts.length} contatos
                </span>
                <span className="px-3 py-1.5 bg-primary-50 border border-primary-200 text-primary-700 rounded-lg font-medium">
                  {selectedCount} selecionado{selectedCount !== 1 ? 's' : ''}
                </span>
              </div>

              {/* Table */}
              <div className="border border-gray-200 rounded-xl overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 border-b border-gray-200">
                      <tr>
                        <th className="px-3 py-2.5 text-left w-10">
                          <input
                            type="checkbox"
                            checked={extractedContacts.length > 0 && extractedContacts.every((c) => c.selected)}
                            onChange={toggleSelectAll}
                            className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                          />
                        </th>
                        <th className="px-3 py-2.5 text-left text-gray-600 font-semibold">Email</th>
                        <th className="px-3 py-2.5 text-left text-gray-600 font-semibold">Telefone</th>
                        <th className="px-3 py-2.5 text-left text-gray-600 font-semibold hidden md:table-cell">Empresa</th>
                        <th className="px-3 py-2.5 text-left text-gray-600 font-semibold hidden lg:table-cell">Website</th>
                        <th className="px-3 py-2.5 w-10"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {extractedContacts.map((contact, idx) => (
                        <tr
                          key={contact.id}
                          className={`transition-colors ${
                            contact.selected ? 'bg-white hover:bg-gray-50/80' : 'bg-gray-50/50 opacity-50'
                          }`}
                        >
                          <td className="px-3 py-2.5">
                            <input
                              type="checkbox"
                              checked={contact.selected}
                              onChange={() => toggleSelect(idx)}
                              className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                            />
                          </td>
                          <td className="px-3 py-2.5 text-gray-900 font-medium">
                            {contact.email || <span className="text-gray-400">-</span>}
                          </td>
                          <td className="px-3 py-2.5 text-gray-700 whitespace-nowrap">
                            {contact.phone || <span className="text-gray-400">-</span>}
                          </td>
                          <td className="px-3 py-2.5 text-gray-700 max-w-[200px] truncate hidden md:table-cell">
                            {contact.company_name || <span className="text-gray-400">-</span>}
                          </td>
                          <td className="px-3 py-2.5 text-gray-500 max-w-[200px] truncate hidden lg:table-cell">
                            {contact.website ? (
                              <a
                                href={contact.website}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-primary-600 hover:underline"
                              >
                                {contact.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                              </a>
                            ) : (
                              <span className="text-gray-400">-</span>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            <button
                              onClick={() => removeContact(idx)}
                              className="text-gray-400 hover:text-red-500 transition-colors"
                              title="Remover"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Save section */}
              <div className="flex flex-col sm:flex-row gap-3">
                <input
                  type="text"
                  value={pasteBatchName}
                  onChange={(e) => setPasteBatchName(e.target.value)}
                  placeholder="Nome do lote (opcional)"
                  className="flex-1 px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all text-sm"
                />
                <button
                  onClick={handleSaveLeads}
                  disabled={saving || selectedCount === 0}
                  className="flex items-center justify-center gap-2 px-6 py-3 bg-green-600 hover:bg-green-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed shadow-sm whitespace-nowrap"
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                  Salvar {selectedCount} Lead{selectedCount !== 1 ? 's' : ''}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Info */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center gap-2 mb-4">
          <Info className="w-4 h-4 text-gray-400" />
          <h3 className="text-sm font-semibold text-gray-900">Como funciona?</h3>
        </div>
        <ol className="space-y-2 text-sm text-gray-600 list-decimal list-inside">
          <li><strong className="text-gray-800">Busca:</strong> Busca automatica por nicho + cidade em motores de busca (DuckDuckGo/Bing)</li>
          <li><strong className="text-gray-800">Busca API:</strong> Busca dominios + enriquece via Hunter.io/Snov.io com fallback para scraping</li>
          <li><strong className="text-gray-800">URL Unica:</strong> Extrai dados de uma pagina com deep crawl</li>
          <li><strong className="text-gray-800">JSON / Lote:</strong> Cole o resultado do Apify ou lista JSON (ate 500 URLs)</li>
          <li><strong className="text-gray-800">URLs Texto:</strong> Cole URLs simples, uma por linha (ate 500)</li>
          <li><strong className="text-gray-800">Extrair de Texto:</strong> Cole qualquer texto e extraia emails, telefones e dados automaticamente</li>
          <li>O sistema faz <strong className="text-gray-800">deep crawl</strong> - visita /contato, /sobre e sitemap.xml</li>
          <li>Extrai <strong className="text-gray-800">emails, telefones, WhatsApp e CNPJ</strong></li>
          <li>Detecta <strong className="text-gray-800">Instagram, Facebook, LinkedIn, Twitter e YouTube</strong></li>
          <li>Captura <strong className="text-gray-800">endereco, cidade e estado</strong> automaticamente</li>
          <li>Exporte em <strong className="text-gray-800">CSV completo, JSON ou texto</strong> para seu CRM</li>
        </ol>
      </div>
    </div>
  )
}
