import { useState, useEffect } from 'react'
import { Check, Zap, Mail, Loader2, AlertCircle } from 'lucide-react'
import api from '../lib/api'

interface PlanTier {
  name: string
  label: string
  price: string
  priceNote: string
  badge: string
  badgeColor: string
  cardBg: string
  cardBorder: string
  highlighted: boolean
  leads: string
  exports: string
  savedFilters: string
  credits: string
  features: string[]
  cta: string
  ctaStyle: string
  stripeEnabled?: boolean
}

const PLANS: PlanTier[] = [
  {
    name: 'free',
    label: 'Free',
    price: 'R$0',
    priceNote: 'para sempre',
    badge: 'Grátis',
    badgeColor: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
    cardBg: 'bg-white dark:bg-gray-800',
    cardBorder: 'border-gray-200 dark:border-gray-700',
    highlighted: false,
    leads: '100',
    exports: '1',
    savedFilters: '0',
    credits: '10',
    features: [
      'Acesso à base de leads',
      'Filtros básicos',
      '10 reveals/mês',
    ],
    cta: 'Plano atual',
    ctaStyle: 'border border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 cursor-default',
  },
  {
    name: 'pro',
    label: 'Pro',
    price: 'R$99',
    priceNote: 'por mês',
    badge: 'Recomendado',
    badgeColor: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
    cardBg: 'bg-blue-50 dark:bg-blue-900/10',
    cardBorder: 'border-blue-400 dark:border-blue-600',
    highlighted: true,
    leads: '5.000',
    exports: '20',
    savedFilters: '5',
    credits: '200',
    features: [
      'Tudo do plano Free',
      'Filtros salvos (5)',
      'Exportações ilimitadas por dia',
      '200 reveals/mês',
      'Suporte prioritário',
    ],
    cta: 'Contratar Pro',
    ctaStyle: 'bg-blue-600 hover:bg-blue-700 text-white shadow-sm',
  },
  {
    name: 'enterprise',
    label: 'Enterprise',
    price: 'Sob consulta',
    priceNote: '',
    badge: 'Enterprise',
    badgeColor: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
    cardBg: 'bg-white dark:bg-gray-800',
    cardBorder: 'border-purple-200 dark:border-purple-800',
    highlighted: false,
    leads: '∞',
    exports: '∞',
    savedFilters: '20',
    credits: '∞',
    features: [
      'Tudo do plano Pro',
      'Filtros salvos ilimitados',
      'Reveals ilimitados',
      'Acesso à API',
      'SLA dedicado',
      'Onboarding personalizado',
    ],
    cta: 'Falar com vendas',
    ctaStyle: 'border border-purple-400 text-purple-700 dark:text-purple-300 hover:bg-purple-50 dark:hover:bg-purple-900/20',
  },
]

function FeatureRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm py-2 border-b border-gray-100 dark:border-gray-700/50 last:border-0">
      <span className="text-gray-600 dark:text-gray-400">{label}</span>
      <span className="font-semibold text-gray-900 dark:text-white">{value}</span>
    </div>
  )
}

