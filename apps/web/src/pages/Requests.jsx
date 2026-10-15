import { useCallback, useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { useApi } from '../hooks/useApi'
import { useClient } from '../hooks/useClient'
import { Badge, EmptyState, PageHeader } from '../components/ui'

const TYPES = {
  new_dashboard: 'New dashboard', research: 'Research', more_access: 'More access', other: 'Other',
}
const STATUS = {
  requested: { label: 'Waiting', color: 'amber' }, approved: { label: 'Approved', color: 'blue' },
  declined: { label: 'Declined', color: 'red' }, done: { label: 'Done', color: 'green' },
}
const PERMISSION_COLOR = { granted: 'green', requested: 'amber', denied: 'red', expired: 'default' }

// Requests are written by clients in the portal, so the text is shown as plain text only.
function Inbox({ onChange }) {
  const { get, put, loading } = useApi()
  const [rows, setRows] = useState(null)
  const [openOnly, setOpenOnly] = useState(true)
  const [problem, setProblem] = useState('')

  const load = useCallback(async () => {
    try {
      setRows(await get('/portal/requests', { open_only: openOnly }))
      setProblem('')
    } catch (err) { setProblem(err.message); setRows([]) }
  }, [get, openOnly])

  useEffect(() => { load() }, [load])

  const setStatus = async (row, status) => {
    try {
      await put(`/portal/requests/${row.id}`, { status })
      toast.success(`Marked ${STATUS[status].label.toLowerCase()}`)
      load()
      onChange?.()
    } catch (err) { toast.error(err.message) }
  }

  return (
    <section className="card mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-display font-bold text-base">Client requests</h2>
        <label className="text-xs flex items-center gap-2" style={{ color: 'var(--text-muted)' }}>
          <input type="checkbox" checked={openOnly} onChange={e => setOpenOnly(e.target.checked)} /> open only
        </label>
      </div>
      {problem && <p className="text-sm mb-2" style={{ color: 'var(--brand)' }}>{problem}</p>}
      {!problem && rows && rows.length === 0 && (
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>{loading ? 'Loading…' : 'No requests.'}</p>
      )}
      <ul className="divide-y" style={{ borderColor: 'var(--surface-border)' }}>
        {(rows ?? []).map(r => (
          <li key={r.id} className="py-3 text-sm">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="font-semibold">{r.client_name ?? 'Unknown client'}</span>
              <Badge>{TYPES[r.type] ?? r.type}</Badge>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{new Date(r.created_at).toLocaleString()}</span>
              <span className="ml-auto"><Badge color={STATUS[r.status].color}>{STATUS[r.status].label}</Badge></span>
            </div>
            {r.note && <p className="mt-1 whitespace-pre-wrap break-words">{r.note}</p>}
            <div className="flex gap-2 mt-2">
              {r.status === 'requested' && <>
                <button className="btn btn-primary" onClick={() => setStatus(r, 'approved')}>Approve</button>
                <button className="btn btn-ghost" onClick={() => setStatus(r, 'declined')}>Decline</button>
              </>}
              {(r.status === 'requested' || r.status === 'approved') && (
                <button className="btn btn-ghost" onClick={() => setStatus(r, 'done')}>Mark done</button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

const RESULT = {
  imported: { label: 'Imported', color: 'green' }, duplicate: { label: 'Already had it', color: 'default' },
  rejected: { label: 'Rejected', color: 'red' }, skipped: { label: 'Left waiting', color: 'amber' },
}

// Files clients uploaded in the portal. Nothing is pushed in: this button reaches out and pulls them.
function Uploads({ onDone }) {
  const { get, post } = useApi()
  const { dataChanged } = useClient()
  const [waiting, setWaiting] = useState(null)
  const [results, setResults] = useState([])
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => get('/portal/inbox').then(setWaiting).catch(() => setWaiting(null)), [get])
  useEffect(() => { load() }, [load])

  const pull = async () => {
    setBusy(true)
    try {
      const outcomes = await post('/portal/inbox/pull')
      setResults(outcomes)
      toast.success(`${outcomes.filter(o => o.result === 'imported').length} imported`)
      await load()
      dataChanged()
      onDone?.()
    } catch (err) { toast.error(err.message) } finally { setBusy(false) }
  }

  if (waiting === null) return null
  return (
    <section className="card mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-display font-bold text-base">Client uploads</h2>
        <button className="btn btn-primary" disabled={busy || waiting.length === 0} onClick={pull}>
          {busy ? 'Importing…' : waiting.length ? `Import ${waiting.length} waiting` : 'Nothing waiting'}
        </button>
      </div>
      <ul className="text-sm space-y-1">
        {waiting.map(u => (
          <li key={u.id}>
            <span className="font-semibold">{u.client_name ?? 'Unknown client'}</span> · {u.original_filename}
            <span className="text-xs ml-2" style={{ color: 'var(--text-muted)' }}>{(u.size_bytes / 1024).toFixed(0)} KB</span>
          </li>
        ))}
      </ul>
      {results.length > 0 && (
        <ul className="mt-3 pt-3 border-t text-sm space-y-1" style={{ borderColor: 'var(--surface-border)' }}>
          {results.map(r => (
            <li key={r.inbox_id} className="flex items-center gap-2">
              <Badge color={RESULT[r.result].color}>{RESULT[r.result].label}</Badge>
              <span>{r.client_name ?? 'Unknown client'} · {r.filename}</span>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{r.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Access({ client }) {
  const { get, put, del } = useApi()
  const [permissions, setPermissions] = useState([])
  const [feature, setFeature] = useState('research')
  const [quota, setQuota] = useState('')
  const [days, setDays] = useState('30')
  const [focus, setFocus] = useState(null)

  const load = useCallback(async () => {
    try {
      setPermissions(await get(`/clients/${client.id}/portal/permissions`))
      setFocus((await get(`/clients/${client.id}/portal/preferences`)).focus)
    } catch { setPermissions([]) }
  }, [get, client.id])

  useEffect(() => { load() }, [load])

  const base = `/clients/${client.id}/portal/permissions`

  const grant = async status => {
    try {
      setPermissions(await put(`${base}/${feature}`, {
        status, quota: quota === '' ? null : Number(quota), expires_in_days: days === '' ? null : Number(days),
      }))
      toast.success(`${feature}: ${status}`)
    } catch (err) { toast.error(err.message) }
  }

  return (
    <section className="card">
      <h2 className="font-display font-bold text-base mb-3">Access for {client.name}</h2>
      <ul className="mb-4 space-y-1 text-sm">
        {permissions.length === 0 && <li style={{ color: 'var(--text-muted)' }}>Nothing beyond the basics has been set.</li>}
        {permissions.map(p => (
          <li key={p.feature} className="flex items-center gap-3">
            <span className="font-mono">{p.feature}</span>
            <Badge color={PERMISSION_COLOR[p.status]}>{p.status}</Badge>
            {p.quota != null && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>quota {p.quota}</span>}
            {p.expires_at && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>until {new Date(p.expires_at).toLocaleDateString()}</span>}
            <button className="btn btn-ghost ml-auto" onClick={() => del(`${base}/${p.feature}`).then(setPermissions).catch(e => toast.error(e.message))}>Remove</button>
          </li>
        ))}
      </ul>
      <div className="flex gap-2 flex-wrap items-center">
        <input className="input w-44" value={feature} onChange={e => setFeature(e.target.value.toLowerCase())}
          placeholder="feature, e.g. research" aria-label="feature" />
        <input className="input w-24" type="number" min="0" value={quota} onChange={e => setQuota(e.target.value)} placeholder="quota" />
        <input className="input w-28" type="number" min="1" value={days} onChange={e => setDays(e.target.value)} placeholder="days valid" />
        <button className="btn btn-primary" onClick={() => grant('granted')}>Grant</button>
        <button className="btn btn-ghost" onClick={() => grant('denied')}>Deny</button>
      </div>
      <div className="mt-5 text-sm">
        <div className="text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>What they asked you to focus on</div>
        {focus && (focus.areas?.length || focus.note) ? (
          <>
            {focus.areas?.length > 0 && <p>{focus.areas.join(', ')}</p>}
            {focus.note && <p className="mt-1 whitespace-pre-wrap break-words" style={{ color: 'var(--text-muted)' }}>{focus.note}</p>}
          </>
        ) : <p style={{ color: 'var(--text-muted)' }}>Nothing chosen yet.</p>}
      </div>
    </section>
  )
}

export default function Requests() {
  const { client, loadStatus } = useClient()
  return (
    <div className="animate-fade-in max-w-4xl">
      <PageHeader title="Requests" subtitle="Requests, access and focus choices from the client portal" />
      <Uploads />
      <Inbox onChange={loadStatus} />
      {client ? <Access client={client} /> : <EmptyState icon="📬" title="No client selected" desc="Pick a client in the sidebar." />}
    </div>
  )
}
