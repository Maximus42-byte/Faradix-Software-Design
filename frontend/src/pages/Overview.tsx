import { getDevices, getSubscription } from '../api'
import { AppLink } from '../navigation'
import type { Device, SubscriptionStatus } from '../types'
import { useApiResource } from '../useApiResource'
import { EmptyState, ErrorState, LoadingState } from '../components/States'

type OverviewData = { devices: Device[]; subscription: SubscriptionStatus }

export function Overview() {
  const { resource, retry } = useApiResource<OverviewData>(
    async () => {
      const [devices, subscription] = await Promise.all([getDevices(), getSubscription()])
      return { devices, subscription }
    },
    'overview',
  )

  return <>
    <div className="page-intro"><div><span className="eyebrow">CUSTOMER WORKSPACE</span><h1>Overview</h1><p>Manage your Faradix device inventory from one place. Live equipment telemetry is not integrated in this development shell.</p></div><AppLink to="/devices" className="button button-primary">View my devices <span aria-hidden="true">↗</span></AppLink></div>
    {resource.status === 'loading' && <LoadingState label="Loading customer overview…" />}
    {resource.status === 'error' && <ErrorState error={resource.error} retry={retry} />}
    {resource.status === 'ready' && <OverviewContent data={resource.data} />}
  </>
}

function OverviewContent({ data }: { data: OverviewData }) {
  const pending = data.devices.filter((device) => device.telemetry_status === 'pending_integration').length
  const installations = new Set(data.devices.map((device) => device.installation_name).filter(Boolean)).size
  return <>
    <div className="stat-grid">
      <article className="stat-card"><span className="stat-label">MY DEVICES</span><strong className="stat-value">{data.devices.length}</strong><span className="stat-caption">Development inventory records</span></article>
      <article className="stat-card"><span className="stat-label">TELEMETRY INTEGRATION</span><strong className="stat-value">{pending}<span className="stat-value-unit"> pending</span></strong><span className="stat-caption">No sensor readings are shown</span></article>
      <article className="stat-card"><span className="stat-label">INSTALLATION LABELS</span><strong className="stat-value">{installations}</strong><span className="stat-caption">From current inventory data</span></article>
      <article className="stat-card"><span className="stat-label">SUBSCRIPTION</span><strong className="stat-value stat-text">{data.subscription.status === 'not_configured' ? 'Not configured' : '—'}</strong><span className="stat-caption">Billing integration pending</span></article>
    </div>
    <div className="section-grid">
      <section className="surface main-surface"><div className="section-heading"><div><span className="eyebrow">INVENTORY</span><h2>Your devices</h2></div><AppLink to="/devices" className="text-link">See all devices <span aria-hidden="true">→</span></AppLink></div>
        {data.devices.length === 0 ? <EmptyState title="No devices in this customer inventory" text="Device records will appear here when assigned to this customer." /> : <div className="device-list">{data.devices.slice(0, 3).map((device) => <AppLink key={device.id} to={`/devices/${device.id}`} className="device-row"><span className="device-row-icon">F</span><span className="device-row-main"><strong>{device.name}</strong><small>{device.reference} · {device.installation_name ?? 'No installation assigned'}</small></span><span className="tag">Telemetry pending</span><span className="row-arrow" aria-hidden="true">→</span></AppLink>)}</div>}
      </section>
      <aside className="surface note-surface"><span className="eyebrow">INTEGRATION STATUS</span><h2>Ready for the next step</h2><p>This shell uses server-side development fixtures. Device telemetry, history, alarms, authentication, and subscription services still require integration.</p><div className="note-divider"/><div className="note-line"><span className="note-line-dot"/>Local equipment control remains a separate planned system.</div></aside>
    </div>
  </>
}
