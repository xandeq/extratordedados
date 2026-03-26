import { useRouter } from 'next/router'
import { useEffect, useState } from 'react'
import api from '../../lib/api'
import Layout from '../../components/Layout'
import { Tag } from 'lucide-react'

interface Niche {
  id: number
  name: string
  category: string
  active: boolean
  priority: number
  last_used_at: string | null
  created_at: string | null
}

interface CatalogData {
  niches: Record<string, Niche[]>
  total: number
}

export default function NichesCatalog() {
  const router = useRouter()
  const [data, setData] = useState<CatalogData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState('')
  const [savingId, setSavingId] = useState<number | null>(null)

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) { router.replace('/login'); return }
    api.get('/api/admin/niches')
      .then(res => {
        setData(res.data)
        const cats = Object.keys(res.data.niches)
        if (cats.length > 0) setActiveTab(cats[0])
      })
      .catch(err => {
        if (err.response?.status === 401 || err.response?.status === 403) router.replace('/login')
        else setError('Erro ao carregar catálogo de nichos')
      })
      .finally(() => setLoading(false))
  }, [])

  const toggleActive = async (niche: Niche) => {
    setSavingId(niche.id)
    try {
      await api.put(`/api/admin/niches/${niche.id}`, { active: !niche.active })
      setData(prev => {
        if (!prev) return prev
        const updated = { ...prev }
        updated.niches = { ...prev.niches }
        updated.niches[niche.category] = prev.niches[niche.category].map(n =>
          n.id === niche.id ? { ...n, active: !n.active } : n
        )
        return updated
      })
    } catch { setError('Erro ao atualizar nicho') }
    finally { setSavingId(null) }
  }

  const savePriority = async (niche: Niche, value: string) => {
    const priority = parseInt(value, 10)
    if (isNaN(priority)) return
    setSavingId(niche.id)
    try {
      await api.put(`/api/admin/niches/${niche.id}`, { priority })
      setData(prev => {
        if (!prev) return prev
        const updated = { ...prev }
        updated.niches = { ...prev.niches }
        updated.niches[niche.category] = prev.niches[niche.category].map(n =>
          n.id === niche.id ? { ...n, priority } : n
        )
        return updated
      })
    } catch { setError('Erro ao salvar prioridade') }
    finally { setSavingId(null) }
  }

  const categories = data ? Object.keys(data.niches) : []

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <Tag className="text-blue-600" size={24} />
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Catálogo de Nichos</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {data ? `${data.total} nichos cadastrados — pipeline rotaciona pelos ativos` : 'Carregando...'}
            </p>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded-lg text-sm">
            {error}
          </div>
        )}

        {loading && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">Carregando catálogo...</div>
        )}

        {!loading && data && categories.length > 0 && (
          <>
            {/* Category Tabs */}
            <div className="border-b border-gray-200 dark:border-gray-700 mb-6 overflow-x-auto">
              <div className="flex gap-1 min-w-max">
                {categories.map(cat => {
                  const count = data.niches[cat].length
                  const activeCount = data.niches[cat].filter(n => n.active).length
                  return (
                    <button
                      key={cat}
                      onClick={() => setActiveTab(cat)}
                      className={`px-4 py-2 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                        activeTab === cat
                          ? 'border-blue-600 text-blue-600 dark:text-blue-400'
                          : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
                      }`}
                    >
                      {cat} ({activeCount}/{count})
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Niche List for Active Tab */}
            {activeTab && data.niches[activeTab] && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50">
                      <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Nome</th>
                      <th className="text-center px-4 py-3 font-medium text-gray-600 dark:text-gray-300 w-32">Prioridade</th>
                      <th className="text-center px-4 py-3 font-medium text-gray-600 dark:text-gray-300 w-24">Ativo</th>
                      <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300 w-40">Último uso</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.niches[activeTab].map((niche, idx) => (
                      <tr
                        key={niche.id}
                        className={`border-b border-gray-100 dark:border-gray-700/50 ${
                          idx % 2 === 0 ? '' : 'bg-gray-50/50 dark:bg-gray-700/20'
                        } ${!niche.active ? 'opacity-50' : ''}`}
                      >
                        <td className="px-4 py-3 text-gray-900 dark:text-white">{niche.name}</td>
                        <td className="px-4 py-3 text-center">
                          <input
                            type="number"
                            defaultValue={niche.priority}
                            min={1}
                            max={999}
                            className="w-20 text-center border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
                            onBlur={e => savePriority(niche, e.target.value)}
                            disabled={savingId === niche.id}
                          />
                        </td>
                        <td className="px-4 py-3 text-center">
                          <button
                            onClick={() => toggleActive(niche)}
                            disabled={savingId === niche.id}
                            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                              niche.active ? 'bg-blue-600' : 'bg-gray-300 dark:bg-gray-600'
                            }`}
                            title={niche.active ? 'Desativar' : 'Ativar'}
                          >
                            <span
                              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                                niche.active ? 'translate-x-6' : 'translate-x-1'
                              }`}
                            />
                          </button>
                        </td>
                        <td className="px-4 py-3 text-gray-500 dark:text-gray-400 text-xs">
                          {niche.last_used_at
                            ? new Date(niche.last_used_at).toLocaleDateString('pt-BR')
                            : 'Nunca'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {!loading && data && categories.length === 0 && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            Nenhum nicho cadastrado. Execute populate_niches.sql no banco de dados.
          </div>
        )}
      </div>
    </Layout>
  )
}
