import { useEffect, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { useClient } from '../hooks/useClient'
import { Badge, EmptyState, PageHeader, Skeleton } from '../components/ui'

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

function FindingCard({ finding }) {
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

export default function Audit() {
  const { get, loading } = useApi()
  const { client, clientId, scoped, version } = useClient()
  const [audit, setAudit] = useState(null)

  useEffect(() => {
    setAudit(null)
    if (!clientId) return
    get(scoped('/audit')).then(setAudit).catch(() => {})
  }, [clientId, version])  // eslint-disable-line

  if (!audit && !loading) {
    return <EmptyState icon="🔎" title="No audit yet"
      desc={clientId ? 'Upload an export for this client on the Dashboard first.' : 'Create a client in the sidebar first.'} />
  }

  return (
    <div className="animate-fade-in max-w-4xl">
      <PageHeader title="Channel Audit"
        subtitle={client ? `${client.name}${audit ? ` · ${audit.videos} videos · ages measured to ${audit.as_of}` : ''}` : ''} />
      {!audit && <Skeleton className="h-40 w-full" />}
      {audit && (
        <>
          <p className="text-xs mb-4" style={{ color: 'var(--text-muted)' }}>
            Every number is computed from the export, not written by a model. "Ages measured to" comes from {audit.as_of_source}.
          </p>
          {audit.findings.map(f => <FindingCard key={f.key} finding={f} />)}
        </>
      )}
    </div>
  )
}
