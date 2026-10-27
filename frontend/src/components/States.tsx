import { ApiError } from '../api'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <div className="state-panel" role="status"><span className="loading-dot" />{label}</div>
}

export function EmptyState({ title, text }: { title: string; text: string }) {
  return <div className="empty-state"><span className="empty-symbol" aria-hidden="true">◇</span><h3>{title}</h3><p>{text}</p></div>
}

export function ErrorState({ error, retry }: { error: unknown; retry: () => void }) {
  const unavailable = error instanceof ApiError && (error.status === 0 || error.status >= 500)
  return <div className="state-panel state-error" role="alert">
    <div><strong>{unavailable ? 'Backend or API unavailable' : 'Unable to load this page'}</strong>
      <p>{unavailable ? 'Start or check the local API and try again. Navigation remains available.' : 'The API request did not complete. Try again.'}</p></div>
    <button className="button button-secondary" onClick={retry}>Try again</button>
  </div>
}
