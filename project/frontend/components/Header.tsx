import React, { useEffect, useState } from 'react'
import { useRouter } from 'next/router'
import { Menu, X } from 'lucide-react'
import { UserMenu } from './UserMenu'
import api from '../lib/api'

interface User {
  id: number
  username: string
  is_admin: boolean
}

interface HeaderProps {
  onSidebarToggle?: () => void
}

export const Header: React.FC<HeaderProps> = ({ onSidebarToggle }) => {
  const router = useRouter()
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const response = await api.get('/api/me')
        setUser(response.data)
      } catch (error) {
        console.error('Failed to fetch user:', error)
        // If unauthorized, redirect to login
        if ((error as any)?.response?.status === 401) {
          router.push('/login')
        }
      } finally {
        setLoading(false)
      }
    }

    fetchUser()
  }, [router])

  const handleLogout = () => {
    localStorage.removeItem('token')
    router.push('/login')
  }

  const handleUpgrade = () => {
    // TODO: Implement upgrade flow
    alert('Upgrade flow coming soon!')
  }

  if (loading || !user) {
    return (
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-3">
        <div className="max-w-7xl mx-auto flex justify-between items-center">
          <div className="h-8 w-20 bg-gray-200 dark:bg-gray-700 rounded animate-pulse" />
          <div className="h-8 w-32 bg-gray-200 dark:bg-gray-700 rounded animate-pulse" />
        </div>
      </header>
    )
  }

  return (
    <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 sticky top-0 z-40">
      <div className="px-4 py-3 md:px-8">
        <div className="flex justify-between items-center">
          {/* Left: Menu toggle + Logo */}
          <div className="flex items-center gap-4">
            <button
              onClick={onSidebarToggle}
              className="md:hidden p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
            >
              <Menu className="w-5 h-5 text-gray-700 dark:text-gray-300" />
            </button>
            <div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white">
                {user.is_admin ? '⚙️ Painel Admin' : '📊 Dashboard'}
              </h1>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {user.is_admin ? 'Gerenciamento de usuários e planos' : 'Seus leads e analíticos'}
              </p>
            </div>
          </div>

          {/* Right: User Menu */}
          <UserMenu
            username={user.username}
            isAdmin={user.is_admin}
            onLogout={handleLogout}
            onUpgrade={handleUpgrade}
          />
        </div>
      </div>
    </header>
  )
}
