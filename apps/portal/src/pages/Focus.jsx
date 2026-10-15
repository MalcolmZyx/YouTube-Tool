import { useEffect, useState } from 'react'
import { usePortalData } from '../hooks/usePortalData'
import { supabase } from '../supabase'

const AREAS = {
  retention: 'Audience retention',
  titles_thumbnails: 'Titles and thumbnails',
  shorts_vs_long: 'Shorts compared with long videos',
  upload_schedule: 'Upload schedule',
  traffic_sources: 'Where viewers come from',
  geography: 'Where viewers live',
  audience: 'Who my audience is',
}

export default function Focus() {
  const { clientId } = usePortalData()
  const [areas, setAreas] = useState([])
  const [note, setNote] = useState('')
  const [exists, setExists] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!clientId) return
    supabase.from('dashboard_preference').select('focus').eq('client_id', clientId).maybeSingle().then(({ data }) => {
      setExists(!!data)
      setAreas(data?.focus?.areas ?? [])
      setNote(data?.focus?.note ?? '')
    })
  }, [clientId])

  const toggle = key => setAreas(a => (a.includes(key) ? a.filter(k => k !== key) : [...a, key]))

  const save = async e => {
    e.preventDefault()
    const focus = { areas, note: note.trim() }
    // Insert the first time, update after: the database lets a client change only its own focus, nothing else.
    const query = exists
      ? supabase.from('dashboard_preference').update({ focus, updated_at: new Date().toISOString() }).eq('client_id', clientId)
      : supabase.from('dashboard_preference').insert({ client_id: clientId, focus })
    const { error } = await query
    if (error) { setMessage('Your choices could not be saved. Please try again.'); return }
    setExists(true)
    setMessage('Saved. Your next report will take this into account.')
  }

  return (
    <div className="animate-fade-in max-w-2xl">
      <h1 className="font-display font-bold text-2xl mb-1">What to focus on</h1>
      <p className="text-sm mb-4" style={{ color: 'var(--text-muted)' }}>
        Choose what matters most to you. It helps decide what your next report emphasises.
      </p>
      <form onSubmit={save} className="card space-y-4">
        <div className="grid sm:grid-cols-2 gap-2">
          {Object.entries(AREAS).map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={areas.includes(key)} onChange={() => toggle(key)} />
              {label}
            </label>
          ))}
        </div>
        <textarea className="input w-full" rows={3} maxLength={500} placeholder="Anything else you want us to look at? (optional)"
          value={note} onChange={e => setNote(e.target.value)} />
        <div className="flex items-center gap-3">
          <button className="btn btn-primary" type="submit">Save</button>
          {message && <span role="status" className="text-sm" style={{ color: 'var(--text-muted)' }}>{message}</span>}
        </div>
      </form>
    </div>
  )
}
