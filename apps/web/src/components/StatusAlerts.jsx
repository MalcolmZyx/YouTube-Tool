import toast from 'react-hot-toast'
import { useClient } from '../hooks/useClient'

const fmtDate = iso => new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

// Stored YouTube data may be kept for 30 days. Refreshing and deleting it is manual for now, so this asks.
export default function StatusAlerts() {
  const { alerts, refreshPublicData, deletePublicData } = useClient()
  if (!alerts?.length) return null

  const refresh = async a => {
    toast.loading('Fetching YouTube details…', { id: 'pd' })
    try {
      const r = await refreshPublicData(a.client_id)
      toast.success(`Refreshed ${r.stored} videos for ${a.client_name}`, { id: 'pd' })
    } catch (err) { toast.error(err.message, { id: 'pd' }) }
  }

  const erase = async a => {
    if (!window.confirm(`Delete the stored YouTube details (tags, descriptions, thumbnails) for ${a.client_name}? `
      + 'Their exported figures are kept.')) return
    try {
      const r = await deletePublicData(a.client_id)
      toast.success(`Deleted YouTube details for ${r.deleted_videos} videos`)
    } catch (err) { toast.error(err.message) }
  }

  return (
    <div className="space-y-2 mb-6" role="alert">
      {alerts.map(a => {
        const expired = a.level === 'expired'
        const color = expired ? 'var(--brand)' : '#fbbf24'
        return (
          <div key={a.client_id} className="card flex items-center gap-4 flex-wrap"
            style={{ borderColor: color }}>
            <div className="flex-1 min-w-64 text-sm">
              <span className="font-semibold" style={{ color }}>
                {expired ? 'YouTube data expired' : 'YouTube data expires soon'}
              </span>
              {' · '}{a.client_name}
              <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                {expired
                  ? `${a.expired} of ${a.stored} videos passed the 30-day limit and are hidden from Keywords and Descriptions.`
                  : `${a.expiring_soon} of ${a.stored} videos expire by ${fmtDate(a.next_expiry)}.`}
                {' '}Refresh to keep it, or delete it.
              </div>
            </div>
            <button className="btn btn-primary" onClick={() => refresh(a)}>Refresh now</button>
            <button className="btn btn-ghost" onClick={() => erase(a)}>Delete YouTube data</button>
          </div>
        )
      })}
    </div>
  )
}
