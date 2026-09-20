import { useState, useEffect } from 'react'
import { useApi } from '../hooks/useApi'
import { PageHeader, EmptyState, Badge, Skeleton } from '../components/ui'

export default function Descriptions() {
  const { get, loading } = useApi()
  const [videos,   setVideos]   = useState([])
  const [expanded, setExpanded] = useState({})
  const [search,   setSearch]   = useState('')
  const [filter,   setFilter]   = useState('all')

  useEffect(() => {
    get('/descriptions')
      .then(d => setVideos(d.videos ?? []))
      .catch(() => {})
  }, [])  // eslint-disable-line

  const toggle = id => setExpanded(p => ({ ...p, [id]: !p[id] }))

  const filtered = videos.filter(v => {
    if (search && !v.title.toLowerCase().includes(search.toLowerCase()) &&
        !v.description.toLowerCase().includes(search.toLowerCase())) return false
    if (filter === 'links'      && !v.has_links)      return false
    if (filter === 'hashtags'   && !v.has_hashtags)   return false
    if (filter === 'timestamps' && !v.has_timestamps) return false
    if (filter === 'long'       && v.char_count < 500) return false
    return true
  })

  if (!loading && videos.length === 0) {
    return (
      <EmptyState icon="📄" title="No description data"
        desc="Upload a file on the Dashboard. Descriptions require a valid YouTube API key to be fetched." />
    )
  }

  return (
    <div className="animate-fade-in">
      <PageHeader title="Description Analysis"
        subtitle={`${videos.length} videos with description data`}>
        {/* Search */}
        <input placeholder="Search title or description…"
          value={search} onChange={e => setSearch(e.target.value)}
          className="input w-56" />
        {/* Filter */}
        <select value={filter} onChange={e => setFilter(e.target.value)}
          className="input w-40"
          style={{ appearance: 'none', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-primary)' }}>
          <option value="all" style={{ background: '#1a1a1f' }}>All videos</option>
          <option value="links"      style={{ background: '#1a1a1f' }}>Has links</option>
          <option value="hashtags"   style={{ background: '#1a1a1f' }}>Has hashtags</option>
          <option value="timestamps" style={{ background: '#1a1a1f' }}>Has timestamps</option>
          <option value="long"       style={{ background: '#1a1a1f' }}>Long desc (500+)</option>
        </select>
      </PageHeader>

      {/* Summary stats */}
      {videos.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          {[
            { label: 'Total', val: videos.length, color: 'rgba(255,255,255,0.06)' },
            { label: 'Has Links', val: videos.filter(v=>v.has_links).length, color: 'rgba(96,165,250,0.1)' },
            { label: 'Has Hashtags', val: videos.filter(v=>v.has_hashtags).length, color: 'rgba(192,132,252,0.1)' },
            { label: 'Has Timestamps', val: videos.filter(v=>v.has_timestamps).length, color: 'rgba(251,191,36,0.1)' },
            { label: 'Long (500+ chars)', val: videos.filter(v=>v.char_count>=500).length, color: 'rgba(74,222,128,0.1)' },
          ].map(({ label, val, color }) => (
            <div key={label} className="rounded-xl p-3 text-center"
              style={{ background: color, border: '1px solid rgba(255,255,255,0.07)' }}>
              <div className="font-display font-bold text-xl">{val}</div>
              <div className="text-xs font-mono mt-0.5" style={{ color: 'var(--text-muted)' }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Video list */}
      <div className="space-y-3">
        {loading && [...Array(5)].map((_,i) => (
          <div key={i} className="card space-y-2">
            <Skeleton className="h-5 w-64" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-3/4" />
          </div>
        ))}

        {!loading && filtered.length === 0 && videos.length > 0 && (
          <div className="text-center py-16" style={{ color: 'var(--text-muted)' }}>
            No videos match the current filter.
          </div>
        )}

        {filtered.map(v => (
          <div key={v.video_id} className="card hover:border-white/10 transition-colors duration-150">
            <div className="flex gap-4">
              {/* Thumbnail */}
              {v.thumbnail_url && (
                <a href={v.url} target="_blank" rel="noreferrer" className="flex-shrink-0">
                  <img src={v.thumbnail_url} alt={v.title}
                    className="rounded-lg object-cover" style={{ width: 120, height: 68 }} />
                </a>
              )}

              <div className="flex-1 min-w-0">
                {/* Title row */}
                <div className="flex items-start justify-between gap-4 mb-2">
                  <a href={v.url} target="_blank" rel="noreferrer"
                    className="font-display font-bold text-sm hover:underline truncate"
                    style={{ color: 'var(--text-primary)' }}>
                    {v.title || v.video_id}
                  </a>
                  {/* Badges */}
                  <div className="flex items-center gap-1 flex-shrink-0">
                    {v.has_links      && <Badge color="blue">links</Badge>}
                    {v.has_hashtags   && <Badge color="amber">#tags</Badge>}
                    {v.has_timestamps && <Badge color="green">time</Badge>}
                    <Badge>{v.char_count.toLocaleString()} chars</Badge>
                    <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                      {v.line_count} lines
                    </span>
                  </div>
                </div>

                {/* Description */}
                <div className="relative">
                  <div
                    className="text-xs font-mono whitespace-pre-wrap overflow-hidden transition-all duration-300"
                    style={{
                      color: 'var(--text-muted)',
                      maxHeight: expanded[v.video_id] ? '600px' : '60px',
                      lineHeight: 1.6,
                    }}>
                    {v.description}
                  </div>
                  {!expanded[v.video_id] && v.char_count > 180 && (
                    <div className="absolute bottom-0 left-0 right-0 h-8"
                      style={{ background: 'linear-gradient(transparent, var(--surface-card))' }} />
                  )}
                </div>

                {v.char_count > 180 && (
                  <button onClick={() => toggle(v.video_id)}
                    className="text-xs mt-1 font-display font-semibold"
                    style={{ color: 'var(--brand)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
                    {expanded[v.video_id] ? '↑ Show less' : '↓ Show more'}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
