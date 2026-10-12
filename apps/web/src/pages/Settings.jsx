import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { useApi } from '../hooks/useApi'
import { PageHeader } from '../components/ui'

export default function Settings() {
  const { get, post, loading } = useApi()
  const [apiKey,    setApiKey]    = useState('')
  const [keyStatus, setKeyStatus] = useState(null)
  const [showKey,   setShowKey]   = useState(false)
  const [health,    setHealth]    = useState(null)

  useEffect(() => {
    get('/settings').then(setKeyStatus).catch(() => {})
    get('/health').then(setHealth).catch(() => {})
  }, [])  // eslint-disable-line

  const handleSave = async () => {
    if (!apiKey.trim()) { toast.error('Please enter an API key'); return }
    try {
      await post('/settings', { api_key: apiKey.trim() })
      toast.success('API key saved for this session')
      setApiKey('')
      const s = await get('/settings')
      setKeyStatus(s)
    } catch (err) {
      toast.error(err.message)
    }
  }

  return (
    <div className="animate-fade-in max-w-2xl">
      <PageHeader title="Settings" subtitle="Configure your YouTube Data API key and preferences" />

      {/* ── API Key ──────────────────────────────────────────────────────── */}
      <section className="card mb-5">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-xl">🔑</span>
          <h2 className="font-display font-bold text-base">YouTube Data API Key</h2>
        </div>

        {/* Current status */}
        {keyStatus && (
          <div className={`rounded-lg p-3 mb-4 flex items-center gap-2 text-sm`}
            style={keyStatus.has_api_key
              ? { background: 'rgba(74,222,128,0.08)', border: '1px solid rgba(74,222,128,0.2)' }
              : { background: 'rgba(255,60,60,0.08)',  border: '1px solid rgba(255,60,60,0.2)' }}>
            <span>{keyStatus.has_api_key ? '✅' : '⚠️'}</span>
            <span style={{ color: keyStatus.has_api_key ? '#4ade80' : '#ff6b6b' }}>
              {keyStatus.has_api_key
                ? `API key configured (${keyStatus.key_preview})`
                : 'No API key set. Thumbnails and researcher features require an API key.'}
            </span>
          </div>
        )}

        {/* Input */}
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <input
              type={showKey ? 'text' : 'password'}
              placeholder="AIza…"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSave()}
              className="input pr-10"
            />
            <button
              type="button"
              onClick={() => setShowKey(s => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-xs"
              style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer' }}>
              {showKey ? '🙈' : '👁️'}
            </button>
          </div>
          <button className="btn btn-primary shrink-0" onClick={handleSave} disabled={loading}>
            Save Key
          </button>
        </div>

        <p className="text-xs mt-3" style={{ color: 'var(--text-muted)' }}>
          The key is stored only in memory for the current Flask session. 
          Add it to your <code className="font-mono px-1 rounded-sm" style={{ background: 'rgba(255,255,255,0.08)' }}>.env</code> file 
          as <code className="font-mono px-1 rounded-sm" style={{ background: 'rgba(255,255,255,0.08)' }}>YOUTUBE_API_KEY</code> for persistence.
        </p>
      </section>

      {/* ── How to get a key ──────────────────────────────────────────────── */}
      <section className="card mb-5">
        <h2 className="font-display font-bold text-base mb-3">How to get a YouTube Data API key</h2>
        <ol className="space-y-2">
          {[
            <>Go to <a href="https://console.cloud.google.com" target="_blank" rel="noreferrer" style={{ color: 'var(--accent-blue)' }} className="underline">console.cloud.google.com</a></>,
            'Create or select a project',
            'Navigate to APIs & Services → Library',
            'Search for "YouTube Data API v3" and enable it',
            'Go to APIs & Services → Credentials → Create Credentials → API Key',
            'Copy the key and paste it above',
          ].map((step, i) => (
            <li key={i} className="flex items-start gap-3 text-sm" style={{ color: 'var(--text-muted)' }}>
              <span className="shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-display font-bold"
                style={{ background: 'var(--brand-dim)', color: 'var(--brand)', marginTop: 1 }}>
                {i+1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </section>

      {/* ── System status ─────────────────────────────────────────────────── */}
      <section className="card">
        <h2 className="font-display font-bold text-base mb-4">System Status</h2>
        <div className="space-y-2">
          {[
            { label: 'Flask API', ok: true },
            { label: 'Dataset loaded', ok: health?.cache_loaded },
            { label: 'API key configured', ok: keyStatus?.has_api_key },
          ].map(({ label, ok }) => (
            <div key={label} className="flex items-center justify-between py-2 border-b last:border-0"
              style={{ borderColor: 'var(--surface-border)' }}>
              <span className="text-sm" style={{ color: 'var(--text-muted)' }}>{label}</span>
              <span className={`text-xs font-mono font-bold`}
                style={{ color: ok ? '#4ade80' : '#ff6b6b' }}>
                {ok === undefined ? '…' : ok ? '● OK' : '● Not set'}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
