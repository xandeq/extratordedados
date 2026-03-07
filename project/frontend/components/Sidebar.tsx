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
} from 'lucide-react'
import { useState, useEffect } from 'react'

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/scrape', label: 'Nova Extracao', icon: Search },
  { href: '/massive-search', label: 'Busca Massiva', icon: Zap },
  { href: '/leads', label: 'Leads', icon: Database },
  { href: '/app-logs', label: 'App Logs', icon: ScrollText },
]

export default function Sidebar() {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [dark, setDark] = useState(false)

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

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user_id')
    router.push('/')
  }

  const isActive = (href: string) => router.pathname.startsWith(href)

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setOpen(true)}
        className="fixed top-4 left-4 z-50 md:hidden bg-white dark:bg-gray-800 rounded-lg shadow-md p-2 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
        aria-label="Menu"
      >
        <Menu className="w-5 h-5 text-gray-600 dark:text-gray-300" />
      </button>

      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 bg-black/40 z-40 md:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed top-0 left-0 z-50 h-full w-64 bg-white border-r border-gray-200
          flex flex-col transition-transform duration-300
          md:translate-x-0 md:static md:z-auto
          ${open ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {/* Logo */}
        <div className="flex items-center justify-between px-5 py-5 border-b border-gray-100">
          <Link href="/dashboard" className="flex items-center gap-2.5 no-underline">
            <img
              src="/favicon.png"
              alt="Extrator de Dados"
              className="w-9 h-9 rounded-lg dark:invert"
            />
            <div>
              <h1 className="text-sm font-bold text-gray-900 leading-tight">Extrator</h1>
              <p className="text-[10px] text-gray-400 font-medium tracking-wide uppercase">de Dados</p>
            </div>
          </Link>
          <button
            onClick={() => setOpen(false)}
            className="md:hidden p-1 hover:bg-gray-100 rounded-lg transition-colors"
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
                onClick={() => setOpen(false)}
                className={`
                  flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium no-underline
                  transition-all duration-150
                  ${active
                    ? 'bg-primary-50 text-primary-700 shadow-sm'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  }
                `}
              >
                <Icon className={`w-[18px] h-[18px] ${active ? 'text-primary-600' : 'text-gray-400'}`} />
                {item.label}
              </Link>
            )
          })}
        </nav>

        {/* Footer */}
        <div className="px-3 py-4 border-t border-gray-100 space-y-1">
          {/* Dark mode toggle */}
          <button
            onClick={toggleDark}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all duration-150 w-full"
            title={dark ? 'Modo claro' : 'Modo escuro'}
          >
            {dark ? (
              <Sun className="w-[18px] h-[18px] text-yellow-400" />
            ) : (
              <Moon className="w-[18px] h-[18px] text-gray-400" />
            )}
            {dark ? 'Modo Claro' : 'Modo Escuro'}
          </button>
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-gray-500 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/30 dark:hover:text-red-400 transition-all duration-150 w-full"
          >
            <LogOut className="w-[18px] h-[18px]" />
            Sair
          </button>
        </div>
      </aside>
    </>
  )
}
