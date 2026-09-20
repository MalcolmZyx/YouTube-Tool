import clsx from 'clsx'

/* ── MetricCard ─────────────────────────────────────────────────────────── */
export function MetricCard({ label, value, sub, accent }) {
  const colors = {
    red:   { bg: 'rgba(255,60,60,0.08)',  border: 'rgba(255,60,60,0.2)',  text: '#ff3c3c' },
    green: { bg: 'rgba(74,222,128,0.08)', border: 'rgba(74,222,128,0.2)', text: '#4ade80' },
    blue:  { bg: 'rgba(96,165,250,0.08)', border: 'rgba(96,165,250,0.2)', text: '#60a5fa' },
    amber: { bg: 'rgba(251,191,36,0.08)', border: 'rgba(251,191,36,0.2)', text: '#fbbf24' },
  }
  const c = colors[accent] || colors.blue

  return (
    <div className="rounded-xl p-4 flex flex-col gap-1"
      style={{ background: c.bg, border: `1px solid ${c.border}` }}>
      <span className="text-xs font-mono uppercase tracking-widest" style={{ color: c.text }}>{label}</span>
      <span className="font-display text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>{value}</span>
      {sub && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{sub}</span>}
    </div>
  )
}

/* ── TagBar ─────────────────────────────────────────────────────────────── */
export function TagBar({ tag, score, maxScore, color = 'var(--brand)' }) {
  const pct = maxScore > 0 ? (score / maxScore) * 100 : 0
  return (
    <div className="flex items-center gap-3 group">
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-mono truncate" style={{ color: 'var(--text-primary)' }}>{tag}</span>
          <span className="text-xs ml-2 flex-shrink-0" style={{ color: 'var(--text-muted)' }}>{score.toFixed(1)}</span>
        </div>
        <div className="h-1.5 rounded-full" style={{ background: 'rgba(255,255,255,0.06)' }}>
          <div className="h-full rounded-full transition-all duration-500"
            style={{ width: `${pct}%`, background: color }} />
        </div>
      </div>
    </div>
  )
}

/* ── Skeleton ────────────────────────────────────────────────────────────── */
export function Skeleton({ className }) {
  return <div className={clsx('skeleton', className)} />
}

export function SkeletonCard() {
  return (
    <div className="card space-y-3">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-8 w-24" />
      <Skeleton className="h-3 w-20" />
    </div>
  )
}

/* ── EmptyState ──────────────────────────────────────────────────────────── */
export function EmptyState({ icon = '📂', title, desc, action }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <span className="text-5xl mb-4">{icon}</span>
      <h3 className="font-display font-bold text-lg mb-1" style={{ color: 'var(--text-primary)' }}>{title}</h3>
      {desc && <p className="text-sm mb-4 max-w-xs" style={{ color: 'var(--text-muted)' }}>{desc}</p>}
      {action}
    </div>
  )
}

/* ── PageHeader ──────────────────────────────────────────────────────────── */
export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="font-display font-bold text-2xl" style={{ color: 'var(--text-primary)' }}>{title}</h1>
        {subtitle && <p className="text-sm mt-0.5" style={{ color: 'var(--text-muted)' }}>{subtitle}</p>}
      </div>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </div>
  )
}

/* ── Select ──────────────────────────────────────────────────────────────── */
export function Select({ value, onChange, options, className }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className={clsx('input pr-8 cursor-pointer', className)}
      style={{ appearance: 'none', backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M2 4l4 4 4-4' stroke='%238d8d99' strokeWidth='1.5' fill='none'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center' }}
    >
      {options.map(o => (
        <option key={o.value ?? o} value={o.value ?? o}
          style={{ background: '#1a1a1f' }}>
          {o.label ?? o}
        </option>
      ))}
    </select>
  )
}

/* ── Badge ───────────────────────────────────────────────────────────────── */
export function Badge({ children, color = 'default' }) {
  const styles = {
    default: { background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' },
    green:   { background: 'rgba(74,222,128,0.12)',  color: '#4ade80' },
    red:     { background: 'rgba(255,60,60,0.12)',   color: '#ff6b6b' },
    blue:    { background: 'rgba(96,165,250,0.12)',  color: '#60a5fa' },
    amber:   { background: 'rgba(251,191,36,0.12)',  color: '#fbbf24' },
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-mono"
      style={styles[color] || styles.default}>
      {children}
    </span>
  )
}
