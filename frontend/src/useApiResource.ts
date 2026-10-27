import { useEffect, useState } from 'react'

type Resource<T> =
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; error: unknown }

export function useApiResource<T>(load: () => Promise<T>, key: string) {
  const [resource, setResource] = useState<Resource<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    setResource({ status: 'loading' })
    load().then(
      (data) => { if (active) setResource({ status: 'ready', data }) },
      (error: unknown) => { if (active) setResource({ status: 'error', error }) },
    )
    return () => { active = false }
    // The key captures the route or backend-state change that should reload data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt])

  return { resource, retry: () => setAttempt((value) => value + 1) }
}
