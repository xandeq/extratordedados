import { useState, useEffect, useCallback } from 'react'
import api from './api'

interface CreditEvent {
  amount: number
  operation: string
  ref_id: number | null
  balance_after: number
  created_at: string
}

interface UseClientCreditsReturn {
  balance: number | null
  history: CreditEvent[]
  loading: boolean
  refetch: () => Promise<void>
}

export function useClientCredits(): UseClientCreditsReturn {
  const [balance, setBalance] = useState<number | null>(null)
  const [history, setHistory] = useState<CreditEvent[]>([])
  const [loading, setLoading] = useState(true)

  const fetchCredits = useCallback(async () => {
    try {
      const res = await api.get('/api/client/credits')
      setBalance(res.data.balance)
      setHistory(res.data.history)
    } catch {
      // silently fail — balance stays null, widget hidden
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCredits()
  }, [fetchCredits])

  return { balance, history, loading, refetch: fetchCredits }
}
