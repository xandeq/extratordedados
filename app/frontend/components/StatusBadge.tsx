const statusStyles: Record<string, string> = {
  pending: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  processing: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  completed: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  failed: 'bg-red-50 text-red-700 ring-red-600/20',
  novo: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  contatado: 'bg-purple-50 text-purple-700 ring-purple-600/20',
  interessado: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  negociando: 'bg-orange-50 text-orange-700 ring-orange-600/20',
  cliente: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  descartado: 'bg-gray-50 text-gray-600 ring-gray-500/20',
}

const statusLabels: Record<string, string> = {
  pending: 'Pendente',
  processing: 'Processando',
  completed: 'Concluido',
  failed: 'Falhou',
  novo: 'Novo',
  contatado: 'Contatado',
  interessado: 'Interessado',
  negociando: 'Negociando',
  cliente: 'Cliente',
  descartado: 'Descartado',
}

interface StatusBadgeProps {
  status: string
  size?: 'sm' | 'md'
}

export default function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  const style = statusStyles[status] || 'bg-gray-50 text-gray-600 ring-gray-500/20'
  const label = statusLabels[status] || status

  return (
    <span
      className={`
        inline-flex items-center rounded-full ring-1 ring-inset font-medium capitalize
        ${size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm'}
        ${style}
      `}
    >
      {label}
    </span>
  )
}
