import { getDevices } from '../api'
import { AppLink } from '../navigation'
import { useApiResource } from '../useApiResource'
import { EmptyState, ErrorState, LoadingState } from '../components/States'

export function Devices() {
  const { resource, retry } = useApiResource(getDevices, 'devices')
  return <>
    <div className="page-intro"><div><span className="eyebrow">DEVICE INVENTORY</span><h1>My Devices</h1><p>Only records assigned to the current development customer appear here. Every record is a labeled fixture awaiting real telemetry integration.</p></div></div>
    {resource.status === 'loading' && <LoadingState label="Loading device inventory…" />}
    {resource.status === 'error' && <ErrorState error={resource.error} retry={retry} />}
    {resource.status === 'ready' && <section className="surface inventory-surface"><div className="section-heading"><div><span className="eyebrow">REGISTERED RECORDS</span><h2>Device inventory <span className="heading-count">{resource.data.length}</span></h2></div></div>
      {resource.data.length === 0 ? <EmptyState title="No devices assigned" text="The current development customer has no device records." /> : <div className="inventory-list">{resource.data.map((device) => <AppLink key={device.id} to={`/devices/${device.id}`} className="inventory-row"><span className="device-row-icon">F</span><span className="device-row-main"><strong>{device.name}</strong><small>{device.reference} · {device.installation_name ?? 'No installation assigned'}</small></span><span className="tag">Development fixture</span><span className="tag tag-muted">Telemetry pending</span><span className="row-arrow" aria-hidden="true">→</span></AppLink>)}</div>}
    </section>}
  </>
}
