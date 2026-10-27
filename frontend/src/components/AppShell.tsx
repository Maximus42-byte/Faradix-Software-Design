import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { getCurrentCustomer, getHealth } from '../api'
import { AppLink, useNavigation } from '../navigation'
import { useApiResource } from '../useApiResource'

type BackendState = 'checking' | 'online' | 'offline'
type IconName = 'overview' | 'devices' | 'subscription'

function Icon({ name }: { name: IconName }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  if (name === 'overview') return <svg viewBox="0 0 24 24" aria-hidden="true" {...common}><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="10" width="8" height="11" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/></svg>
  if (name === 'devices') return <svg viewBox="0 0 24 24" aria-hidden="true" {...common}><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 11h6M9 16h2"/><circle cx="15.5" cy="16.5" r="1"/></svg>
  return <svg viewBox="0 0 24 24" aria-hidden="true" {...common}><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M7 15h4"/></svg>
}

const navigation: { to: string; label: string; icon: IconName }[] = [
  { to: '/', label: 'Overview', icon: 'overview' },
  { to: '/devices', label: 'My Devices', icon: 'devices' },
  { to: '/subscription', label: 'Subscription', icon: 'subscription' },
]

export function AppShell({ title, children }: { title: string; children: ReactNode }) {
  const { path } = useNavigation()
  const [backend, setBackend] = useState<BackendState>('checking')
  const customer = useApiResource(getCurrentCustomer, backend)

  useEffect(() => {
    let active = true
    const check = () => {
      getHealth().then(
        (health) => { if (active) setBackend(health.status === 'ok' ? 'online' : 'offline') },
        () => { if (active) setBackend('offline') },
      )
    }
    check()
    const timer = window.setInterval(check, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  return <div className="app-layout">
    <aside className="sidebar">
      <AppLink to="/" className="brand"><span className="brand-mark">F<span className="brand-mark-dot"/></span><span><strong>Faradix</strong><small>CUSTOMER WORKSPACE</small></span></AppLink>
      <div className="sidebar-divider" />
      <div className="nav-group-label">WORKSPACE</div>
      <nav className="side-nav" aria-label="Main navigation">
        {navigation.map((item) => {
          const active = item.to === '/' ? path === '/' : path === item.to || (item.to === '/devices' && path.startsWith('/devices/'))
          return <AppLink key={item.to} to={item.to} className={`nav-link${active ? ' active' : ''}`} ariaCurrent={active ? 'page' : undefined}>
            <Icon name={item.icon} /><span>{item.label}</span>{active && <span className="nav-active-marker"/>}
          </AppLink>
        })}
      </nav>
      <div className="sidebar-spacer" />
      <div className="demo-card"><span className="demo-card-icon">i</span><div><strong>Development demo</strong><p>Fixture inventory only. No live equipment data or authentication.</p></div></div>
      <div className="sidebar-footer">Faradix platform shell <span>·</span> Local only</div>
    </aside>
    <div className="main-column">
      <header className="topbar">
        <div className="topbar-location"><span>Customer workspace</span><span className="breadcrumb-divider">/</span><strong>{title}</strong></div>
        <div className="topbar-right">
          <span className="demo-pill">DEVELOPMENT DEMO</span>
          <div className="customer-identity"><span className="avatar">{customer.resource.status === 'ready' ? customer.resource.data.name.charAt(0) : '—'}</span><span className="customer-identity-text"><small>CURRENT CUSTOMER</small><strong>{customer.resource.status === 'ready' ? customer.resource.data.name : customer.resource.status === 'loading' ? 'Loading customer…' : 'Customer unavailable'}</strong></span></div>
          <span className={`backend-status ${backend}`} role="status"><span className="backend-dot" />{backend === 'online' ? 'Backend online' : backend === 'offline' ? 'Backend unavailable' : 'Checking backend'}</span>
        </div>
      </header>
      <main id="main-content" className="content">{children}</main>
    </div>
  </div>
}
