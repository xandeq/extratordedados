import { useState, useEffect } from 'react'
import Head from 'next/head'
import { MessageSquarePlus, ThumbsUp, Loader } from 'lucide-react'
import api from '../lib/api'
import { useToast } from '../components/Toast'
import Layout from '../components/Layout'

interface NicheRequest {
  id: number
  niche: string
  city: string | null
  state: string | null
  votes: number
  status: string
  user_voted: boolean
  requester_username: string
  leads_added: number | null
}

export default function RequestNiche() {
  const { addToast } = useToast()

  // Form state
  const [niche, setNiche] = useState('')
  const [city, setCity] = useState('')
  const [stateVal, setStateVal] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [nicheError, setNicheError] = useState(false)

  // Vote list state
  const [requests, setRequests] = useState<NicheRequest[]>([])
  const [loadingList, setLoadingList] = useState(true)
  const [votingId, setVotingId] = useState<number | null>(null)

  const fetchRequests = async () => {
    try {
      const resp = await api.get('/api/client/niche-requests')
      setRequests(resp.data.requests || [])
    } catch (e) {
      console.error('Failed to fetch niche requests', e)
    } finally {
      setLoadingList(false)
    }
  }

  useEffect(() => {
    fetchRequests()
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!niche.trim()) {
      setNicheError(true)
      return
    }
    setNicheError(false)
    setSubmitting(true)
    try {
      const resp = await api.post('/api/client/niche-requests', {
        niche: niche.trim(),
        city: city.trim() || undefined,
        state: stateVal.trim().toUpperCase() || undefined,
        notes: notes.trim() || undefined,
      })
      if (resp.data.action === 'voted') {
        addToast('Seu voto foi registrado!', 'success')
      } else {
        setSubmitted(true)
      }
      setNiche('')
      setCity('')
      setStateVal('')
      setNotes('')
      fetchRequests()
    } catch (e: any) {
      const status = e.response?.status
      if (status === 409) {
        addToast('Você já votou nesta solicitação.', 'info')
      } else {
        addToast('Erro ao enviar solicitação. Tente novamente.', 'error')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleVote = async (reqId: number) => {
    setVotingId(reqId)
    try {
      const target = requests.find((r) => r.id === reqId)
      if (!target) return
      const resp = await api.post('/api/client/niche-requests', {
        niche: target.niche,
        city: target.city,
        state: target.state,
      })
      if (resp.data.action === 'voted') {
        addToast('Seu voto foi registrado!', 'success')
      }
      setRequests((prev) =>
        prev.map((r) =>
          r.id === reqId ? { ...r, votes: r.votes + 1, user_voted: true } : r
        )
      )
    } catch (e: any) {
      const status = e.response?.status
      if (status === 409) {
        // Already voted — update local state silently
        setRequests((prev) =>
          prev.map((r) => (r.id === reqId ? { ...r, user_voted: true } : r))
        )
      } else {
        addToast('Erro ao votar. Tente novamente.', 'error')
      }
    } finally {
      setVotingId(null)
    }
  }

  const statusLabel: Record<string, string> = {
    pending: 'Aguardando',
    approved: 'Aprovado',
    processing: 'Processando...',
    done: 'Concluído',
    rejected: 'Rejeitado',
  }

  return (
    <Layout>
      <Head>
        <title>Solicitar Nicho — Extrator de Dados</title>
      </Head>

      <div className="max-w-2xl mx-auto px-4 py-8 space-y-8">
        {/* Form card */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-6">
          <div className="flex items-center gap-3 mb-1">
            <MessageSquarePlus className="w-5 h-5 text-blue-600" />
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">Solicitar Novo Nicho</h1>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
            Peça leads de um segmento que ainda não temos. Quanto mais votos, mais rápido adicionamos.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wide mb-1">
                Segmento <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={niche}
                onChange={(e) => { setNiche(e.target.value); setNicheError(false) }}
                placeholder="Ex: Clínica Veterinária, Academia de Ginástica..."
                className={`w-full px-3 py-2 rounded-lg border text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors ${
                  nicheError
                    ? 'border-red-500 focus:ring-red-500'
                    : 'border-gray-200 dark:border-gray-600'
                }`}
              />
              {nicheError && (
                <p className="text-xs text-red-500 mt-1">Segmento é obrigatório.</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wide mb-1">
                  Cidade
                </label>
                <input
                  type="text"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  placeholder="Ex: Vitória"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wide mb-1">
                  Estado (UF)
                </label>
                <input
                  type="text"
                  value={stateVal}
                  onChange={(e) => setStateVal(e.target.value.slice(0, 2).toUpperCase())}
                  placeholder="Ex: ES"
                  maxLength={2}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wide mb-1">
                Observações
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                placeholder="Detalhes adicionais sobre o nicho ou região..."
                className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors resize-none"
              />
            </div>

            {submitted ? (
              <p className="text-sm text-emerald-600 dark:text-emerald-400 font-bold py-2">
                Solicitação enviada! Agora você pode votar em outras solicitações abaixo.
              </p>
            ) : (
              <button
                type="submit"
                disabled={submitting}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-bold rounded-lg transition-colors"
              >
                {submitting ? (
                  <>
                    <Loader className="w-4 h-4 animate-spin" />
                    Enviando...
                  </>
                ) : (
                  <>
                    <MessageSquarePlus className="w-4 h-4" />
                    Solicitar Nicho
                  </>
                )}
              </button>
            )}
          </form>
        </div>

        {/* Vote list */}
        <div>
          <h2 className="text-base font-bold text-gray-900 dark:text-white mb-1">
            Solicitações Populares
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Vote nos nichos que você também quer ver na base.
          </p>

          {loadingList ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-16 rounded-xl bg-gray-100 dark:bg-gray-700 animate-pulse" />
              ))}
            </div>
          ) : requests.length === 0 ? (
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-8 text-center">
              <MessageSquarePlus className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Nenhuma solicitação ainda. Seja o primeiro a pedir um nicho novo!
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {requests.map((req) => (
                <div
                  key={req.id}
                  className="flex items-center justify-between rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-3"
                >
                  <div className="flex-1 min-w-0 mr-4">
                    <p className="text-sm font-bold text-gray-900 dark:text-white truncate">{req.niche}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {req.city && req.state
                        ? `${req.city}, ${req.state}`
                        : req.city || req.state || '—'}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <div className="text-right">
                      <span className="text-sm font-bold text-gray-700 dark:text-gray-300">
                        {req.votes}
                      </span>
                      <span className="text-xs text-gray-400 ml-1">votos</span>
                    </div>
                    {req.status === 'pending' || req.status === 'approved' ? (
                      <button
                        onClick={() => handleVote(req.id)}
                        disabled={req.user_voted || votingId === req.id}
                        className={`flex items-center gap-1 text-sm font-bold px-4 py-2 rounded-lg transition-colors ${
                          req.user_voted
                            ? 'bg-blue-600 text-white cursor-default'
                            : 'border border-blue-600 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20'
                        }`}
                      >
                        {votingId === req.id ? (
                          <Loader className="w-3 h-3 animate-spin" />
                        ) : (
                          <ThumbsUp className="w-3 h-3" />
                        )}
                        Votar
                      </button>
                    ) : (
                      <span className="text-xs text-gray-400">{statusLabel[req.status] ?? req.status}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Layout>
  )
}
