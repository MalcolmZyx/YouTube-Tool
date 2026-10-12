import { NavLink } from 'react-router-dom'
import clsx from 'clsx'

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