export default function Plans() {
  const [stripeEnabled, setStripeEnabled] = useState(false)
  const [loading, setLoading] = useState<string | null>(null)
  const [flashMsg, setFlashMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    // Show success/cancel flash based on URL params
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search)
      if (params.get('success') === '1') {
        setFlashMsg({ type: 'success', text: '🎉 Pagamento confirmado! Seu plano Pro está ativo.' })
        window.history.replaceState({}, '', '/plans')
      } else if (params.get('canceled') === '1') {
        setFlashMsg({ type: 'error', text: 'Pagamento cancelado. Você pode tentar novamente quando quiser.' })
        window.history.replaceState({}, '', '/plans')
      }
    }
    // Check if Stripe is configured on the backend
    api.get('/api/stripe/config')
      .then(r => setStripeEnabled(r.data?.enabled ?? false))
      .catch(() => setStripeEnabled(false))
  }, [])

  const handleProCheckout = async () => {
    if (stripeEnabled) {
      setLoading('pro')
      try {
        const r = await api.post('/api/stripe/create-checkout-session', { plan: 'pro' })
        if (r.data?.url) {
          window.location.href = r.data.url
        }
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error || 'Erro ao iniciar checkout'
        setFlashMsg({ type: 'error', text: msg })
        setLoading(null)
      }
    } else {
      // Fallback: open email
      window.location.href = 'mailto:contato@extratordedados.com.br?subject=Upgrade%20para%20Pro'
    }
  }

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Flash messages */}
      {flashMsg && (
        <div className={`max-w-2xl mx-auto flex items-start gap-3 p-4 rounded-xl border text-sm font-medium
          ${flashMsg.type === 'success'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-900/20 dark:border-emerald-800 dark:text-emerald-300'
            : 'bg-red-50 border-red-200 text-red-800 dark:bg-red-900/20 dark:border-red-800 dark:text-red-300'
          }`}>
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{flashMsg.text}</span>
          <button onClick={() => setFlashMsg(null)} className="ml-auto opacity-60 hover:opacity-100">✕</button>
        </div>
      )}

      {/* Header */}
      <div className="text-center max-w-xl mx-auto">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800 mb-4">
          <Zap className="w-3.5 h-3.5 text-blue-600" />
          <span className="text-xs font-semibold text-blue-700 dark:text-blue-300 uppercase tracking-wide">Planos & Preços</span>
        </div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-3">
          Escolha seu plano
        </h1>
        <p className="text-gray-500 dark:text-gray-400 text-sm leading-relaxed">
          Acesse a base de leads qualificados, filtre por nicho e cidade, e exporte para suas ferramentas de marketing.
        </p>
      </div>

      {/* Plan Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-4xl mx-auto">
        {PLANS.map((plan) => (
          <div
            key={plan.name}
            className={`rounded-2xl border-2 p-6 flex flex-col gap-5 relative transition-shadow ${plan.cardBg} ${plan.cardBorder} ${plan.highlighted ? 'shadow-lg shadow-blue-100 dark:shadow-blue-900/30' : ''}`}
          >
            {plan.highlighted && (
              <div className="absolute -top-3.5 left-1/2 -translate-x-1/2">
                <span className="text-[11px] font-bold px-3 py-1 rounded-full bg-blue-600 text-white uppercase tracking-wide shadow-sm">
                  Mais popular
                </span>
              </div>
            )}

            {/* Plan name + price */}
            <div>
              <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${plan.badgeColor}`}>
                {plan.badge}
              </span>
              <div className="mt-3 flex items-baseline gap-1.5">
                <span className="text-2xl font-bold text-gray-900 dark:text-white">{plan.price}</span>
                {plan.priceNote && (
                  <span className="text-sm text-gray-500 dark:text-gray-400">{plan.priceNote}</span>
                )}
              </div>
            </div>

            {/* Usage limits */}
            <div className="space-y-0">
              <FeatureRow label="Créditos de reveal / mês" value={plan.credits} />
              <FeatureRow label="Leads / mês" value={plan.leads} />
              <FeatureRow label="Exportações / mês" value={plan.exports} />
              <FeatureRow label="Filtros salvos" value={plan.savedFilters} />
            </div>

            {/* Features list */}
            <ul className="space-y-2 flex-1">
              {plan.features.map((f) => (
                <li key={f} className="flex items-start gap-2 text-sm text-gray-600 dark:text-gray-300">
                  <Check className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                  {f}
                </li>
              ))}
            </ul>

            {/* CTA */}
            {plan.name === 'free' && (
              <div className={`flex items-center justify-center w-full py-3 rounded-xl text-sm ${plan.ctaStyle}`}>
                {plan.cta}
              </div>
            )}

            {plan.name === 'pro' && (
              <button
                onClick={handleProCheckout}
                disabled={loading === 'pro'}
                className={`flex items-center justify-center gap-2 w-full py-3 rounded-xl font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${plan.ctaStyle}`}
              >
                {loading === 'pro' ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Aguarde...</>
                ) : stripeEnabled ? (
                  <>{plan.cta} →</>
                ) : (
                  <><Mail className="w-4 h-4" /> {plan.cta}</>
                )}
              </button>
            )}

            {plan.name === 'enterprise' && (
              <a
                href="mailto:contato@extratordedados.com.br?subject=Plano%20Enterprise"
                className={`flex items-center justify-center gap-2 w-full py-3 rounded-xl font-semibold text-sm transition-colors ${plan.ctaStyle}`}
              >
                <Mail className="w-4 h-4" />
                {plan.cta}
              </a>
            )}
          </div>
        ))}
      </div>

      {/* Payment methods note */}
      <div className="text-center space-y-1">
        <p className="text-xs text-gray-400 dark:text-gray-500">
          {stripeEnabled
            ? 'Pagamento seguro via Stripe — cartão de crédito, débito ou PIX.'
            : 'Pagamentos por PIX, cartão ou boleto. Entre em contato para contratar.'}
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500">
          Cancelamento a qualquer momento.{' '}
          <a href="mailto:contato@extratordedados.com.br" className="underline hover:text-gray-600">
            contato@extratordedados.com.br
          </a>
        </p>
      </div>
    </div>
  )
}
