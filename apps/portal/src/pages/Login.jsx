import { useState } from 'react'
import { useAuth } from '../hooks/useAuth'

export default function Login() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async e => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try { await signIn(email.trim(), password) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4">
        <div>
          <h1 className="font-display font-bold text-xl">Your channel report</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>Sign in with the details you were sent.</p>
        </div>
        <label className="block text-sm">
          Email
          <input className="input w-full mt-1" type="email" autoComplete="username" required
            value={email} onChange={e => setEmail(e.target.value)} />
        </label>
        <label className="block text-sm">
          Password
          <input className="input w-full mt-1" type="password" autoComplete="current-password" required
            value={password} onChange={e => setPassword(e.target.value)} />
        </label>
        {error && <p role="alert" className="text-sm" style={{ color: 'var(--brand)' }}>{error}</p>}
        <button className="btn btn-primary w-full" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          Accounts are created by invitation. If you need access, contact the person who sent you this link.
        </p>
      </form>
    </div>
  )
}
