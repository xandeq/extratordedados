import { useState, useRef, useEffect } from 'react'
import { HelpCircle } from 'lucide-react'

interface TooltipProps {
  text: string
  position?: 'top' | 'bottom' | 'left' | 'right'
  size?: 'sm' | 'md'
}

export default function Tooltip({ text, position = 'top', size = 'sm' }: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setVisible(false)
      }
    }
    if (visible) document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [visible])

  const positionClasses: Record<string, string> = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  }

  const arrowClasses: Record<string, string> = {
    top: 'top-full left-1/2 -translate-x-1/2 border-t-gray-800 dark:border-t-gray-700 border-l-transparent border-r-transparent border-b-transparent',
    bottom: 'bottom-full left-1/2 -translate-x-1/2 border-b-gray-800 dark:border-b-gray-700 border-l-transparent border-r-transparent border-t-transparent',
    left: 'left-full top-1/2 -translate-y-1/2 border-l-gray-800 dark:border-l-gray-700 border-t-transparent border-b-transparent border-r-transparent',
    right: 'right-full top-1/2 -translate-y-1/2 border-r-gray-800 dark:border-r-gray-700 border-t-transparent border-b-transparent border-l-transparent',
  }

  const iconSize = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'

  return (
    <div ref={ref} className="relative inline-flex items-center">
      <button
        type="button"
        className="text-gray-400 hover:text-primary-500 dark:text-gray-500 dark:hover:text-primary-400 transition-colors focus:outline-none"
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        onClick={() => setVisible(v => !v)}
        aria-label="Ajuda"
      >
        <HelpCircle className={iconSize} />
      </button>

      {visible && (
        <div className={`absolute z-50 ${positionClasses[position]}`}>
          <div className="relative bg-gray-800 dark:bg-gray-700 text-white text-xs rounded-lg px-3 py-2 shadow-xl w-56 leading-relaxed">
            {text}
            <span
              className={`absolute border-4 ${arrowClasses[position]}`}
              style={{ borderWidth: 5 }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
