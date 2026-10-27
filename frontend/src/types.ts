export type Health = {
  status: 'ok'
  mode: 'development_demo'
  authentication_configured: false
}

export type Customer = {
  id: string
  name: string
  fixture_label: 'Development fixture'
}

export type Device = {
  id: string
  name: string
  reference: string
  installation_name: string | null
  telemetry_status: 'pending_integration' | 'available'
  fixture_label: 'Development fixture'
}

export type DeviceDetail = Device & {
  telemetry_available: boolean
  history_available: boolean
}

export type SubscriptionStatus = {
  status: 'not_configured'
  message: string
}
