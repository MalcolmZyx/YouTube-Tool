// Copied from apps/web (the admin app). Extract a shared package when both apps are polished.
import { Badge } from '../components/ui'

// How far to trust a finding, in words a creator understands.
const STRENGTH = {
  solid:           { label: 'Solid evidence',     color: 'green' },
  suggestive:      { label: 'Suggestive',         color: 'blue' },
  weak:            { label: 'Weak: a hint only',  color: 'amber' },
  not_enough_data: { label: 'Not enough data',    color: 'default' },
  info:            { label: 'Fact',               color: 'default' },
}

const num = v => (v >= 100 ? Math.round(v).toLocaleString() : Number(v).toFixed(1))

function VideoList({ rows, columns }) {
  if (!rows?.length) return null
  return (
    <table className="w-full text-sm mt-3">
      <thead>
        <tr style={{ color: 'var(--text-muted)' }}>
          <th className="text-left font-normal pb-1">Video</th>
          {columns.map(c => <th key={c.label} className="text-right font-normal pb-1">{c.label}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.video_id} className="border-t" style={{ borderColor: 'var(--surface-border)' }}>
            <td className="py-1.5 pr-4 truncate max-w-md">{r.title || r.video_id}</td>
            {columns.map(c => <td key={c.label} className="py-1.5 text-right font-mono">{c.format(r)}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const index = r => `${r.index.toFixed(1)}x`
const performanceColumns = [
  { label: 'Views',        format: r => num(r.views) },
  { label: 'Typical for age', format: r => num(r.expected) },
  { label: 'Versus typical',  format: index },
]
const ctrColumns = [
  { label: 'Impressions', format: r => num(r.impressions) },
  { label: 'Click rate',  format: r => `${r.ctr.toFixed(1)}%` },
  { label: 'Views',       format: r => num(r.views) },
]

function Extra({ finding }) {
  const d = finding.details
  if (finding.key === 'performance' && d.best) {
    return (
      <>
        <div className="mt-3 text-xs uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Doing best for their age</div>
        <VideoList rows={d.best} columns={performanceColumns} />
        <div className="mt-4 text-xs uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Doing worst for their age</div>
        <VideoList rows={d.worst} columns={performanceColumns} />
      </>
    )
  }
  if (finding.key === 'click_through' && d.candidates?.length) {
    return <VideoList rows={d.candidates} columns={ctrColumns} />
  }
  if (finding.key === 'retention' && d.candidates?.length) {
    return <VideoList rows={d.candidates} columns={[
      { label: 'Views', format: r => num(r.views) },
      { label: 'Average % viewed', format: r => `${r.percent_viewed.toFixed(0)}%` },
    ]} />
  }
  if (finding.key === 'title_features' && d.features) {
    return (
      <table className="w-full text-sm mt-3">
        <thead><tr style={{ color: 'var(--text-muted)' }}>
          <th className="text-left font-normal pb-1">Title has</th>
          <th className="text-right font-normal pb-1">Videos with / without</th>
          <th className="text-right font-normal pb-1">Index ratio</th>
          <th className="text-right font-normal pb-1">Adjusted p</th>
        </tr></thead>
        <tbody>
          {d.features.map(r => (
            <tr key={r.feature} className="border-t" style={{ borderColor: 'var(--surface-border)' }}>
              <td className="py-1.5">{r.feature}</td>
              <td className="py-1.5 text-right font-mono">{r.n_with} / {r.n_without}</td>
              <td className="py-1.5 text-right font-mono">{r.ratio == null ? '-' : `${r.ratio.toFixed(2)}x`}</td>
              <td className="py-1.5 text-right font-mono">{r.p_adjusted == null ? '-' : r.p_adjusted.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }
  if (finding.key === 'duration' && d.formats) {
    return (
      <ul className="mt-3 text-sm space-y-1">
        {d.formats.map(r => (
          <li key={r.format}>{r.format} ({r.videos} videos): {r.rho == null ? 'too few to measure'
            : `rank correlation ${r.rho.toFixed(2)}, 95% range ${r.low.toFixed(2)} to ${r.high.toFixed(2)}`}</li>
        ))}
      </ul>
    )
  }
  if (finding.key === 'cadence' && d.by_weekday) {
    const max = Math.max(...Object.values(d.by_weekday), 1)
    return (
      <div className="mt-3 flex items-end gap-2 h-20">
        {Object.entries(d.by_weekday).map(([day, n]) => (
          <div key={day} className="flex-1 flex flex-col items-center justify-end h-full" title={`${day}: ${n} uploads`}>
            <div className="w-full rounded-t" style={{ height: `${(n / max) * 100}%`, background: 'var(--brand)', minHeight: n ? 2 : 0 }} />
            <span className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{day.slice(0, 3)}</span>
          </div>
        ))}
      </div>
    )
  }
  return null
}

export function FindingCard({ finding }) {
  const s = STRENGTH[finding.strength] || STRENGTH.info
  return (
    <section className="card mb-4">
      <div className="flex items-center justify-between gap-3 mb-2">
        <h2 className="font-display font-bold text-base">{finding.title}</h2>
        <Badge color={s.color}>{s.label}</Badge>
      </div>
      <p className="text-sm">{finding.headline}</p>
      <Extra finding={finding} />
      {finding.caveats.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs list-disc pl-4" style={{ color: 'var(--text-muted)' }}>
          {finding.caveats.map(c => <li key={c}>{c}</li>)}
        </ul>
      )}
    </section>
  )
}

