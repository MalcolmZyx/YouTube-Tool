import { useCallback, useEffect, useState } from 'react'
import { Badge } from '../components/ui'
import { usePortalData } from '../hooks/usePortalData'
import { supabase } from '../supabase'

const TYPES = {
  new_dashboard: 'A new dashboard or report',
  research: 'Topic and trend research',
  more_access: 'More access',
  other: 'Something else',
}
const STATUS = {
  requested: { label: 'Waiting', color: 'amber' },
  approved: { label: 'Approved', color: 'blue' },
  declined: { label: 'Declined', color: 'red' },
  done: { label: 'Done', color: 'green' },
}
const PERMISSION = {
  requested: { label: 'Requested', color: 'amber' },
  granted: { label: 'Granted', color: 'green' },
  denied: { label: 'Not granted', color: 'red' },
  expired: { label: 'Expired', color: 'default' },
}
const FEATURES = { research: 'Topic and trend research', extra_dashboards: 'Extra dashboards' }

export default function Requests() {
  const { clientId } = usePortalData()
  const [requests, setRequests] = useState([])
  const [permissions, setPermissions] = useState([])
  const [type, setType] = useState('new_dashboard')
  const [note, setNote] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!clientId) return
    const [r, p] = await Promise.all([
      supabase.from('service_request').select('id, type, note, status, created_at').eq('client_id', clientId)
        .order('created_at', { ascending: false }),
      supabase.from('client_permission').select('feature, status, quota, expires_at').eq('client_id', clientId),
    ])
    setRequests(r.data ?? [])
    setPermissions(p.data ?? [])
  }, [clientId])

  useEffect(() => { load() }, [load])

  const send = async (kind, text) => {
    setBusy(true)
    setMessage('')
    const { error } = await supabase.from('service_request').insert({ client_id: clientId, type: kind, note: text })
    setBusy(false)
    if (error) { setMessage('That request could not be sent. Please try again.'); return false }
    setMessage('Request sent. You will see its status here.')
    load()
    return true
  }

  const submit = async e => {
    e.preventDefault()
    if (await send(type, note.trim())) setNote('')
  }

  const state = Object.fromEntries(permissions.map(p => [p.feature, p]))

  return (
    <div className="animate-fade-in max-w-3xl space-y-6">
      <h1 className="font-display font-bold text-2xl">Requests</h1>

      <section className="card">
        <h2 className="font-display font-bold text-base mb-3">Ask for something</h2>
        <form onSubmit={submit} className="space-y-3">
          <select className="input w-full" value={type} onChange={e => setType(e.target.value)}>
            {Object.entries(TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <textarea className="input w-full" rows={3} maxLength={1000} placeholder="Tell us what you would like (optional)"
            value={note} onChange={e => setNote(e.target.value)} />
          <div className="flex items-center gap-3">
            <button className="btn btn-primary" type="submit" disabled={busy}>Send request</button>
            {message && <span role="status" className="text-sm" style={{ color: 'var(--text-muted)' }}>{message}</span>}
          </div>
        </form>
      </section>

      <section className="card">
        <h2 className="font-display font-bold text-base mb-1">Your access</h2>
        <p className="text-xs mb-3" style={{ color: 'var(--text-muted)' }}>
          You can always view your published report, upload an export and choose your focus. Anything beyond that
          is switched on for you after you ask.
        </p>
        <ul className="divide-y" style={{ borderColor: 'var(--surface-border)' }}>
          {Object.entries(FEATURES).map(([feature, label]) => {
            const p = state[feature]
            const s = p ? PERMISSION[p.status] : null
            return (
              <li key={feature} className="py-2 flex items-center gap-3 text-sm">
                <span className="flex-1">{label}</span>
                {s ? <Badge color={s.color}>{s.label}</Badge> : <Badge>Not enabled</Badge>}
                {p?.quota != null && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>quota {p.quota}</span>}
                {p?.expires_at && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>until {new Date(p.expires_at).toLocaleDateString()}</span>}
                {(!p || p.status === 'denied' || p.status === 'expired') && (
                  <button className="btn btn-ghost" disabled={busy} onClick={() => send('more_access', `Access to: ${label} (${feature})`)}>
                    Ask for access
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      </section>

      <section className="card">
        <h2 className="font-display font-bold text-base mb-3">Your requests</h2>
        {requests.length === 0 ? (
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>You have not made any requests yet.</p>
        ) : (
          <ul className="divide-y" style={{ borderColor: 'var(--surface-border)' }}>
            {requests.map(r => (
              <li key={r.id} className="py-2 text-sm">
                <div className="flex items-center gap-3">
                  <span className="flex-1 font-medium">{TYPES[r.type] ?? r.type}</span>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{new Date(r.created_at).toLocaleDateString()}</span>
                  <Badge color={STATUS[r.status].color}>{STATUS[r.status].label}</Badge>
                </div>
                {r.note && <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{r.note}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
