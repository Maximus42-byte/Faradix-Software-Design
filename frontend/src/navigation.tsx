import { createContext, useContext, useEffect, useState } from 'react'
import type { MouseEvent, ReactNode } from 'react'

type Navigation = { path: string; navigate: (path: string) => void }
const NavigationContext = createContext<Navigation | null>(null)

export function NavigationProvider({ children }: { children: ReactNode }) {
  const [path, setPath] = useState(window.location.pathname)

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = (nextPath: string) => {
    if (nextPath !== window.location.pathname) window.history.pushState(null, '', nextPath)
    setPath(nextPath)
    window.scrollTo({ top: 0, behavior: 'instant' })
  }

  return <NavigationContext.Provider value={{ path, navigate }}>{children}</NavigationContext.Provider>
}

export function useNavigation() {
  const context = useContext(NavigationContext)
  if (!context) throw new Error('NavigationProvider is missing')
  return context
}

export function AppLink({ to, className, children, ariaCurrent }: {
  to: string
  className?: string
  children: ReactNode
  ariaCurrent?: 'page'
}) {
  const { navigate } = useNavigation()
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate(to)
  }
  return <a href={to} className={className} aria-current={ariaCurrent} onClick={onClick}>{children}</a>
}
