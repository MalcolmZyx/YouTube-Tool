import { NavLink } from 'react-router-dom'
import { useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { useClient } from '../hooks/useClient'

const NAV = [
  { to: '/',            icon: GridIcon,     label: 'Dashboard'   },
  { to: '/heatmap',     icon: CalendarIcon, label: 'Heatmap'     },
  { to: '/keywords',    icon: TagIcon,      label: 'Keywords'    },
  { to: '/descriptions',icon: DocIcon,      label: 'Descriptions'},
  { to: '/researcher',  icon: SearchIcon,   label: 'Researcher'  },
  { to: '/settings',    icon: GearIcon,     label: 'Settings'    },
]

export default function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex flex-col w-56 border-r"
      style={{ background: 'var(--surface-card)', borderColor: 'var(--surface-border)' }}>

      {/* Logo */}
      <div className="flex items-center gap-2 px-5 py-5 border-b"
        style={{ borderColor: 'var(--surface-border)' }}>
        <span className="text-2xl">▶</span>
        <div>
          <div className="font-display font-800 text-sm leading-tight tracking-wide"
            style={{ color: 'var(--brand)' }}>YT Analytics</div>
          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>Studio</div>
        </div>
      </div>

      <ClientSwitcher />

      {/* Nav links */}
      <nav className="flex-1 py-4 space-y-1 px-2 overflow-y-auto">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink key={to} to={to} end={to === '/'}
            className={({ isActive }) => clsx(
              'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150',
              isActive
                ? 'font-semibold'
                : 'hover:bg-white/5'
            )}
            style={({ isActive }) => isActive
              ? { background: 'var(--brand-dim)', color: 'var(--brand)', fontFamily: 'Syne, sans-serif' }
              : { color: 'var(--text-muted)', fontFamily: 'DM Sans, sans-serif' }
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t text-xs" style={{ borderColor: 'var(--surface-border)', color: 'var(--text-muted)' }}>
        v0.2.0 · FastAPI + React
      </div>
    </aside>
  )
}

// ── Client switcher ──────────────────────────────────────────────────────

function ClientSwitcher() {
  const { clients, clientId, client, ready, select, create, remove } = useClient()
  const [adding, setAdding] = useState(false)
  const [name,   setName]   = useState('')

  const submit = async e => {
    e.preventDefault()
    if (!name.trim()) return
    try {
      await create(name.trim())
      setName('')
      setAdding(false)
    } catch (err) { toast.error(err.message) }
  }

  const erase = async () => {
    const ok = window.confirm(
      `Erase "${client.name}" and everything imported for it (${client.upload_count} uploads, `
      + `${client.video_count} videos)? This cannot be undone.`)
    if (!ok) return
    try {
      const { deleted } = await remove(client.id)
      toast.success(`Erased ${deleted.videos} videos and ${deleted.metric_values} values`)
    } catch (err) { toast.error(err.message) }
  }

  return (
    <div className="px-3 py-3 border-b space-y-2" style={{ borderColor: 'var(--surface-border)' }}>
      <div className="text-xs uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Client</div>
      {ready && clients.length > 0 && (
        <select className="input w-full" value={clientId ?? ''} onChange={e => select(e.target.value)}>
          {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      )}
      {adding ? (
        <form onSubmit={submit} className="flex gap-1">
          <input autoFocus className="input w-full" placeholder="Client name" maxLength={200}
            value={name} onChange={e => setName(e.target.value)} />
          <button className="btn btn-primary" type="submit">Add</button>
        </form>
      ) : (
        <div className="flex gap-1">
          <button className="btn btn-ghost flex-1" onClick={() => setAdding(true)}>+ New</button>
          {client && <button className="btn btn-ghost" onClick={erase} title="Erase this client and its data">Delete</button>}
        </div>
      )}
      {client && (
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {client.video_count} videos · {client.upload_count} uploads
        </div>
      )}
    </div>
  )
}

// ── Icon components ──────────────────────────────────────────────────────

function GridIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <rect x="1" y="1" width="6" height="6" rx="1.5" fill="currentColor" opacity=".8"/>
      <rect x="9" y="1" width="6" height="6" rx="1.5" fill="currentColor" opacity=".8"/>
      <rect x="1" y="9" width="6" height="6" rx="1.5" fill="currentColor" opacity=".8"/>
      <rect x="9" y="9" width="6" height="6" rx="1.5" fill="currentColor" opacity=".8"/>
    </svg>
  )
}
function CalendarIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <rect x="1.5" y="3" width="13" height="11" rx="2" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M1.5 6.5h13" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M5 1.5v3M11 1.5v3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
      <rect x="4" y="9" width="2" height="2" rx=".5" fill="currentColor"/>
      <rect x="7" y="9" width="2" height="2" rx=".5" fill="currentColor"/>
      <rect x="10" y="9" width="2" height="2" rx=".5" fill="currentColor"/>
    </svg>
  )
}
function TagIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M2 2h5.5l6.2 6.2a1.5 1.5 0 0 1 0 2.1l-3.4 3.4a1.5 1.5 0 0 1-2.1 0L2 7.5V2z" stroke="currentColor" strokeWidth="1.4"/>
      <circle cx="5.5" cy="5.5" r="1" fill="currentColor"/>
    </svg>
  )
}
function DocIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M3 2h7l3 3v9a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M10 2v3h3" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M5 8h6M5 11h4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  )
}
function SearchIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M10.5 10.5l3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  )
}
function GearIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="2.5" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41"
        stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  )
}
