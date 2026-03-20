import { useState, useEffect, useCallback } from 'react'
import api from './api'

interface UsageStats {
  leads_viewed: number
  leads_exported: number
  month_year: string
}

interface PlanLimits {
  leads_per_month: number
  exports_per_month: number
  price_monthly: number
  features: Record<string, unknown>
}

interface ClientPlanData {
  plan: string
  limits: PlanLimits
  usage: UsageStats
  usage_percent: {
    leads: number
    exports: number
  }
}

interface UseClientPlanReturn {
  plan: string | null
  limits: PlanLimits | null
  usage: UsageStats | null
  loading: boolean
  error: string | null
  canViewLeads: () => boolean
  canExport: () => boolean
  refetch: () => Promise<void>
}

export const useClientPlan = (): UseClientPlanReturn => {
  const [data, setData] = useState<ClientPlanData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchPlan = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await api.get('/api/client/usage')
      setData(response.data)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to fetch plan info'
      setError(message)
      console.error('Error fetching plan:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPlan()
    // Refresh plan data every 5 minutes
    const interval = setInterval(fetchPlan, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchPlan])

  const canViewLeads = useCallback((): boolean => {
    if (!data || !data.limits) return true
    // Enterprise plans can always view
    if (data.plan === 'enterprise') return true
    return data.usage.leads_viewed < data.limits.leads_per_month
  }, [data])

  const canExport = useCallback((): boolean => {
    if (!data || !data.limits) return true
    // Enterprise plans can always export
    if (data.plan === 'enterprise') return true
    return data.usage.leads_exported < data.limits.exports_per_month
  }, [data])

  return {
    plan: data?.plan ?? null,
    limits: data?.limits ?? null,
    usage: data?.usage ?? null,
    loading,
    error,
    canViewLeads,
    canExport,
    refetch: fetchPlan,
  }
}
