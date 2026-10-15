import { useCallback, useEffect, useRef, useState } from 'react'
import { Badge } from '../components/ui'
import { usePortalData } from '../hooks/usePortalData'
import { supabase } from '../supabase'

const MAX_BYTES = 5 * 1024 * 1024
const OK_SUFFIX = /\.(csv|xlsx)$/i
const STATUS = {
  pending: { label: 'Waiting to be processed', color: 'amber' },
  pulled: { label: 'Processed', color: 'green' },
  rejected: { label: 'Could not be used', color: 'red' },
}

async function sha256Hex(file) {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('')
}

// A name that is safe as a storage key whatever the file is called; the original name is kept separately for display.
const storageName = name => name.replace(/[^A-Za-z0-9._-]/g, '_').slice(-80)

export default function Upload() {
  const { clientId } = usePortalData()
  const [uploads, setUploads] = useState([])
  const [message, setMessage] = useState({ text: '', bad: false })
  const [busy, setBusy] = useState(false)
  const input = useRef()

  const load = useCallback(async () => {
    if (!clientId) return
    const { data } = await supabase.from('upload_inbox')
      .select('id, original_filename, size_bytes, status, message, created_at').eq('client_id', clientId)
      .order('created_at', { ascending: false }).limit(20)
    setUploads(data ?? [])
  }, [clientId])

  useEffect(() => { load() }, [load])

  const fail = text => setMessage({ text, bad: true })

  const send = async e => {
    e.preventDefault()
    const file = input.current?.files?.[0]
    if (!file) return fail('Choose a file first.')
    if (!OK_SUFFIX.test(file.name)) return fail('Please choose a .csv or .xlsx file exported from YouTube Studio.')
    if (file.size === 0) return fail('That file is empty.')
    if (file.size > MAX_BYTES) return fail('That file is larger than 5 MB.')

    setBusy(true)
    setMessage({ text: '', bad: false })
    try {
      const hash = await sha256Hex(file)
      const path = `${clientId}/${crypto.randomUUID()}-${storageName(file.name)}`
      const stored = await supabase.storage.from('inbox').upload(path, file, { upsert: false })
      if (stored.error) throw new Error('upload')
      const row = await supabase.from('upload_inbox').insert({
        client_id: clientId, storage_path: path, original_filename: file.name.slice(0, 255), size_bytes: file.size, sha256: hash,
      })
      if (row.error) throw new Error('record')
      input.current.value = ''
      setMessage({ text: 'Uploaded. It will be processed soon and the result will show below.', bad: false })
      load()
    } catch {
      fail('That file could not be uploaded. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="animate-fade-in max-w-2xl space-y-6">
      <h1 className="font-display font-bold text-2xl">Upload an export</h1>

      <section className="card">
        <p className="text-sm mb-3" style={{ color: 'var(--text-muted)' }}>
          In YouTube Studio, open Analytics, choose Advanced mode, and export the table as .csv or .xlsx. Your file is
          checked, added to your report data, and then removed from this site.
        </p>
        <form onSubmit={send} className="space-y-3">
          <input ref={input} type="file" accept=".csv,.xlsx" className="input w-full" aria-label="Studio export file" />
          <div className="flex items-center gap-3">
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Uploading…' : 'Upload'}</button>
            {message.text && (
              <span role={message.bad ? 'alert' : 'status'} className="text-sm"
                style={{ color: message.bad ? 'var(--brand)' : 'var(--text-muted)' }}>{message.text}</span>
            )}
          </div>
        </form>
      </section>

      <section className="card">
        <h2 className="font-display font-bold text-base mb-3">Your uploads</h2>
        {uploads.length === 0 ? (
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>You have not uploaded anything yet.</p>
        ) : (
          <ul className="divide-y" style={{ borderColor: 'var(--surface-border)' }}>
            {uploads.map(u => (
              <li key={u.id} className="py-2 text-sm">
                <div className="flex items-center gap-3">
                  <span className="flex-1 truncate">{u.original_filename}</span>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{new Date(u.created_at).toLocaleDateString()}</span>
                  <Badge color={STATUS[u.status].color}>{STATUS[u.status].label}</Badge>
                </div>
                {u.message && <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{u.message}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
