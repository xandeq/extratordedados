import { useState, useEffect, useCallback } from 'react'
import Head from 'next/head'
import { Loader, RefreshCw } from 'lucide-react'
import api from '../../lib/api'
import { useToast } from '../../components/Toast'
import Layout from '../../components/Layout'

interface NicheRequest {
  id: number
  niche: string
  city: string | null
  state: string | null
  votes: number
  status: string
  admin_notes: string | null
  leads_added: number | null
  created_at: string | null
  requester_username: string
}

const statusBadge: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  approved: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  processing: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
  done: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  rejected: 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400',
}

const statusLabel: Record<string, string> = {
  pending: 'Aguardando',
  approved: 'Aprovado',
  processing: 'Processando...',
  done: 'Concluído',
  rejected: 'Rejeitado',
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

export default function AdminNicheRequests() {
  const { addToast } = useToast()
  const [requests, setRequests] = useState<NicheRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [actionId, setActionId] = useState<number | null>(null)

  const fetchRequests = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await api.get('/api/admin/niche-requests')
      setRequests(resp.data.requests || [])
    } catch (e) {
      console.error('Failed to load niche requests', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchRequests()
  }, [fetchRequests])

  const handleApprove = async (req: NicheRequest) => {
    setActionId(req.id)
    // Optimistic update
    setRequests((prev) =>
      prev.map((r) => (r.id === req.id ? { ...r, status: 'processing' } : r))
    )
    try {
      await api.post(`/api/admin/niche-requests/${req.id}/approve`)
      addToast(
        `Extração iniciada para ${req.niche}${req.city ? ` em ${req.city}${req.state ? `/${req.state}` : ''}` : ''}.`,
        'success'
      )
    } catch (e: any) {
      addToast('Erro ao aprovar solicitação.', 'error')
      setRequests((prev) =>
        prev.map((r) => (r.id === req.id ? { ...r, status: 'pending' } : r))
      )
    } finally {
      setActionId(null)
    }
  }

  const handleReject = async (req: NicheRequest) => {
    if (!confirm('Rejeitar esta solicitação? Esta ação não pode ser desfeita.')) return
    setActionId(req.id)
    try {
      await api.post(`/api/admin/niche-requests/${req.id}/reject`)
      addToast('Solicitação rejeitada.', 'info')
      setRequests((prev) =>
        prev.map((r) => (r.id === req.id ? { ...r, status: 'rejected' } : r))
      )
    } catch (e) {
      addToast('Erro ao rejeitar solicitação.', 'error')
    } finally {
      setActionId(null)
    }
  }

  const pendingCount = requests.filter((r) => r.status === 'pending').length

  return (
    <Layout>
      <Head>
        <title>Fila de Nichos — Admin</title>
      </Head>

      <div className="p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">
              Fila de Nichos Solicitados
            </h1>
            {pendingCount > 0 && (
              <span className="text-xs font-bold px-2 py-1 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                {pendingCount} pendente{pendingCount !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <button
            onClick={fetchRequests}
            className="flex items-center gap-2 px-3 py-2 text-sm font-bold text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Atualizar
          </button>
        </div>

        {/* Table */}
        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-14 rounded-xl bg-gray-100 dark:bg-gray-700 animate-pulse" />
            ))}
          </div>
        ) : requests.length === 0 ? (
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Nenhuma solicitação pendente no momento.
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide w-[30%]">Nicho</th>
                  <th className="text-left px-4 py-3 text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide w-[15%]">Local</th>
                  <th className="text-center px-4 py-3 text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide w-[8%]">Votos</th>
                  <th className="text-left px-4 py-3 text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide w-[15%]">Usuário</th>
                  <th className="text-left px-4 py-3 text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide w-[12%]">Status</th>
                  <th className="text-left px-4 py-3 text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide w-[10%]">Data</th>
                  <th className="text-right px-4 py-3 text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide w-[10%]">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {requests.map((req) => (
                  <tr
                    key={req.id}
                    className={`bg-white dark:bg-gray-800 ${
                      req.status === 'processing' ? 'opacity-60' : ''
                    }`}
                  >
                    <td className="px-4 py-3">
                      <p className="font-bold text-gray-900 dark:text-white">{req.niche}</p>
                      {req.status === 'done' && req.leads_added != null && (
                        <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-0.5">
                          Leads adicionados: {req.leads_added}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                      {req.city && req.state
                        ? `${req.city}, ${req.state}`
                        : req.city || req.state || '—'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="font-bold text-gray-900 dark:text-white">{req.votes}</span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                      {req.requester_username}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 text-xs font-bold px-2 py-1 rounded-full ${
                          statusBadge[req.status] ?? statusBadge.pending
                        }`}
                      >
                        {req.status === 'processing' && (
                          <Loader className="w-3 h-3 animate-spin" />
                        )}
                        {statusLabel[req.status] ?? req.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">{formatDate(req.created_at)}</td>
                    <td className="px-4 py-3">
                      {req.status === 'pending' && (
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleApprove(req)}
                            disabled={actionId === req.id}
                            className="text-xs font-bold px-4 py-2 rounded-lg bg-emerald-100 text-emerald-700 hover:bg-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 disabled:opacity-50 transition-colors"
                          >
                            Aprovar
                          </button>
                          <button
                            onClick={() => handleReject(req)}
                            disabled={actionId === req.id}
                            className="text-xs font-bold px-4 py-2 rounded-lg bg-red-100 text-red-600 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400 disabled:opacity-50 transition-colors"
                          >
                            Rejeitar
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  )
}
