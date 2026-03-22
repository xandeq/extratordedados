import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Link from 'next/link'
import { Zap, Mail, Search, FileDown, Database, ArrowRight, BarChart3, Globe } from 'lucide-react'

const features = [
  { icon: Search, title: 'Deep Crawl', desc: 'Visita paginas de contato, sobre e sitemap automaticamente' },
  { icon: Mail, title: 'Extracao de Emails', desc: 'Encontra emails em todas as paginas do site' },
  { icon: Database, title: 'Leads Completos', desc: 'Extrai telefone, empresa, redes sociais e CNPJ' },
  { icon: Globe, title: 'Lotes de URLs', desc: 'Processe ate 500 URLs de uma vez em background' },
  { icon: BarChart3, title: 'Dashboard Analytics', desc: 'Graficos e metricas dos seus leads extraidos' },
  { icon: FileDown, title: 'Export CRM', desc: 'CSV, JSON, Mailchimp, WhatsApp e vCard' },
]

export default function Home() {
  const router = useRouter()
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('token')
    setIsLoggedIn(!!token)
    setLoading(false)
  }, [])

  if (loading) return null

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-900 to-primary-950">
      {/* Decorative */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[600px] bg-primary-500/5 rounded-full blur-3xl" />
      </div>

      {/* Header */}
      <header className="relative flex items-center justify-between max-w-6xl mx-auto px-6 py-6">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 bg-gradient-to-br from-primary-400 to-primary-600 rounded-xl flex items-center justify-center">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <span className="text-lg font-bold text-white">Extrator de Dados</span>
        </div>
        <Link href={isLoggedIn ? '/dashboard' : '/login'}>
          <button className="px-5 py-2 bg-white/10 hover:bg-white/15 text-white text-sm font-medium rounded-lg border border-white/10 transition-all">
            {isLoggedIn ? 'Dashboard' : 'Entrar'}
          </button>
        </Link>
      </header>

      {/* Hero */}
      <section className="relative max-w-6xl mx-auto px-6 pt-16 pb-24 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-primary-500/10 border border-primary-500/20 rounded-full text-primary-300 text-xs font-medium mb-6">
          <Zap className="w-3 h-3" />
          Extracao automatica de leads
        </div>

        <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold text-white leading-tight mb-5">
          Extraia leads de<br />
          <span className="bg-gradient-to-r from-primary-400 to-blue-400 bg-clip-text text-transparent">
            qualquer website
          </span>
        </h1>

        <p className="text-lg text-slate-400 max-w-2xl mx-auto mb-10">
          Cole uma lista de URLs e receba emails, telefones, nomes de empresa, redes sociais e mais.
          Pronto para importar no seu CRM ou ferramenta de marketing.
        </p>

        <div className="flex items-center justify-center gap-4 flex-wrap">
          <Link href={isLoggedIn ? '/scrape' : '/login'}>
            <button className="px-6 py-3 bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-600 hover:to-primary-700 text-white font-semibold rounded-xl shadow-lg shadow-primary-500/25 transition-all flex items-center gap-2">
              Comecar Extracao
              <ArrowRight className="w-4 h-4" />
            </button>
          </Link>
          {isLoggedIn && (
            <Link href="/dashboard">
              <button className="px-6 py-3 bg-white/5 hover:bg-white/10 text-white font-medium rounded-xl border border-white/10 transition-all">
                Ir para Dashboard
              </button>
            </Link>
          )}
        </div>
      </section>

      {/* Features */}
      <section className="relative max-w-6xl mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {features.map((f, i) => (
            <div
              key={i}
              className="group bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] hover:border-white/10 rounded-2xl p-6 transition-all duration-300"
            >
              <div className="w-10 h-10 bg-primary-500/10 rounded-xl flex items-center justify-center mb-4 group-hover:bg-primary-500/15 transition-colors">
                <f.icon className="w-5 h-5 text-primary-400" />
              </div>
              <h3 className="text-base font-semibold text-white mb-1.5">{f.title}</h3>
              <p className="text-sm text-slate-400 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="relative border-t border-white/5 py-8 text-center">
        <p className="text-xs text-slate-600">Extrator de Dados &copy; {new Date().getFullYear()}</p>
      </footer>
    </div>
  )
}
