import { useState, useEffect } from 'react'
import {
  X, Mail, Phone, Building2, Globe, MapPin, MessageCircle,
  Instagram, Facebook, Linkedin, Twitter, Youtube,
  ExternalLink, Save, Tag, FileText, User, Hash
} from 'lucide-react'
import api from '../lib/api'
import { useToast } from './Toast'
import StatusBadge from './StatusBadge'

const CRM_STATUSES = [
  { value: 'novo', label: 'Novo' },
  { value: 'contatado', label: 'Contatado' },
  { value: 'interessado', label: 'Interessado' },
  { value: 'negociando', label: 'Negociando' },
  { value: 'cliente', label: 'Cliente' },
  { value: 'descartado', label: 'Descartado' },
]

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

interface LeadDrawerProps {
  lead: Lead | null
  onClose: () => void
  onUpdate: (lead: Lead) => void
}

export default function LeadDrawer({ lead, onClose, onUpdate }: LeadDrawerProps) {
  const { addToast } = useToast()
  const [status, setStatus] = useState('')
  const [tags, setTags] = useState('')
  const [notes, setNotes] = useState('')
  const [contactName, setContactName] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (lead) {
      setStatus(lead.crm_status || 'novo')
      setTags(lead.tags || '')
      setNotes(lead.notes || '')
      setContactName(lead.contact_name || '')
    }
  }, [lead])

  if (!lead) return null

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.put(`/api/leads/${lead.id}`, {
        crm_status: status,
        tags,
        notes,
        contact_name: contactName,
      })
      addToast('Lead atualizado!', 'success')
      onUpdate({ ...lead, crm_status: status, tags, notes, contact_name: contactName })
    } catch {
      addToast('Erro ao salvar', 'error')
    } finally {
      setSaving(false)
    }
  }

  const socials = [
    { url: lead.instagram, icon: Instagram, label: 'Instagram', color: 'hover:text-pink-500 hover:bg-pink-50' },
    { url: lead.facebook, icon: Facebook, label: 'Facebook', color: 'hover:text-blue-600 hover:bg-blue-50' },
    { url: lead.linkedin, icon: Linkedin, label: 'LinkedIn', color: 'hover:text-sky-600 hover:bg-sky-50' },
    { url: lead.twitter, icon: Twitter, label: 'Twitter', color: 'hover:text-gray-700 hover:bg-gray-100' },
    { url: lead.youtube, icon: Youtube, label: 'YouTube', color: 'hover:text-red-500 hover:bg-red-50' },
  ].filter(s => s.url)

  return (
    <>
      {/* Overlay */}
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-full max-w-lg bg-white z-50 shadow-2xl flex flex-col animate-slide-in-right">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-primary-50 flex items-center justify-center flex-shrink-0">
              <Building2 className="w-5 h-5 text-primary-600" />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-bold text-gray-900 truncate">{lead.company_name || 'Sem nome'}</h2>
              <p className="text-xs text-gray-400 truncate">{lead.email}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* CRM Status */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Status</label>
            <div className="grid grid-cols-3 gap-1.5">
              {CRM_STATUSES.map((s) => (
                <button
                  key={s.value}
                  onClick={() => setStatus(s.value)}
                  className={`px-3 py-2 rounded-lg text-xs font-medium transition-all border ${
                    status === s.value
                      ? 'ring-2 ring-primary-400 border-primary-300 bg-primary-50 text-primary-700'
                      : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          {/* Contact Info */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Contato</label>
            <div className="space-y-2.5">
              <div className="flex items-center gap-3 text-sm">
                <Mail className="w-4 h-4 text-gray-400 flex-shrink-0" />
                <a href={`mailto:${lead.email}`} className="text-primary-600 hover:underline truncate">{lead.email}</a>
              </div>
              {lead.phone && (
                <div className="flex items-center gap-3 text-sm text-gray-700">
                  <Phone className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  {lead.phone}
                </div>
              )}
              {lead.whatsapp && (
                <a href={`https://wa.me/${lead.whatsapp.replace(/\D/g, '')}`} target="_blank" rel="noopener noreferrer"
                   className="flex items-center gap-3 text-sm text-green-600 hover:underline">
                  <MessageCircle className="w-4 h-4 flex-shrink-0" />
                  {lead.whatsapp}
                </a>
              )}
              {lead.cnpj && (
                <div className="flex items-center gap-3 text-sm text-gray-700">
                  <Hash className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  {lead.cnpj}
                </div>
              )}
              {lead.website && (
                <a href={lead.website} target="_blank" rel="noopener noreferrer"
                   className="flex items-center gap-3 text-sm text-primary-600 hover:underline">
                  <Globe className="w-4 h-4 flex-shrink-0" />
                  <span className="truncate">{lead.website.replace(/^https?:\/\/(www\.)?/, '')}</span>
                </a>
              )}
              {(lead.address || lead.city || lead.state) && (
                <div className="flex items-center gap-3 text-sm text-gray-600">
                  <MapPin className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  <span className="truncate">
                    {lead.address ? lead.address.substring(0, 50) : ''}
                    {lead.city ? ` - ${lead.city}` : ''}
                    {lead.state ? `/${lead.state}` : ''}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Social Media */}
          {socials.length > 0 && (
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Redes Sociais</label>
              <div className="flex items-center gap-1.5">
                {socials.map((s, idx) => {
                  const Icon = s.icon
                  return (
                    <a key={idx} href={s.url!} target="_blank" rel="noopener noreferrer"
                       className={`p-2 rounded-lg text-gray-400 transition-colors ${s.color}`} title={s.label}>
                      <Icon className="w-5 h-5" />
                    </a>
                  )
                })}
              </div>
            </div>
          )}

          {/* Contact Name */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
              Nome do Contato
            </label>
            <div className="relative">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                placeholder="Ex: Joao Silva"
                className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all"
              />
            </div>
          </div>

          {/* Tags */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
              Tags
            </label>
            <div className="relative">
              <Tag className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="Ex: premium,sao-paulo,restaurante"
                className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all"
              />
            </div>
            <p className="mt-1 text-xs text-gray-400">Separe tags por virgula</p>
            {tags && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {tags.split(',').map((t, i) => t.trim() && (
                  <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary-50 text-primary-700 rounded-full text-xs font-medium">
                    {t.trim()}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Notes */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
              Observacoes
            </label>
            <div className="relative">
              <FileText className="absolute left-3 top-3 w-4 h-4 text-gray-400" />
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Adicionar notas sobre este lead..."
                rows={4}
                className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-all resize-y"
              />
            </div>
          </div>

          {/* Meta info */}
          <div className="text-xs text-gray-400 space-y-1 pt-2 border-t border-gray-100">
            <p>Lote: <span className="text-gray-600">{lead.batch_name}</span></p>
            {lead.source_url && (
              <p className="truncate">Fonte: <span className="text-gray-600">{lead.source_url}</span></p>
            )}
            <p>Extraido em: <span className="text-gray-600">{lead.extracted_at ? new Date(lead.extracted_at).toLocaleString('pt-BR') : '-'}</span></p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-semibold text-sm transition-colors disabled:opacity-60 shadow-sm"
          >
            <Save className="w-4 h-4" />
            {saving ? 'Salvando...' : 'Salvar Alteracoes'}
          </button>
        </div>
      </div>
    </>
  )
}
