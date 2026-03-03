import { useState } from 'react'
import {
  X, Download, FileText, FileJson, MessageCircle, Phone,
  Mail, Users, ChevronRight, Copy, ExternalLink, Loader2
} from 'lucide-react'
import api from '../lib/api'
import { useToast } from './Toast'

interface ExportModalProps {
  onClose: () => void
  totalLeads: number
  filters?: {
    search?: string
    status?: string
    tag?: string
    batch_id?: string | number
    ids?: number[]
  }
}

const FORMATS = [
  {
    id: 'csv',
    label: 'CSV Completo',
    description: 'Todos os campos, compativel com Excel e Google Sheets',
    icon: FileText,
    color: 'text-green-600 bg-green-50',
    ext: '.csv',
  },
  {
    id: 'mailchimp',
    label: 'Mailchimp',
    description: 'Pronto para importar no Mailchimp (Email, Nome, Empresa, Tags)',
    icon: Mail,
    color: 'text-yellow-600 bg-yellow-50',
    ext: '.csv',
  },
  {
    id: 'whatsapp',
    label: 'WhatsApp CSV',
    description: 'Planilha com telefones formatados +55XX para envio em massa',
    icon: MessageCircle,
    color: 'text-green-600 bg-green-50',
    ext: '.csv',
  },
  {
    id: 'whatsapp_txt',
    label: 'WhatsApp TXT',
    description: 'Um numero por linha (+55XXXXXXXXXXX) para copiar e colar',
    icon: Phone,
    color: 'text-green-600 bg-green-50',
    ext: '.txt',
  },
  {
    id: 'vcard',
    label: 'vCard Contatos',
    description: 'Arquivo .vcf para importar direto no celular ou Outlook',
    icon: Users,
    color: 'text-blue-600 bg-blue-50',
    ext: '.vcf',
  },
  {
    id: 'json',
    label: 'JSON',
    description: 'Dados estruturados para desenvolvedores e automacoes',
    icon: FileJson,
    color: 'text-purple-600 bg-purple-50',
    ext: '.json',
  },
]

const WA_VARIABLES = ['{empresa}', '{email}', '{website}', '{telefone}', '{contato}']

