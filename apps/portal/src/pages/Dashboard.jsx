import { useMemo, useState } from 'react'
import { MetricCard } from '../components/ui'
import { usePortalData } from '../hooks/usePortalData'
import Empty from '../components/Empty'

const compact = v => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : Math.round(v).toLocaleString())

function cell(value, column, percent) {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value !== 'number') return String(value)
  if (percent.has(column)) return `${value.toFixed(1)}%`
  return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

export default function Dashboard() {
  const { snapshots } = usePortalData()
  const data = snapshots.dashboard?.payload
  const [sort, setSort] = useState({ column: 'Views', desc: true })

  const percent = useMemo(() => new Set(data?.percent_columns ?? []), [data])
  const rows = useMemo(() => {
    if (!data) return []
    return [...data.rows].sort((a, b) => {
      const x = a[sort.column], y = b[sort.column]
      if (x === y) return 0
      if (x === null || x === '' || x === undefined) return 1
      if (y === null || y === '' || y === undefined) return -1
      return (x > y ? 1 : -1) * (sort.desc ? -1 : 1)
    })
  }, [data, sort])

  if (!data) return <Empty title="Nothing published yet" desc="Your report has not been published. You will see it here once it is ready." />

  const total = data.total_row ?? {}
  const views = data.rows.reduce((s, r) => s + (Number(r.Views) || 0), 0)
  const ctr = Number(total['Impressions click-through rate (%)']) || null
  const columns = data.columns.filter(c => c !== data.video_id_col)

  return (
    <div className="animate-fade-in">
      <h1 className="font-display font-bold text-2xl mb-1">Dashboard</h1>
      <p className="text-xs mb-6" style={{ color: 'var(--text-muted)' }}>
        A snapshot published {new Date(snapshots.dashboard.published_at).toLocaleDateString()}. It does not update until a new report is published.
      </p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <MetricCard accent="red" label="Videos" value={data.rows.length.toLocaleString()} />
        <MetricCard accent="blue" label="Total views" value={compact(Number(total.Views) || views)} sub="across the channel" />
        <MetricCard accent="amber" label="CTR" value={ctr ? `${ctr.toFixed(1)}%` : 'N/A'} sub="click-through rate" />
        <MetricCard accent="green" label="Avg views" value={compact(data.rows.length ? views / data.rows.length : 0)} sub="per video" />
      </div>

      <section className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: 'var(--text-muted)' }}>
              <th className="text-left font-normal pb-2 pr-4">Video</th>
              {columns.filter(c => c !== 'Video title').map(c => (
                <th key={c} className="text-right font-normal pb-2 px-2 whitespace-nowrap cursor-pointer select-none"
                  onClick={() => setSort(s => ({ column: c, desc: s.column === c ? !s.desc : true }))}>
                  {c}{sort.column === c ? (sort.desc ? ' ↓' : ' ↑') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r[data.video_id_col]} className="border-t" style={{ borderColor: 'var(--surface-border)' }}>
                <td className="py-1.5 pr-4 max-w-xs truncate">
                  <a href={`https://www.youtube.com/watch?v=${encodeURIComponent(r[data.video_id_col])}`}
                    target="_blank" rel="noopener noreferrer">{r['Video title'] || r[data.video_id_col]}</a>
                </td>
                {columns.filter(c => c !== 'Video title').map(c => (
                  <td key={c} className="py-1.5 px-2 text-right font-mono whitespace-nowrap">{cell(r[c], c, percent)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
