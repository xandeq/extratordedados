import { useEffect, useState } from 'react'
import { useRouter } from 'next/router'
import Head from 'next/head'
import Layout from '../components/Layout'
import api from '../lib/api'
import { Bell, BellOff, Trash2 } from 'lucide-react'

interface SavedSearch {
  id: number
  name: string
  filters: Record<string, string | boolean>
  notify_enabled: boolean
  notify_email: string | null
  last_notified_at: string | null
  created_at: string
}

export default function SavedSearchesPage() {
  const router = useRouter()
  const [searches, setSearches] = useState<SavedSearch[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/api/client/saved-searches')
      .then(r => setSearches(r.data.saved_searches || []))
      .catch(err => {
        if (err.response?.status === 401) router.push('/login')
        else setError('Erro ao carregar buscas salvas.')
      })
      .finally(() => setLoading(false))
  }, [])

  const filtersSummary = (f: Record<string, string | boolean>) => {
    const parts: string[] = []
    if (f.category) parts.push(String(f.category))
    if (f.city)     parts.push(String(f.city))
    if (f.state)    parts.push(String(f.state))
    if (f.q)        parts.push(`"${f.q}"`)
    return parts.join(' · ') || 'Todos os leads'
  }

  const toggleNotify = async (ss: SavedSearch) => {
    try {
      const r = await api.patch(`/api/client/saved-searches/${ss.id}`, {
        notify_enabled: !ss.notify_enabled,
      })
      setSearches(prev => prev.map(s => s.id === ss.id ? { ...s, ...r.data } : s))
    } catch {
      alert('Erro ao atualizar notificação.')
    }
  }

  const deleteSS = async (id: number) => {
    if (!confirm('Remover esta busca salva?')) return
    try {
      await api.delete(`/api/client/saved-searches/${id}`)
      setSearches(prev => prev.filter(s => s.id !== id))
    } catch {
      alert('Erro ao remover busca.')
    }
  }

  return (
    <Layout>
      <Head>
        <title>Buscas Salvas — Extrator de Dados</title>
      </Head>
      <div className="max-w-3xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
          Buscas Salvas
        </h1>
        <p className="text-gray-500 dark:text-gray-400 mb-6 text-sm">
          Ative notificações para receber email quando novos leads chegarem.
        </p>

        {loading && <p className="text-gray-400">Carregando...</p>}
        {error   && <p className="text-red-500">{error}</p>}

        {!loading && searches.length === 0 && (
          <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-8 text-center">
            <p className="text-gray-500 dark:text-gray-400">
              Nenhuma busca salva.{' '}
              <a href="/portal" className="text-blue-600 underline">
                Acesse o portal
              </a>{' '}
              e clique em &quot;Salvar Busca&quot;.
            </p>
          </div>
        )}

        <ul className="space-y-3">
          {searches.map(ss => (
            <li
              key={ss.id}
              className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700
                         rounded-lg px-5 py-4 flex items-center justify-between gap-4"
            >
              <div className="min-w-0 flex-1">
                <p className="font-medium text-gray-900 dark:text-white truncate">{ss.name}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {filtersSummary(ss.filters)}
                </p>
                {ss.last_notified_at && (
                  <p className="text-xs text-gray-400 mt-0.5">
                    Ultima notificacao: {new Date(ss.last_notified_at).toLocaleDateString('pt-BR')}
                  </p>
                )}
                {ss.notify_email && (
                  <p className="text-xs text-gray-400">Email: {ss.notify_email}</p>
                )}
              </div>

              <div className="flex items-center gap-3 shrink-0">
                {/* Notification toggle */}
                <button
                  onClick={() => toggleNotify(ss)}
                  title={ss.notify_enabled ? 'Desativar notificacoes' : 'Ativar notificacoes'}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors
                    ${ss.notify_enabled ? 'bg-blue-600' : 'bg-gray-200 dark:bg-gray-700'}`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition
                    ${ss.notify_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
                {ss.notify_enabled ? (
                  <Bell size={16} className="text-blue-500" />
                ) : (
                  <BellOff size={16} className="text-gray-400" />
                )}

                {/* Delete */}
                <button
                  onClick={() => deleteSS(ss.id)}
                  className="p-1.5 rounded hover:bg-red-50 dark:hover:bg-red-900/20
                             text-gray-400 hover:text-red-500 transition-colors"
                  title="Remover busca salva"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </Layout>
  )
}
