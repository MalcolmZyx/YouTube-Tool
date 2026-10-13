import { useState, useEffect, useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts'
import { useApi } from '../hooks/useApi'
import { useClient } from '../hooks/useClient'
import { PageHeader, Select, EmptyState, Skeleton } from '../components/ui'

const DOW_COLORS = ['#60a5fa','#4ade80','#fbbf24','#f472b6','#c084fc','#fb923c','#38bdf8']

// ── Calendar colours ──────────────────────────────────────────────────────
function heatColor(value, max) {
  if (!value || value === 0 || max === 0) return 'rgba(255,255,255,0.04)'
  const t = Math.min(value / max, 1)
  // gradient: dim yellow → orange → red
  if (t < 0.33) {
    const r = Math.round(255 * t * 3), g = Math.round(220 * t * 3)
    return `rgba(${r},${g},0,0.55)`
  }
  if (t < 0.66) {
    const p = (t - 0.33) / 0.33
    return `rgba(255,${Math.round(170 - p * 100)},0,${0.55 + p * 0.25})`
  }
  const p = (t - 0.66) / 0.34
  return `rgba(255,${Math.round(70 - p * 70)},0,${0.8 + p * 0.2})`
}

// ── Build months from daily data ──────────────────────────────────────────
function buildCalendarMonths(daily) {
  if (!daily?.length) return []
  const byDate = {}
  daily.forEach(d => { byDate[d.date] = d.value })

  const dates = daily.map(d => new Date(d.date)).sort((a, b) => a - b)
  const first = new Date(dates[0].getFullYear(), dates[0].getMonth(), 1)
  const last  = dates[dates.length - 1]

  const months = []
  let cur = new Date(first)
  while (cur <= last) {
    const yr = cur.getFullYear(), mo = cur.getMonth()
    const daysInMonth = new Date(yr, mo + 1, 0).getDate()
    const firstDow    = new Date(yr, mo, 1).getDay() // 0=Sun

    const weeks = []
    let week = new Array(7).fill(null)
    for (let d = 1; d <= daysInMonth; d++) {
      const dow  = (firstDow + d - 1) % 7
      const key  = `${yr}-${String(mo+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`
      week[dow]  = { day: d, date: key, value: byDate[key] ?? 0 }
      if (dow === 6 || d === daysInMonth) {
        weeks.push([...week])
        week = new Array(7).fill(null)
      }
    }
    months.push({ yr, mo, weeks })
    cur = new Date(yr, mo + 1, 1)
  }
  return months
}

const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
const DAY_LABELS  = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']

export default function Heatmap() {
  const { get, loading } = useApi()
  const { clientId, scoped, version } = useClient()
  const [data,   setData]   = useState(null)
  const [metric, setMetric] = useState('Views')
  const [tooltip, setTooltip] = useState(null)

  const fetchData = async (m = metric) => {
    if (!clientId) { setData(null); return }
    try {
      const d = await get(scoped('/heatmap'), { metric: m })
      setData(d)
      setMetric(m)
    } catch {}
  }

  useEffect(() => { fetchData() }, [clientId, version])  // eslint-disable-line

  const months = useMemo(() => buildCalendarMonths(data?.calendar), [data])
  const maxVal  = useMemo(() => Math.max(...(data?.calendar?.map(d => d.value) ?? [0])), [data])
  const dowData = data?.day_of_week ?? []

  if (!data && !loading) {
    return (
      <EmptyState icon="📅" title="No data loaded"
        desc="Pick a client and upload an export on the Dashboard first." />
    )
  }

  return (
    <div className="animate-fade-in">
      <PageHeader title="Calendar Heatmap" subtitle="Video publish dates plotted against performance">
        {data?.available_metrics?.length > 0 && (
          <Select
            value={metric}
            onChange={m => fetchData(m)}
            options={data.available_metrics.map(c => ({ value: c, label: c }))}
            className="w-44"
          />
        )}
      </PageHeader>

      {loading && (
        <div className="grid grid-cols-2 gap-6">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-52" />)}
        </div>
      )}

      {!loading && data && (
        <>
          {/* ── Calendar grid ────────────────────────────────────────── */}
          <section className="card mb-6">
            <div className="flex items-center gap-4 mb-4">
              <h2 className="font-display font-bold text-base">Monthly Calendar — {metric}</h2>
              {/* Colour scale legend */}
              <div className="flex items-center gap-1 ml-auto">
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Low</span>
                {[0.1,0.3,0.55,0.75,1].map(t => (
                  <div key={t} className="w-5 h-3 rounded-xs"
                    style={{ background: heatColor(t * maxVal, maxVal) }} />
                ))}
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>High</span>
              </div>
            </div>

            <div className="grid gap-6"
              style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
              {months.map(({ yr, mo, weeks }) => (
                <div key={`${yr}-${mo}`}>
                  <div className="font-display font-bold text-xs mb-2 tracking-wide uppercase"
                    style={{ color: 'var(--text-muted)' }}>
                    {MONTH_NAMES[mo]} {yr}
                  </div>
                  {/* Day labels */}
                  <div className="grid grid-cols-7 mb-1">
                    {DAY_LABELS.map(d => (
                      <div key={d} className="text-center text-xs font-mono"
                        style={{ color: 'var(--text-muted)', fontSize: 9 }}>{d}</div>
                    ))}
                  </div>
                  {weeks.map((week, wi) => (
                    <div key={wi} className="grid grid-cols-7 gap-0.5 mb-0.5">
                      {week.map((cell, ci) => cell
                        ? (
                          <div key={ci}
                            className="relative rounded-xs flex flex-col items-center justify-center cursor-default transition-all duration-150 hover:scale-110 hover:z-10"
                            style={{ background: heatColor(cell.value, maxVal), aspectRatio: '1', minHeight: 28 }}
                            onMouseEnter={() => setTooltip(cell)}
                            onMouseLeave={() => setTooltip(null)}
                          >
                            <span className="text-xs leading-none font-mono"
                              style={{ color: cell.value > 0 ? 'white' : 'rgba(255,255,255,0.2)', fontSize: 8 }}>
                              {cell.day}
                            </span>
                            {cell.value > 0 && (
                              <span style={{ fontSize: 7, color: 'rgba(255,255,255,0.7)', fontFamily: 'DM Mono' }}>
                                {cell.value >= 1000 ? `${(cell.value/1000).toFixed(0)}k` : cell.value}
                              </span>
                            )}
                          </div>
                        )
                        : <div key={ci} />
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </div>

            {/* Tooltip */}
            {tooltip && (
              <div className="fixed bottom-6 right-8 rounded-xl px-4 py-3 text-sm z-50 pointer-events-none"
                style={{ background: '#1a1a1f', border: '1px solid rgba(255,255,255,0.12)', boxShadow: '0 8px 32px rgba(0,0,0,0.6)' }}>
                <div className="font-mono text-xs" style={{ color: 'var(--text-muted)' }}>{tooltip.date}</div>
                <div className="font-display font-bold text-lg mt-0.5">{tooltip.value > 0 ? tooltip.value.toLocaleString() : 'No videos'}</div>
                <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{metric}</div>
              </div>
            )}
          </section>

          {/* ── Day-of-Week charts ────────────────────────────────────── */}
          {dowData.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <section className="card">
                <h2 className="font-display font-bold text-base mb-4">Avg {metric} per Video by Day</h2>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={dowData} layout="vertical"
                    margin={{ top: 0, right: 60, bottom: 0, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 9, fill: 'var(--text-muted)', fontFamily: 'DM Mono' }}
                      tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(0)}k` : v} />
                    <YAxis type="category" dataKey="day" tick={{ fontSize: 10, fill: 'var(--text-muted)', fontFamily: 'DM Mono' }} width={36} />
                    <Tooltip
                      contentStyle={{ background: '#1a1a1f', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontFamily: 'DM Mono', fontSize: 11 }}
                      formatter={v => [v.toLocaleString(), `Avg ${metric}`]}
                      labelStyle={{ color: 'var(--text-muted)' }}
                    />
                    <Bar dataKey="avg" radius={[0, 4, 4, 0]}>
                      {dowData.map((_, i) => <Cell key={i} fill={DOW_COLORS[i % DOW_COLORS.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="card">
                <h2 className="font-display font-bold text-base mb-4">Total {metric} + Video Count by Day</h2>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={dowData} layout="vertical"
                    margin={{ top: 0, right: 80, bottom: 0, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 9, fill: 'var(--text-muted)', fontFamily: 'DM Mono' }}
                      tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(0)}k` : v} />
                    <YAxis type="category" dataKey="day" tick={{ fontSize: 10, fill: 'var(--text-muted)', fontFamily: 'DM Mono' }} width={36} />
                    <Tooltip
                      contentStyle={{ background: '#1a1a1f', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontFamily: 'DM Mono', fontSize: 11 }}
                      formatter={(v, n, p) => {
                        const entry = dowData[dowData.findIndex(d => d.day === p?.payload?.day)]
                        return [`${v.toLocaleString()} (${entry?.count ?? ''} videos)`, `Total ${metric}`]
                      }}
                      labelStyle={{ color: 'var(--text-muted)' }}
                    />
                    <Bar dataKey="total" radius={[0, 4, 4, 0]}>
                      {dowData.map((_, i) => <Cell key={i} fill={DOW_COLORS[i % DOW_COLORS.length]} opacity={0.7} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>

                {/* Summary stats */}
                {dowData.length > 0 && (() => {
                  const best  = [...dowData].sort((a, b) => b.avg - a.avg)[0]
                  const worst = [...dowData].sort((a, b) => a.avg - b.avg)[0]
                  return (
                    <div className="mt-4 grid grid-cols-2 gap-3 pt-4 border-t"
                      style={{ borderColor: 'var(--surface-border)' }}>
                      <div className="rounded-lg p-3" style={{ background: 'rgba(74,222,128,0.08)' }}>
                        <div className="text-xs mb-1 font-mono" style={{ color: '#4ade80' }}>Best day</div>
                        <div className="font-display font-bold">{best?.day}</div>
                        <div className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                          {best?.avg?.toLocaleString(undefined, { maximumFractionDigits: 0 })} avg · {best?.count} videos
                        </div>
                      </div>
                      <div className="rounded-lg p-3" style={{ background: 'rgba(255,60,60,0.08)' }}>
                        <div className="text-xs mb-1 font-mono" style={{ color: '#ff3c3c' }}>Lowest day</div>
                        <div className="font-display font-bold">{worst?.day}</div>
                        <div className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                          {worst?.avg?.toLocaleString(undefined, { maximumFractionDigits: 0 })} avg · {worst?.count} videos
                        </div>
                      </div>
                    </div>
                  )
                })()}
              </section>
            </div>
          )}
        </>
      )}
    </div>
  )
}
