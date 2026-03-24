import Link from 'next/link'
import { useRouter } from 'next/router'
import {
  LayoutDashboard,
  Search,
  Database,
  FileDown,
  LogOut,
  Menu,
  X,
  Moon,
  Sun,
  Zap,
  ScrollText,
  Users,
  Settings,
  TrendingUp,
  Shield,
  BookMarked,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import api from '../lib/api'
import { useClientCredits } from '../lib/useClientCredits'

const clientNavItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/portal', label: 'Portal de Leads', icon: BookMarked },
  { href: '/leads', label: 'Leads', icon: Database },
  { href: '/plans', label: 'Planos', icon: Zap },
]

const adminNavItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/admin', label: 'Painel Admin', icon: Shield },
  { href: '/admin/massive-search', label: 'Alimentar Base', icon: Zap },
  { href: '/leads', label: 'Leads Database', icon: Database },
  { href: '/admin/users', label: 'Usuários', icon: Users },
  { href: '/admin/plans', label: 'Planos & Limites', icon: Settings },
  { href: '/app-logs', label: 'System Logs', icon: ScrollText },
]

interface SidebarProps {
  isOpen?: boolean
  onClose?: () => void
}

interface UsageData {
  plan: string
  limits: { leads_per_month: number; exports_per_month: number }
  usage: { leads_viewed: number; leads_exported: number }
}

