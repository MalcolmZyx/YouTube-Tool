import { useState, useEffect } from 'react'
import { useApi } from '../hooks/useApi'
import { TagBar, PageHeader, EmptyState, Skeleton } from '../components/ui'

export default function Keywords() {
  const { get, loading } = useApi()
  const [weighted, setWeighted] = useState(null)
  const [tvb,      setTvb]      = useState(null)
  const [topN,     setTopN]     = useState(25)
  const [tab,      setTab]      = useState('weighted')

  const load = async () => {
    try {
      const [w, t] = await Promise.all([
        get('/keywords/weighted', { top_n: topN }),
        get('/keywords/top-vs-bottom', { top_n: 20 }),
      ])
      setWeighted(w)
      setTvb(t)
    } catch {}
  }

  useEffect(() => { load() }, [])  // eslint-disable-line

  const noData = !weighted && !tvb && !loading

  if (noData) {
    return <EmptyState icon="🏷️" title="No data loaded"
      desc="Upload a file on the Dashboard. Keywords require YouTube API enrichment." />
  }

  const wTags = weighted?.tags ?? []
  const maxW  = wTags[0]?.score ?? 1

  const topTags    = tvb?.top    ?? []
  const bottomTags = tvb?.bottom ?? []
  const maxTop     = topTags[0]?.score    ?? 1
  const maxBottom  = bottomTags[0]?.score ?? 1

  return (
    <div className="animate-fade-in">
      <PageHeader title="Keyword Analysis" subtitle="View-weighted tag scoring and top vs bottom performer comparison">
        <div className="flex items-center gap-2">
          <label className="text-xs" style={{ color: 'var(--text-muted)' }}>Top N</label>
          <input type="number" value={topN} onChange={e => setTopN(+e.target.value)}
            className="input w-20" min={5} max={100} step={5} />
          <button className="btn btn-primary" onClick={load} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </PageHeader>

      {/* Tab switcher */}
      <div className="flex gap-1 mb-6 p-1 rounded-xl w-fit"
        style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid var(--surface-border)' }}>
        {[['weighted','⚡ Weighted Tags'],['tvb','📊 Top vs Bottom']].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            className="px-4 py-1.5 rounded-lg text-sm font-display font-semibold transition-all duration-150"
            style={tab === key
              ? { background: 'var(--brand)', color: 'white' }
              : { color: 'var(--text-muted)', background: 'transparent' }}>
            {label}
          </button>
        ))}
      </div>

      {/* ── Weighted Tags ─────────────────────────────────────────────── */}
      {tab === 'weighted' && (
        <div className="card">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="font-display font-bold text-base">View-Weighted Tag Scores</h2>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                Score = Σ log₁₀(views+1) per video that uses the tag
              </p>
            </div>
            <span className="text-xs font-mono px-2 py-1 rounded-sm"
              style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)' }}>
              {wTags.length} tags
            </span>
          </div>

          {loading
            ? <div className="space-y-3">{[...Array(8)].map((_, i) => <Skeleton key={i} className="h-6" />)}</div>
            : wTags.length === 0
              ? <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No tag data available. Ensure your YouTube API key is set and data is uploaded.</p>
              : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-10 gap-y-3">
                  {wTags.map((t, i) => (
                    <div key={t.tag} className="flex items-center gap-3">
                      <span className="text-xs font-mono w-5 shrink-0 text-right"
                        style={{ color: 'var(--text-muted)' }}>{i+1}</span>
                      <div className="flex-1 min-w-0">
                        <TagBar tag={t.tag} score={t.score} maxScore={maxW} />
                      </div>
                    </div>
                  ))}
                </div>
              )
          }
        </div>
      )}

      {/* ── Top vs Bottom ─────────────────────────────────────────────── */}
      {tab === 'tvb' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Top performers */}
          <div className="card">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-lg">📈</span>
              <div>
                <h2 className="font-display font-bold text-base">Top 20% Performer Tags</h2>
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Tags most associated with high-view videos</p>
              </div>
            </div>
            {loading
              ? <div className="space-y-3">{[...Array(6)].map((_,i) => <Skeleton key={i} className="h-6"/>)}</div>
              : topTags.length === 0
                ? <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No data.</p>
                : topTags.map((t, i) => (
                  <div key={t.tag} className="flex items-center gap-3 mb-2.5">
                    <span className="text-xs font-mono w-5 shrink-0 text-right"
                      style={{ color: 'var(--text-muted)' }}>{i+1}</span>
                    <div className="flex-1 min-w-0">
                      <TagBar tag={t.tag} score={t.score} maxScore={maxTop} color="#4ade80" />
                    </div>
                  </div>
                ))
            }
          </div>

          {/* Bottom performers */}
          <div className="card">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-lg">📉</span>
              <div>
                <h2 className="font-display font-bold text-base">Bottom 20% Performer Tags</h2>
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Tags most associated with lower-view videos</p>
              </div>
            </div>
            {loading
              ? <div className="space-y-3">{[...Array(6)].map((_,i) => <Skeleton key={i} className="h-6"/>)}</div>
              : bottomTags.length === 0
                ? <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No data.</p>
                : bottomTags.map((t, i) => (
                  <div key={t.tag} className="flex items-center gap-3 mb-2.5">
                    <span className="text-xs font-mono w-5 shrink-0 text-right"
                      style={{ color: 'var(--text-muted)' }}>{i+1}</span>
                    <div className="flex-1 min-w-0">
                      <TagBar tag={t.tag} score={t.score} maxScore={maxBottom} color="#ff6b6b" />
                    </div>
                  </div>
                ))
            }
          </div>

          {/* Overlap analysis */}
          {topTags.length > 0 && bottomTags.length > 0 && (() => {
            const topSet    = new Set(topTags.map(t => t.tag))
            const bottomSet = new Set(bottomTags.map(t => t.tag))
            const overlap   = [...topSet].filter(t => bottomSet.has(t))
            const unique    = [...topSet].filter(t => !bottomSet.has(t))

            return (
              <div className="md:col-span-2 card">
                <h2 className="font-display font-bold text-base mb-4">Insight Summary</h2>
                <div className="grid grid-cols-3 gap-4">
                  <div className="rounded-lg p-3" style={{ background: 'rgba(74,222,128,0.08)', border: '1px solid rgba(74,222,128,0.2)' }}>
                    <div className="text-xs font-mono mb-1" style={{ color: '#4ade80' }}>Unique to top</div>
                    <div className="font-display font-bold text-xl">{unique.length}</div>
                    <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                      {unique.slice(0,3).join(', ')}{unique.length > 3 ? '…' : ''}
                    </div>
                  </div>
                  <div className="rounded-lg p-3" style={{ background: 'rgba(255,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}>
                    <div className="text-xs font-mono mb-1" style={{ color: '#fbbf24' }}>In both groups</div>
                    <div className="font-display font-bold text-xl">{overlap.length}</div>
                    <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                      {overlap.slice(0,3).join(', ')}{overlap.length > 3 ? '…' : ''}
                    </div>
                  </div>
                  <div className="rounded-lg p-3" style={{ background: 'rgba(255,60,60,0.08)', border: '1px solid rgba(255,60,60,0.2)' }}>
                    <div className="text-xs font-mono mb-1" style={{ color: '#ff6b6b' }}>Unique to bottom</div>
                    <div className="font-display font-bold text-xl">
                      {bottomTags.filter(t => !topSet.has(t.tag)).length}
                    </div>
                    <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                      Avoid or improve these
                    </div>
                  </div>
                </div>
              </div>
            )
          })()}
        </div>
      )}
    </div>
  )
}
