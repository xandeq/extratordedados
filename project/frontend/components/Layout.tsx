import { useRouter } from 'next/router'
import { useEffect } from 'react'
import Sidebar from './Sidebar'
import { motion, AnimatePresence } from 'framer-motion'

const noLayoutPages = ['/login', '/']

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter()

  // Global keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'

      // Esc -> close modals/drawers (dispatch custom event)
      if (e.key === 'Escape') {
        window.dispatchEvent(new CustomEvent('app:close-modal'))
        return
      }

      // Only trigger shortcut keys when not focused on inputs
      if (isInput) return

      // "/" -> focus search input
      if (e.key === '/') {
        e.preventDefault()
        const searchInput = document.querySelector<HTMLInputElement>('input[placeholder*="Buscar"]')
        if (searchInput) searchInput.focus()
      }

      // "n" -> go to Nova Extracao
      if (e.key === 'n' || e.key === 'N') {
        e.preventDefault()
        router.push('/scrape')
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [router])

  if (noLayoutPages.includes(router.pathname)) {
    return (
      <AnimatePresence mode="wait">
        <motion.div
          key={router.pathname}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={router.pathname}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.2 }}
            className="p-4 md:p-8 max-w-[1400px] mx-auto"
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  )
}
