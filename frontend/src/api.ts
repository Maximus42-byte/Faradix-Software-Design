import type { Customer, Device, DeviceDetail, Health, SubscriptionStatus } from './types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the Faradix development API.')
  }
  if (!response.ok) {
    throw new ApiError(response.status, response.status === 404 ? 'Not found.' : 'The API request failed.')
  }
  return (await response.json()) as T
}

export const getHealth = () => request<Health>('/health')
export const getCurrentCustomer = () => request<Customer>('/me')
export const getDevices = () => request<Device[]>('/devices')
export const getDevice = (id: string) => request<DeviceDetail>(`/devices/${encodeURIComponent(id)}`)
export const getSubscription = () => request<SubscriptionStatus>('/subscription')
