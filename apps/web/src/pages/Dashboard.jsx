import { useState, useEffect, useRef } from 'react'
import toast from 'react-hot-toast'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts'
import { useApi } from '../hooks/useApi'
import { useClient } from '../hooks/useClient'
import DataTable from '../components/DataTable'
import { MetricCard, EmptyState, PageHeader, Select, SkeletonCard, Skeleton } from '../components/ui'

const ACCENT_COLORS = ['#ff3c3c','#ff6b6b','#fbbf24','#4ade80','#60a5fa','#c084fc','#f472b6']

export default function Dashboard() {
  const { get, post, upload, loading } = useApi()
  const { client, clientId, scoped, version, dataChanged } = useClient()
  const [dataset,    setDataset]    = useState(null)
  const [duration,   setDuration]   = useState(null)
  const [durationMetric, setDurationMetric] = useState('Views')
  const fileRef = useRef()

  // ── Load the selected client's data, and again when it changes ─────────
  useEffect(() => {
    setDataset(null)
    setDuration(null)
    if (!clientId) return
    get(scoped('/dashboard'))
      .then(d => { setDataset(d); fetchDuration('Views', d) })
      .catch(() => {})
  }, [clientId, version])  // eslint-disable-line

  const fetchDuration = async (metric, ds = dataset) => {
    if (!ds) return
    try {
      const d = await get(scoped('/duration'), { metric })
      setDuration(d)
    } catch {}
  }

  // ── Upload ────────────────────────────────────────────────────────────
  const handleUpload = async e => {
    const file = e.target.files?.[0]
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)

    toast.loading('Processing file…', { id: 'upload' })
    try {
      const result = await upload(`/clients/${clientId}/uploads`, fd)
      await dataChanged()
      const note = result.duplicate ? 'This file was already imported' : `Imported ${result.videos} videos`
      toast.success(note, { id: 'upload' })
      result.warnings?.forEach(w => toast(w, { duration: 8000 }))
    } catch (err) {
      toast.error(err.message, { id: 'upload' })
    }
  }

  // Fetch public YouTube details (description, tags, thumbnail); needs the API key from Settings.
  const handleEnrich = async () => {
    toast.loading('Fetching YouTube details…', { id: 'enrich' })
    try {
      const r = await post(`/clients/${clientId}/enrich`)
      await dataChanged()
      toast.success(
        r.requested === 0 ? 'Details are already up to date'
          : `Fetched ${r.stored} videos${r.unavailable ? `, ${r.unavailable} not public` : ''}`,
        { id: 'enrich' })
    } catch (err) {
      toast.error(err.message, { id: 'enrich' })
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
      <PageHeader title="Analytics Dashboard" subtitle={client ? `Client: ${client.name}` : 'Create a client, then upload their YouTube Studio export'}>
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
        {dataset && (
          <button className="btn btn-ghost" onClick={handleEnrich} title="Fetch tags, descriptions and thumbnails from YouTube">
            Fetch YouTube details
          </button>
        )}
        <button className="btn btn-primary" disabled={!clientId} onClick={() => fileRef.current?.click()}>
          <UploadIcon />
          {dataset ? 'Re-upload' : 'Upload File'}
        </button>
        <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv"
          className="hidden" onChange={handleUpload} />
      </PageHeader>

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
          desc={clientId ? 'Upload an Excel or CSV export from YouTube Studio to see analytics for this client.' : 'Create a client in the sidebar first.'}
          action={clientId &&
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
              <MetricCard accent="amber" label="CTR"         value={stats.avgCTR}       sub="channel click-through rate" />
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
  const numeric = ds.numeric_columns || []
  // Prefer the column named exactly "Views": "Average view duration" also contains "view".
  const viewsCol = numeric.find(c => c.toLowerCase() === 'views') || numeric.find(c => c.toLowerCase().includes('view')) || 'Views'
  const ctrCol   = (ds.percent_columns || []).find(c => c.toLowerCase().includes('ctr')
    || c.toLowerCase().includes('click')) || null

  // The export's Total row is the channel's own figure. It includes views the listed videos do not (deleted
  // videos and the like), so it is preferred; the sum over videos is the fallback.
  const totalRow = ds.total_row || {}
  const videoSum = rows.reduce((s, r) => s + (parseFloat(r[viewsCol]) || 0), 0)
  const totalViews = parseFloat(totalRow[viewsCol]) || videoSum
  const avgViews   = rows.length ? videoSum / rows.length : 0

  // A rate must not be averaged across videos: use the Total row's rate, else average only the videos that
  // reported one (a blank or 0 means "no impressions", not a 0% rate).
  const reported = ctrCol ? rows.map(r => parseFloat(r[ctrCol])).filter(v => v > 0) : []
  const ctr = (ctrCol && parseFloat(totalRow[ctrCol])) || (reported.length ? reported.reduce((a, v) => a + v, 0) / reported.length : null)

  return {
    totalVideos: rows.length.toLocaleString(),
    totalViews:  totalViews >= 1e6 ? `${(totalViews/1e6).toFixed(1)}M` : totalViews >= 1e3 ? `${(totalViews/1e3).toFixed(0)}K` : totalViews.toFixed(0),
    avgViews:    avgViews   >= 1e3 ? `${(avgViews /1e3).toFixed(1)}K` : avgViews.toFixed(0),
    avgCTR:      ctr !== null ? `${ctr.toFixed(1)}%` : 'N/A',
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
