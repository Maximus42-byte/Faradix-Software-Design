import { EmptyState, LoadingState } from './States'
import { useLatestTelemetry } from '../useLatestTelemetry'

export function TelemetryPanel({ deviceId }: { deviceId: string }) {
  const telemetry = useLatestTelemetry(deviceId)
  return <section className="surface"><div className="section-heading"><div><span className="eyebrow">LATEST SAMPLE</span><h2>Telemetry</h2></div></div>
    {telemetry.status === 'loading' && <LoadingState label="Loading telemetry…" />}
    {telemetry.status === 'no_samples' && <EmptyState title="No samples received" text="The development publisher has not sent a simulated sample for this device. No physical connection is indicated." />}
    {telemetry.status === 'unavailable' && <div className="telemetry-notice" role="alert"><strong>Backend unavailable</strong><p>Cannot check for new samples. Any reading below is the last one received by this browser; its current freshness is unknown.</p></div>}
    {telemetry.sample && <div className="telemetry-reading">
      <div className="telemetry-labels"><strong className="simulated-label">Simulated data</strong>{telemetry.status !== 'unavailable' && <span className={`telemetry-condition ${telemetry.status}`}>{telemetry.status === 'fresh' ? 'Fresh simulated data' : 'Stale simulated data'}</span>}</div>
      <p className="telemetry-explainer">Synthetic transport example. These values are not operating limits or evidence of connected equipment.</p>
      <dl className="detail-list"><div><dt>Stack voltage</dt><dd>{telemetry.sample.measurements.stack_voltage_v.toFixed(1)} V</dd></div><div><dt>Stack current</dt><dd>{telemetry.sample.measurements.stack_current_a.toFixed(1)} A</dd></div><div><dt>Electrolyte temperature</dt><dd>{telemetry.sample.measurements.electrolyte_temperature_c.toFixed(1)} °C</dd></div><div><dt>Measured at</dt><dd><time dateTime={telemetry.sample.measured_at}>{new Date(telemetry.sample.measured_at).toLocaleString(undefined, { timeZone: 'UTC', timeZoneName: 'short' })}</time></dd></div></dl>
      {telemetry.status === 'stale' && <p className="telemetry-explainer">No newer sample within {telemetry.freshnessSeconds} seconds. The last value is retained.</p>}
    </div>}
    {telemetry.status === 'unavailable' && !telemetry.sample && <EmptyState title="No cached reading" text="Start or check the local backend to load telemetry." />}
  </section>
}
