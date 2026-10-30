import { useEffect, useState } from 'react'
import { getDeviceTelemetry } from './api'
import type { TelemetrySample } from './types'

type TelemetryState = {
  status: 'loading' | 'no_samples' | 'fresh' | 'stale' | 'unavailable'
  sample: TelemetrySample | null
  freshnessSeconds: number
}

const configuredInterval = Number(import.meta.env.VITE_TELEMETRY_POLL_MS)
const pollIntervalMs = Number.isFinite(configuredInterval) && configuredInterval >= 1000 && configuredInterval <= 60000
  ? configuredInterval : 5000

export function useLatestTelemetry(deviceId: string): TelemetryState {
  const [state, setState] = useState<TelemetryState>({ status: 'loading', sample: null, freshnessSeconds: 15 })

  useEffect(() => {
    let active = true
    let timer: number | undefined
    let controller: AbortController | undefined
    setState({ status: 'loading', sample: null, freshnessSeconds: 15 })

    async function poll() {
      controller = new AbortController()
      try {
        const response = await getDeviceTelemetry(deviceId, controller.signal)
        if (active) setState({ status: response.status, sample: response.sample, freshnessSeconds: response.freshness_seconds })
      } catch {
        // Keep the last reading visible, but stop describing it as fresh.
        if (active) setState((previous) => ({ ...previous, status: 'unavailable' }))
      } finally {
        // Schedule after completion so requests never overlap.
        if (active) timer = window.setTimeout(poll, pollIntervalMs)
      }
    }

    void poll()
    return () => {
      active = false
      window.clearTimeout(timer)
      controller?.abort()
    }
  }, [deviceId])

  return state
}