function UsageMeter({ plan, usage, limits }: UsageData) {
  const isUnlimited = (v: number) => v >= 999999
  const pctLeads = isUnlimited(limits.leads_per_month) ? 0 : Math.min(100, (usage.leads_viewed / limits.leads_per_month) * 100)
  const pctExports = isUnlimited(limits.exports_per_month) ? 0 : Math.min(100, (usage.leads_exported / limits.exports_per_month) * 100)
  const planLabel: Record<string, string> = { free: 'Free', pro: 'Pro', enterprise: 'Enterprise' }
  const planColor: Record<string, string> = {
    free: 'text-gray-500 dark:text-gray-400',
    pro: 'text-blue-600 dark:text-blue-400',
    enterprise: 'text-purple-600 dark:text-purple-400',
  }
  const barColor = (pct: number) =>
    pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-yellow-500' : 'bg-blue-500'

  return (
    <div className="px-3 pb-3">
      <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-3 space-y-2.5 bg-gray-50 dark:bg-gray-700/30">
        <div className="flex items-center justify-between">
          <span className={`text-xs font-semibold uppercase tracking-wide ${planColor[plan] ?? planColor.free}`}>
            Plano {planLabel[plan] ?? plan}
          </span>
          {plan === 'free' && (
            <Link
              href="/plans"
              className="text-[10px] font-semibold text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-0.5"
            >
              <Zap className="w-2.5 h-2.5" />
              Upgrade
            </Link>
          )}
        </div>

        {/* Leads */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-500 dark:text-gray-400 flex items-center gap-1">
              <TrendingUp className="w-3 h-3" />
              Leads
            </span>
            <span className="font-medium text-gray-700 dark:text-gray-300 tabular-nums">
              {isUnlimited(limits.leads_per_month) ? '∞' : `${usage.leads_viewed}/${limits.leads_per_month}`}
            </span>
          </div>
          {!isUnlimited(limits.leads_per_month) && (
            <div className="h-1 rounded-full bg-gray-200 dark:bg-gray-600 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${barColor(pctLeads)}`}
                style={{ width: `${pctLeads}%` }}
              />
            </div>
          )}
        </div>

        {/* Exports */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-500 dark:text-gray-400">Exportações</span>
            <span className="font-medium text-gray-700 dark:text-gray-300 tabular-nums">
              {isUnlimited(limits.exports_per_month) ? '∞' : `${usage.leads_exported}/${limits.exports_per_month}`}
            </span>
          </div>
          {!isUnlimited(limits.exports_per_month) && (
            <div className="h-1 rounded-full bg-gray-200 dark:bg-gray-600 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${barColor(pctExports)}`}
                style={{ width: `${pctExports}%` }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Sidebar({ isOpen = true, onClose }: SidebarProps) {
  const router = useRouter()
  const [sidebarOpen, setSidebarOpen] = useState(isOpen)
  const [dark, setDark] = useState(false)
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)
  const [usageData, setUsageData] = useState<UsageData | null>(null)
  const { balance: creditBalance, loading: creditsLoading } = useClientCredits()

  useEffect(() => {
    setSidebarOpen(isOpen)
  }, [isOpen])

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const response = await api.get('/api/me')
        setIsAdmin(response.data.is_admin)
        if (!response.data.is_admin) {
          try {
            const usageRes = await api.get('/api/client/usage')
            setUsageData(usageRes.data)
          } catch {
            // silently fail
          }
        }
      } catch (error) {
        console.error('Failed to fetch user:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchUser()
  }, [])

  useEffect(() => {
    const saved = localStorage.getItem('theme')
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    const isDark = saved === 'dark' || (!saved && prefersDark)
    setDark(isDark)
    if (isDark) document.documentElement.classList.add('dark')
  }, [])

  const toggleDark = () => {
    const html = document.documentElement
    html.classList.add('transitioning')
    const next = !dark
    setDark(next)
    if (next) {
      html.classList.add('dark')
      localStorage.setItem('theme', 'dark')
    } else {
      html.classList.remove('dark')
      localStorage.setItem('theme', 'light')
    }
    setTimeout(() => html.classList.remove('transitioning'), 350)
  }

  const isActive = (href: string) => {
    // exact match for root-like admin pages to avoid /admin matching /admin/users
    if (href === '/admin' || href === '/dashboard' || href === '/leads' || href === '/plans' || href === '/portal') {
      return router.pathname === href
    }
    return router.pathname.startsWith(href)
  }

  const navItems = isAdmin ? adminNavItems : clientNavItems

  const handleClose = () => {
    setSidebarOpen(false)
    onClose?.()
  }

  return (
    <>
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40 md:hidden"
          onClick={handleClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed top-0 left-0 z-50 h-full w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700
          flex flex-col transition-transform duration-300
          md:translate-x-0 md:static md:z-auto
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {/* Logo */}
        <div className="flex items-center justify-between px-5 py-5 border-b border-gray-100 dark:border-gray-700">
          <Link href="/dashboard" className="flex items-center gap-2.5 no-underline">
            <img
              src="/favicon.png"
              alt="Extrator de Dados"
              className="w-9 h-9 rounded-lg dark:invert"
            />
            <div>
              <h1 className="text-sm font-bold text-gray-900 dark:text-white leading-tight">Extrator</h1>
              <p className="text-[10px] text-gray-400 dark:text-gray-500 font-medium tracking-wide uppercase">
                {isAdmin ? 'Admin' : 'Client'}
              </p>
            </div>
          </Link>
          <button
            onClick={handleClose}
            className="md:hidden p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
          >
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon
            const active = isActive(item.href)
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={handleClose}
                className={`
                  flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium no-underline
                  transition-all duration-150
                  ${active
                    ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 shadow-sm'
                    : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-gray-300'
                  }
                `}
              >
                <Icon className={`w-[18px] h-[18px] ${active ? 'text-blue-600 dark:text-blue-300' : 'text-gray-400 dark:text-gray-500'}`} />
                {item.label}
              </Link>
            )
          })}
        </nav>

        {/* Usage Meter (clients only) */}
        {!isAdmin && !loading && usageData && (
          <UsageMeter
            plan={usageData.plan}
            usage={usageData.usage}
            limits={usageData.limits}
          />
        )}

        {/* Credit Balance (clients only) */}
        {!isAdmin && !loading && creditBalance !== null && (
          <div className="px-3 pb-3">
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-3 space-y-2 bg-gray-50 dark:bg-gray-700/30">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Créditos disponíveis
                </span>
                <Zap className="w-3 h-3 text-blue-500" />
              </div>
              <div>
                <span
                  className="text-xl font-bold text-blue-600 dark:text-blue-400 tabular-nums"
                  aria-live="polite"
                >
                  {creditBalance}
                </span>
                <span className="text-xs text-gray-500 dark:text-gray-400 ml-1">créditos</span>
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="px-3 py-4 border-t border-gray-100 dark:border-gray-700 space-y-1">
          {/* Dark mode toggle */}
          <button
            onClick={toggleDark}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all duration-150 w-full"
            title={dark ? 'Modo claro' : 'Modo escuro'}
          >
            {dark ? (
              <Sun className="w-[18px] h-[18px] text-yellow-400" />
            ) : (
              <Moon className="w-[18px] h-[18px] text-gray-400" />
            )}
            {dark ? 'Claro' : 'Escuro'}
          </button>
        </div>
      </aside>
    </>
  )
}
