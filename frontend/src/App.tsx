import { AppShell } from './components/AppShell'
import { EmptyState } from './components/States'
import { AppLink, NavigationProvider, useNavigation } from './navigation'
import { DeviceDetail } from './pages/DeviceDetail'
import { Devices } from './pages/Devices'
import { Overview } from './pages/Overview'
import { Subscription } from './pages/Subscription'

function CurrentPage() {
  const { path } = useNavigation()
  if (path === '/') return <AppShell title="Overview"><Overview /></AppShell>
  if (path === '/devices') return <AppShell title="My Devices"><Devices /></AppShell>
  if (path === '/subscription') return <AppShell title="Subscription"><Subscription /></AppShell>
  const detail = /^\/devices\/([^/]+)$/.exec(path)
  if (detail) {
    try {
      return <AppShell title="Device Details"><DeviceDetail id={decodeURIComponent(detail[1])} /></AppShell>
    } catch {
      // Malformed URL escapes are treated as an unknown page.
    }
  }
  return <AppShell title="Page not found"><div className="surface not-found"><EmptyState title="Page not found" text="This page does not exist in the customer workspace." /><AppLink to="/" className="button button-secondary">Return to Overview</AppLink></div></AppShell>
}

export default function App() {
  return <NavigationProvider><CurrentPage /></NavigationProvider>
}
