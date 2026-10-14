import Empty from '../components/Empty'
import { FindingCard } from '../components/Findings'
import { usePortalData } from '../hooks/usePortalData'

export default function Audit() {
  const { snapshots, client } = usePortalData()
  const snapshot = snapshots.audit
  if (!snapshot) return <Empty title="No audit published yet" desc="Your audit will appear here once it is ready." />
  const audit = snapshot.payload

  return (
    <div className="animate-fade-in max-w-4xl">
      <h1 className="font-display font-bold text-2xl mb-1">Channel audit</h1>
      <p className="text-sm mb-1" style={{ color: 'var(--text-muted)' }}>
        {client?.display_name} · {audit.videos} videos · ages measured to {audit.as_of}
      </p>
      <p className="text-xs mb-4" style={{ color: 'var(--text-muted)' }}>
        Published {new Date(snapshot.published_at).toLocaleDateString()}. Every number is computed from your export, not written by a model.
        "Ages measured to" comes from {audit.as_of_source}.
      </p>
      {audit.findings.map(f => <FindingCard key={f.key} finding={f} />)}
    </div>
  )
}
