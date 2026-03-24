import { Lock, Unlock, RefreshCw } from 'lucide-react'

interface RevealButtonProps {
  leadId: number
  revealed: boolean
  balance: number | null
  onReveal: (leadId: number) => Promise<void>
  loading?: boolean
}

export function RevealButton({ leadId, revealed, balance, onReveal, loading = false }: RevealButtonProps) {
  const hasCredits = balance === null || balance > 0  // null = unknown/admin, treat as ok

  if (revealed) {
    return (
      <button
        disabled
        className="flex items-center gap-1.5 py-2 px-3 rounded-lg text-xs font-semibold border border-emerald-500 text-emerald-500 bg-transparent cursor-default transition-colors duration-150"
        aria-label="Contato já revelado"
      >
        <Unlock className="w-4 h-4" />
        Revelado
      </button>
    )
  }

  if (loading) {
    return (
      <button
        disabled
        className="flex items-center gap-1.5 py-2 px-3 rounded-lg text-xs font-semibold bg-blue-600 text-white cursor-not-allowed transition-colors duration-150"
        aria-busy="true"
        aria-label="Revelando contato"
      >
        <RefreshCw className="w-4 h-4 animate-spin" />
        Revelando...
      </button>
    )
  }

  if (!hasCredits) {
    return (
      <button
        disabled
        className="flex items-center gap-1.5 py-2 px-3 rounded-lg text-xs font-semibold border border-red-500 text-red-500 bg-transparent cursor-not-allowed transition-colors duration-150"
        title="Você não tem créditos. Faça upgrade do seu plano."
        aria-label="Sem créditos disponíveis"
      >
        <Lock className="w-4 h-4" />
        Sem créditos
      </button>
    )
  }

  return (
    <button
      onClick={() => onReveal(leadId)}
      className="flex items-center gap-1.5 py-2 px-3 rounded-lg text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white transition-colors duration-150"
      title="Revelar consumirá 1 crédito do seu plano"
      aria-label="Revelar contato — consumirá 1 crédito"
    >
      <Lock className="w-4 h-4" />
      Revelar — 1 crédito
    </button>
  )
}
