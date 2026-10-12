import { useState, useEffect, useRef } from 'react'
import toast from 'react-hot-toast'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts'
import { useApi } from '../hooks/useApi'
import DataTable from '../components/DataTable'
import { MetricCard, EmptyState, PageHeader, Select, SkeletonCard, Skeleton } from '../components/ui'

const ACCENT_COLORS = ['#ff3c3c','#ff6b6b','#fbbf24','#4ade80','#60a5fa','#c084fc','#f472b6']

export default function Dashboard() {
  const { get, upload, loading } = useApi()
  const [dataset,    setDataset]    = useState(null)
  const [duration,   setDuration]   = useState(null)
  const [durationMetric, setDurationMetric] = useState('Views')
  const [numRows,    setNumRows]    = useState('')
  const fileRef = useRef()

  // ── Load cached dataset on mount ──────────────────────────────────────
  useEffect(() => {
    get('/dashboard')
      .then(d => { setDataset(d); fetchDuration('Views', d) })
      .catch(() => {})
  }, [])  // eslint-disable-line

  const fetchDuration = async (metric, ds = dataset) => {
    if (!ds) return
    try {
      const d = await get('/duration', { metric })
      setDuration(d)
    } catch {}
  }

  // ── Upload ────────────────────────────────────────────────────────────
  const handleUpload = async e => {
    const file = e.target.files?.[0]
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)
    if (numRows) fd.append('num_rows', numRows)

    toast.loading('Processing file…', { id: 'upload' })
    try {
      const ds = await upload('/dashboard/upload', fd)
      setDataset(ds)
      fetchDuration(durationMetric, ds)
      toast.success(`Loaded ${ds.rows?.length ?? 0} videos`, { id: 'upload' })
    } catch (err) {
      toast.error(err.message, { id: 'upload' })
    }
  }

  const handleMetricChange = val => {
    setDurationMetric(val)
    fetchDuration(val)
  }

  // ── Summary stats ─────────────────────────────────────────────────────
  const stats = dataset ? computeStats(dataset) : null

  return (
    <div className="animate-fade-in">
      <PageHeader title="Analytics Dashboard" subtitle="Upload your YouTube Studio export to begin">
        {dataset && (
          <Select
            value={durationMetric}
            onChange={handleMetricChange}
            options={[
              ...(dataset.numeric_columns || []),
              ...(dataset.percent_columns || []),
            ].map(c => ({ value: c, label: c }))}
            className="w-40"
          />
        )}
        <button className="btn btn-primary" onClick={() => fileRef.current?.click()}>
          <UploadIcon />
          {dataset ? 'Re-upload' : 'Upload File'}
        </button>
        <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv"
          className="hidden" onChange={handleUpload} />
      </PageHeader>

      {/* Row limit input */}
      <div className="flex items-center gap-2 mb-6">
        <input
          type="number" placeholder="Row limit (optional)"
          value={numRows} onChange={e => setNumRows(e.target.value)}
          className="input w-48" min={1}
        />
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Leave blank to load all rows</span>
      </div>

      {/* Loading skeleton */}
      {loading && !dataset && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      )}

      {/* Empty state */}
      {!dataset && !loading && (
        <EmptyState
          icon="📊"
          title="No data loaded"
          desc="Upload an Excel or CSV export from YouTube Studio to see your analytics."
          action={
            <button className="btn btn-primary" onClick={() => fileRef.current?.click()}>
              <UploadIcon /> Choose file
            </button>
          }
        />
      )}

      {dataset && (
        <>
          {/* KPI Cards */}
          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <MetricCard accent="red"   label="Videos"     value={stats.totalVideos}   />
              <MetricCard accent="blue"  label="Total Views" value={stats.totalViews}   sub="across all videos" />
              <MetricCard accent="amber" label="Avg CTR"     value={stats.avgCTR}       sub="click-through rate" />
              <MetricCard accent="green" label="Avg Views"   value={stats.avgViews}     sub="per video" />
            </div>
          )}

          {/* Duration Buckets Chart */}
          {duration?.buckets?.length > 0 && (
            <section className="card mb-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-display font-bold text-base">
                  Average {durationMetric} by Duration Bucket
                </h2>
                <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                  {duration.buckets.reduce((s, b) => s + b.count, 0)} videos
                </span>
              </div>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={duration.buckets} margin={{ top: 4, right: 20, bottom: 24, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: 'var(--text-muted)', fontFamily: 'DM Mono' }}
                    angle={-30} textAnchor="end" />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)', fontFamily: 'DM Mono' }}
                    tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(0)}k` : v} />
                  <Tooltip
                    contentStyle={{ background: '#1a1a1f', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontFamily: 'DM Mono', fontSize: 12 }}
                    itemStyle={{ color: 'var(--text-primary)' }}
                    formatter={(v, n) => [v.toLocaleString(), `Avg ${durationMetric}`]}
                    labelStyle={{ color: 'var(--text-muted)' }}
                  />
                  <Bar dataKey="mean" radius={[4, 4, 0, 0]}>
                    {duration.buckets.map((_, i) => (
                      <Cell key={i} fill={ACCENT_COLORS[i % ACCENT_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>

              {/* Bucket summary mini-table */}
              <div className="mt-4 overflow-x-auto">
                <table className="data-table text-xs">
                  <thead>
                    <tr>
                      {['Bucket','Count','Mean','Median','Total'].map(h => <th key={h}>{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {duration.buckets.map((b, i) => (
                      <tr key={i}>
                        <td className="font-mono">{b.bucket}</td>
                        <td className="text-right font-mono">{b.count}</td>
                        <td className="text-right font-mono">{b.mean?.toLocaleString()}</td>
                        <td className="text-right font-mono">{b.median?.toLocaleString()}</td>
                        <td className="text-right font-mono">{b.total?.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Main data table */}
          <section className="card">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-display font-bold text-base">
                Video Performance Table
                <span className="ml-2 text-xs font-mono font-normal" style={{ color: 'var(--text-muted)' }}>
                  drag columns to reorder · click header to sort
                </span>
              </h2>
              <span className="text-xs font-mono px-2 py-1 rounded-sm"
                style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)' }}>
                {dataset.rows?.length} rows
              </span>
            </div>
            <DataTable
              rows={dataset.rows || []}
              columns={dataset.columns || []}
              textCols={dataset.text_columns || []}
              numericCols={dataset.numeric_columns || []}
              percentCols={dataset.percent_columns || []}
              shares={dataset.shares || {}}
              videoIdCol={dataset.video_id_col}
              totalRow={dataset.total_row}
            />
          </section>
        </>
      )}
    </div>
  )
}

function computeStats(ds) {
  const rows = ds.rows || []
  const viewsCol = (ds.numeric_columns || []).find(c => c.toLowerCase().includes('view')) || 'Views'
  const ctrCol   = (ds.percent_columns  || []).find(c => c.toLowerCase().includes('ctr')
    || c.toLowerCase().includes('click')) || null

  const totalViews = rows.reduce((s, r) => s + (parseFloat(r[viewsCol]) || 0), 0)
  const avgViews   = rows.length ? totalViews / rows.length : 0
  const avgCTR     = ctrCol && rows.length
    ? rows.reduce((s, r) => s + (parseFloat(r[ctrCol]) || 0), 0) / rows.length
    : null

  return {
    totalVideos: rows.length.toLocaleString(),
    totalViews:  totalViews >= 1e6 ? `${(totalViews/1e6).toFixed(1)}M` : totalViews >= 1e3 ? `${(totalViews/1e3).toFixed(0)}K` : totalViews.toFixed(0),
    avgViews:    avgViews   >= 1e3 ? `${(avgViews /1e3).toFixed(1)}K` : avgViews.toFixed(0),
    avgCTR:      avgCTR !== null ? `${avgCTR.toFixed(1)}%` : 'N/A',
  }
}

function UploadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M7 1v8M4 4l3-3 3 3M2 10v2a1 1 0 001 1h8a1 1 0 001-1v-2"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}