export default function ExportModal({ onClose, totalLeads, filters = {} }: ExportModalProps) {
  const { addToast } = useToast()
  const [selectedFormat, setSelectedFormat] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [showWhatsAppTemplate, setShowWhatsAppTemplate] = useState(false)
  const [waTemplate, setWaTemplate] = useState(
    'Ola {empresa}, tudo bem? Vi seu site {website} e gostaria de conversar sobre uma parceria.'
  )

  const handleExport = async () => {
    if (!selectedFormat) return
    setDownloading(true)

    try {
      const params = new URLSearchParams({ format: selectedFormat })
      if (filters.search) params.append('search', filters.search)
      if (filters.status) params.append('status', filters.status)
      if (filters.tag) params.append('tag', filters.tag)
      if (filters.batch_id) params.append('batch_id', String(filters.batch_id))
      if (filters.ids && filters.ids.length > 0) params.append('ids', filters.ids.join(','))

      const response = await api.get(`/api/leads/export?${params.toString()}`, {
        responseType: 'blob',
      })

      const format = FORMATS.find(f => f.id === selectedFormat)
      const filename = `leads_${selectedFormat}${format?.ext || '.csv'}`
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      window.URL.revokeObjectURL(url)

      addToast(`${filename} baixado com sucesso!`, 'success')
      onClose()
    } catch (err: any) {
      if (err.response?.status === 404) {
        addToast('Nenhum lead para exportar com esses filtros', 'error')
      } else {
        addToast('Erro ao exportar leads', 'error')
      }
    } finally {
      setDownloading(false)
    }
  }

  const handleCopyWaLinks = async () => {
    try {
      const params = new URLSearchParams({ format: 'json' })
      if (filters.search) params.append('search', filters.search)
      if (filters.status) params.append('status', filters.status)
      if (filters.tag) params.append('tag', filters.tag)
      if (filters.batch_id) params.append('batch_id', String(filters.batch_id))
      if (filters.ids && filters.ids.length > 0) params.append('ids', filters.ids.join(','))

      const response = await api.get(`/api/leads/export?${params.toString()}`)
      const leads = response.data

      const links: string[] = []
      for (const l of leads) {
        const phone = l.whatsapp || l.phone || ''
        if (!phone) continue
        let clean = phone.replace(/\D/g, '')
        if (clean.length === 10 || clean.length === 11) clean = '55' + clean
        if (clean.length < 10) continue

        let msg = waTemplate
          .replace(/\{empresa\}/g, l.company_name || '')
          .replace(/\{email\}/g, l.email || '')
          .replace(/\{website\}/g, (l.website || '').replace(/^https?:\/\/(www\.)?/, ''))
          .replace(/\{telefone\}/g, phone)
          .replace(/\{contato\}/g, l.contact_name || '')

        links.push(`https://wa.me/${clean}?text=${encodeURIComponent(msg)}`)
      }

      if (links.length === 0) {
        addToast('Nenhum lead com telefone encontrado', 'error')
        return
      }

      await navigator.clipboard.writeText(links.join('\n'))
      addToast(`${links.length} links WhatsApp copiados!`, 'success')
    } catch {
      addToast('Erro ao gerar links WhatsApp', 'error')
    }
  }

  return (
    <>
      {/* Overlay */}
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />

      {/* Modal */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col animate-fade-in">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <div>
              <h2 className="text-lg font-bold text-gray-900">Exportar Leads</h2>
              <p className="text-sm text-gray-500 mt-0.5">
                {filters.ids && filters.ids.length > 0
                  ? `${filters.ids.length} leads selecionados`
                  : `${totalLeads} leads com filtros atuais`}
              </p>
            </div>
            <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
              <X className="w-5 h-5 text-gray-400" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
            {/* Format selection */}
            {FORMATS.map((format) => {
              const Icon = format.icon
              const isActive = selectedFormat === format.id
              return (
                <button
                  key={format.id}
                  onClick={() => setSelectedFormat(format.id)}
                  className={`w-full flex items-center gap-4 p-4 rounded-xl border-2 transition-all text-left ${
                    isActive
                      ? 'border-primary-400 bg-primary-50/50 ring-1 ring-primary-200'
                      : 'border-gray-100 hover:border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${format.color}`}>
                    <Icon className="w-5 h-5" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-900">{format.label}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{format.description}</p>
                  </div>
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 transition-all ${
                    isActive ? 'border-primary-600 bg-primary-600' : 'border-gray-300'
                  }`}>
                    {isActive && <div className="w-2 h-2 bg-white rounded-full" />}
                  </div>
                </button>
              )
            })}

            {/* WhatsApp template section */}
            <div className="pt-2 border-t border-gray-100">
              <button
                onClick={() => setShowWhatsAppTemplate(!showWhatsAppTemplate)}
                className="flex items-center gap-2 text-sm font-medium text-gray-700 hover:text-primary-600 transition-colors"
              >
                <MessageCircle className="w-4 h-4 text-green-500" />
                Template WhatsApp Marketing
                <ChevronRight className={`w-4 h-4 transition-transform ${showWhatsAppTemplate ? 'rotate-90' : ''}`} />
              </button>

              {showWhatsAppTemplate && (
                <div className="mt-3 space-y-3">
                  <textarea
                    value={waTemplate}
                    onChange={(e) => setWaTemplate(e.target.value)}
                    rows={3}
                    placeholder="Escreva sua mensagem..."
                    className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all resize-y"
                  />
                  <div className="flex flex-wrap gap-1.5">
                    {WA_VARIABLES.map((v) => (
                      <button
                        key={v}
                        onClick={() => setWaTemplate(prev => prev + ' ' + v)}
                        className="px-2 py-1 bg-green-50 text-green-700 rounded-md text-xs font-medium hover:bg-green-100 transition-colors"
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                  <button
                    onClick={handleCopyWaLinks}
                    className="inline-flex items-center gap-2 px-4 py-2.5 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold rounded-xl transition-colors"
                  >
                    <Copy className="w-4 h-4" />
                    Copiar Links wa.me com Mensagem
                  </button>
                  <p className="text-xs text-gray-400">
                    Gera um link wa.me/+55XX?text=... para cada lead com telefone
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-200 flex items-center gap-3">
            <button
              onClick={onClose}
              className="flex-1 px-4 py-3 border border-gray-200 text-gray-700 rounded-xl font-medium text-sm hover:bg-gray-50 transition-colors"
            >
              Cancelar
            </button>
            <button
              onClick={handleExport}
              disabled={!selectedFormat || downloading}
              className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
            >
              {downloading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Exportando...
                </>
              ) : (
                <>
                  <Download className="w-4 h-4" />
                  Baixar {selectedFormat ? FORMATS.find(f => f.id === selectedFormat)?.ext : ''}
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
