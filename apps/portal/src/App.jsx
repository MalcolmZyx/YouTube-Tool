import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import Empty from './components/Empty'
import { PortalDataProvider, usePortalData } from './hooks/usePortalData'
import { useAuth } from './hooks/useAuth'
import { configured } from './supabase'
import Audit from './pages/Audit'
import Dashboard from './pages/Dashboard'
import Focus from './pages/Focus'
import Requests from './pages/Requests'
import Upload from './pages/Upload'
import Login from './pages/Login'

const link = ({ isActive }) => `px-3 py-1.5 rounded-lg text-sm ${isActive ? 'font-semibold' : ''}`
const linkStyle = ({ isActive }) => (isActive
  ? { background: 'var(--brand-dim)', color: 'var(--brand)' } : { color: 'var(--text-muted)' })

function Shell() {
  const { user, signOut } = useAuth()
  const { clients, clientId, setClientId, state } = usePortalData()

  return (
    <div className="min-h-screen">
      <header className="border-b flex items-center gap-4 px-6 py-3 flex-wrap"
        style={{ background: 'var(--surface-card)', borderColor: 'var(--surface-border)' }}>
        <span className="font-display font-bold" style={{ color: 'var(--brand)' }}>Your channel report</span>
        <nav className="flex gap-1">
          <NavLink to="/" end className={link} style={linkStyle}>Dashboard</NavLink>
          <NavLink to="/audit" className={link} style={linkStyle}>Audit</NavLink>
          <NavLink to="/upload" className={link} style={linkStyle}>Upload</NavLink>
          <NavLink to="/requests" className={link} style={linkStyle}>Requests</NavLink>
          <NavLink to="/focus" className={link} style={linkStyle}>Focus</NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          {clients.length > 1 && (
            <select className="input" value={clientId ?? ''} onChange={e => setClientId(e.target.value)}>
              {clients.map(c => <option key={c.id} value={c.id}>{c.display_name}</option>)}
            </select>
          )}
          <span style={{ color: 'var(--text-muted)' }}>{user.email}</span>
          <button className="btn btn-ghost" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <main className="max-w-(--breakpoint-2xl) mx-auto px-6 py-8">
        {state === 'error' ? (
          <Empty title="Something went wrong" desc="Your report could not be loaded. Try again in a moment." />
        ) : state === 'ready' && clients.length === 0 ? (
          <Empty title="No report for this account" desc="This account is not linked to a channel yet. Please contact the person who invited you." />
        ) : (
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/requests" element={<Requests />} />
            <Route path="/focus" element={<Focus />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        )}
      </main>
    </div>
  )
}

export default function App() {
  const { user, ready } = useAuth()
  if (!configured) {
    return <Empty title="Not configured" desc="Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY (see .env.example)." />
  }
  if (!ready) return null
  if (!user) return <Login />
  return (
    <PortalDataProvider>
      <Shell />
    </PortalDataProvider>
  )
}
