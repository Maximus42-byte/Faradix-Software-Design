import { getSubscription } from '../api'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useApiResource } from '../useApiResource'

export function Subscription() {
  const { resource, retry } = useApiResource(getSubscription, 'subscription')
  return <>
    <div className="page-intro"><div><span className="eyebrow">ACCOUNT SERVICES</span><h1>Subscription</h1><p>Subscription packaging, pricing, billing intervals, and payment providers have not been decided.</p></div></div>
    {resource.status === 'loading' && <LoadingState label="Loading subscription integration status…" />}
    {resource.status === 'error' && <ErrorState error={resource.error} retry={retry} />}
    {resource.status === 'ready' && <div className="subscription-grid"><section className="surface subscription-main"><span className="eyebrow">CURRENT STATUS</span><span className="subscription-status">Not configured</span><EmptyState title="Subscription integration is pending" text={resource.data.message} /></section><aside className="surface note-surface"><span className="eyebrow">PRODUCT DECISIONS</span><h2>Plans are still being defined</h2><p>Included features, paid services, charging basis, expiry behavior, and historical-data access remain open decisions. No active subscription or payment data is shown in this shell.</p><div className="note-divider"/><div className="note-line"><span className="note-line-dot"/>Basic local equipment control and independent safety must not depend on billing.</div></aside></div>}
  </>
}
