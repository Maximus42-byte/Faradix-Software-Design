import { ApiError, getDevice } from '../api'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { TelemetryPanel } from '../components/TelemetryPanel'
import { AppLink } from '../navigation'
import { useApiResource } from '../useApiResource'

export function DeviceDetail({ id }: { id: string }) {
  const { resource, retry } = useApiResource(() => getDevice(id), id)
  return <>
    <div className="page-intro detail-intro"><div><AppLink to="/devices" className="back-link">← Back to My Devices</AppLink><span className="eyebrow">DEVICE DETAILS</span><h1>{resource.status === 'ready' ? resource.data.name : 'Device Details'}</h1><p>Identity and installation information from the current customer’s development inventory, with synthetic telemetry when published.</p></div></div>
    {resource.status === 'loading' && <LoadingState label="Loading device details…" />}
    {resource.status === 'error' && (resource.error instanceof ApiError && resource.error.status === 404 ? <div className="surface not-found"><EmptyState title="Device not found" text="This device is unavailable in the current customer inventory." /><AppLink to="/devices" className="button button-secondary">Return to My Devices</AppLink></div> : <ErrorState error={resource.error} retry={retry} />)}
    {resource.status === 'ready' && <>
      <div className="detail-banner"><div><span className="eyebrow">DEVELOPMENT FIXTURE</span><strong>{resource.data.reference}</strong><p>Development inventory fixture. Synthetic samples may appear below; no physical equipment connection is implied.</p></div><span className="tag tag-light">Real telemetry pending</span></div>
      <div className="detail-grid"><section className="surface"><div className="section-heading"><div><span className="eyebrow">IDENTITY</span><h2>Device information</h2></div></div><dl className="detail-list"><div><dt>Device name</dt><dd>{resource.data.name}</dd></div><div><dt>Device ID</dt><dd>{resource.data.id}</dd></div><div><dt>Reference</dt><dd>{resource.data.reference}</dd></div><div><dt>Installation</dt><dd>{resource.data.installation_name ?? 'Not assigned'}</dd></div><div><dt>Source</dt><dd>{resource.data.fixture_label}</dd></div></dl></section>
      <TelemetryPanel key={id} deviceId={id} /></div>
      <section className="surface history-surface"><div className="section-heading"><div><span className="eyebrow">PAST DATA</span><h2>History & alarms</h2></div></div><EmptyState title="No history available" text="Event, alarm, and measurement history will appear after a real data pipeline is integrated." /></section>
    </>}
  </>
}
