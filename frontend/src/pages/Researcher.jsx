import { useState, useRef } from 'react'
import toast from 'react-hot-toast'
import { useApi } from '../hooks/useApi'
import { TagBar, PageHeader, Badge } from '../components/ui'

const ORDERS = [
  { value: 'relevance',  label: 'Relevance' },
  { value: 'viewCount',  label: 'Most Views' },
  { value: 'date',       label: 'Newest' },
  { value: 'rating',     label: 'Top Rated' },
]
const DURATIONS = [
  { value: 'any',    label: 'Any length' },
  { value: 'short',  label: 'Short (< 4m)' },
  { value: 'medium', label: 'Medium (4–20m)' },
  { value: 'long',   label: 'Long (> 20m)' },
]

export default function Researcher() {
  const { get, post, loading } = useApi()

  // Form
  const [query,          setQuery]          = useState('')
  const [maxResults,     setMaxResults]     = useState(20)
  const [order,          setOrder]          = useState('viewCount')
  const [videoDuration,  setVideoDuration]  = useState('any')
  const [publishedAfter, setPublishedAfter] = useState('')
  const [publishedBefore,setPublishedBefore]= useState('')

  // Results
  const [videos, setVideos]  = useState([])
  const [tags,   setTags]    = useState([])
  const [ideas,  setIdeas]   = useState([])
  const [tab,    setTab]     = useState('videos')

  // Idea fetch on keystroke debounce
  const ideaTimer = useRef(null)
  const handleQueryChange = val => {
    setQuery(val)
    clearTimeout(ideaTimer.current)
    if (val.trim().length > 2) {
      ideaTimer.current = setTimeout(() => fetchIdeas(val), 500)
    } else {
      setIdeas([])
    }
  }

  const fetchIdeas = async topic => {
    try {
      const d = await get('/researcher/ideas', { topic })
      setIdeas(d.ideas ?? [])
    } catch {}
  }

  const handleSearch = async e => {
    e?.preventDefault()
    if (!query.trim()) return
    setIdeas([])
    toast.loading('Searching YouTube…', { id: 'research' })
    try {
      const body = {
        query, max_results: maxResults, order, video_duration: videoDuration,
        published_after:  publishedAfter  || undefined,
        published_before: publishedBefore || undefined,
      }
      const d = await post('/researcher/search', body)
      setVideos(d.videos ?? [])
      setTags(d.tags ?? [])
      setTab('videos')
      toast.success(`Found ${d.total} videos`, { id: 'research' })
    } catch (err) {
      toast.error(err.message, { id: 'research' })
    }
  }

  const maxTagScore = tags[0]?.score ?? 1

  return (
    <div className="animate-fade-in">
      <PageHeader title="YouTube Researcher" subtitle="Search, ideate, and analyse competitor tags" />

      {/* ── Search Form ────────────────────────────────────────────────── */}
      <form onSubmit={handleSearch} className="card mb-6 space-y-4">
        {/* Query + submit */}
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <input
              value={query}
              onChange={e => handleQueryChange(e.target.value)}
              placeholder="Search query e.g. 'pelvic physical therapy'"
              className="input pr-4"
            />
            {/* Autocomplete dropdown */}
            {ideas.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 rounded-xl z-20 overflow-hidden"
                style={{ background: '#1a1a1f', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 12px 40px rgba(0,0,0,0.6)' }}>
                {ideas.map((idea, i) => (
                  <button key={i} type="button"
                    onClick={() => { setQuery(idea); setIdeas([]) }}
                    className="w-full text-left px-4 py-2 text-sm transition-colors hover:bg-white/5"
                    style={{ color: 'var(--text-primary)', fontFamily: 'DM Sans', background: 'transparent', border: 'none', cursor: 'pointer' }}>
                    <span className="mr-2" style={{ color: 'var(--text-muted)' }}>🔍</span>
                    {idea}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button type="submit" className="btn btn-primary flex-shrink-0" disabled={loading}>
            {loading ? 'Searching…' : '🔍 Search'}
          </button>
        </div>

        {/* Options row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="text-xs mb-1 block" style={{ color: 'var(--text-muted)' }}>Sort by</label>
            <select value={order} onChange={e => setOrder(e.target.value)} className="input"
              style={{ background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)' }}>
              {ORDERS.map(o => <option key={o.value} value={o.value} style={{ background: '#1a1a1f' }}>{o.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs mb-1 block" style={{ color: 'var(--text-muted)' }}>Duration</label>
            <select value={videoDuration} onChange={e => setVideoDuration(e.target.value)} className="input"
              style={{ background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)' }}>
              {DURATIONS.map(d => <option key={d.value} value={d.value} style={{ background: '#1a1a1f' }}>{d.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs mb-1 block" style={{ color: 'var(--text-muted)' }}>Max results</label>
            <input type="number" value={maxResults} onChange={e => setMaxResults(+e.target.value)}
              className="input" min={1} max={50} />
          </div>
          <div>
            <label className="text-xs mb-1 block" style={{ color: 'var(--text-muted)' }}>Published after</label>
            <input type="date" value={publishedAfter} onChange={e => setPublishedAfter(e.target.value)}
              className="input" style={{ colorScheme: 'dark' }} />
          </div>
        </div>
      </form>

      {/* ── Results ─────────────────────────────────────────────────────── */}
      {(videos.length > 0 || tags.length > 0) && (
        <>
          {/* Tab bar */}
          <div className="flex gap-1 mb-5 p-1 rounded-xl w-fit"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid var(--surface-border)' }}>
            {[
              ['videos', `📹 Videos (${videos.length})`],
              ['tags',   `🏷️  Tags (${tags.length})`],
            ].map(([key, label]) => (
              <button key={key} onClick={() => setTab(key)}
                className="px-4 py-1.5 rounded-lg text-sm font-display font-semibold transition-all duration-150"
                style={tab === key
                  ? { background: 'var(--brand)', color: 'white' }
                  : { color: 'var(--text-muted)', background: 'transparent' }}>
                {label}
              </button>
            ))}
          </div>

          {/* Videos grid */}
          {tab === 'videos' && (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 animate-slide-up">
              {videos.map(v => <VideoCard key={v.video_id} v={v} />)}
            </div>
          )}

          {/* Tags panel */}
          {tab === 'tags' && (
            <div className="card animate-slide-up">
              <div className="flex items-center justify-between mb-5">
                <div>
                  <h2 className="font-display font-bold text-base">Competitor Tag Analysis</h2>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    View-weighted scores across all {videos.length} results for "{query}"
                  </p>
                </div>
                <button
                  onClick={() => navigator.clipboard.writeText(tags.map(t => t.tag).join(', ')).then(() => toast.success('Copied!'))}
                  className="btn btn-ghost text-xs">
                  Copy all tags
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-10 gap-y-3">
                {tags.map((t, i) => (
                  <div key={t.tag} className="flex items-center gap-3">
                    <span className="text-xs font-mono w-5 flex-shrink-0 text-right"
                      style={{ color: 'var(--text-muted)' }}>{i+1}</span>
                    <div className="flex-1 min-w-0">
                      <TagBar tag={t.tag} score={t.score} maxScore={maxTagScore} color="#60a5fa" />
                    </div>
                  </div>
                ))}
              </div>

              {/* Tags as copy-ready pill list */}
              <div className="mt-6 pt-5 border-t" style={{ borderColor: 'var(--surface-border)' }}>
                <div className="text-xs font-mono mb-3" style={{ color: 'var(--text-muted)' }}>All tags (click to copy)</div>
                <div className="flex flex-wrap gap-1.5">
                  {tags.map(t => (
                    <span key={t.tag} className="tag-pill cursor-pointer"
                      onClick={() => navigator.clipboard.writeText(t.tag).then(() => toast.success(`"${t.tag}" copied`))}>
                      {t.tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* Empty state after no search yet */}
      {videos.length === 0 && tags.length === 0 && !loading && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <span className="text-5xl mb-4">🔭</span>
          <h3 className="font-display font-bold text-lg mb-1" style={{ color: 'var(--text-primary)' }}>
            Start your research
          </h3>
          <p className="text-sm max-w-xs" style={{ color: 'var(--text-muted)' }}>
            Type a query above. Autocomplete ideas will appear as you type.
          </p>
        </div>
      )}
    </div>
  )
}

/* ── Video Card ── */
function VideoCard({ v }) {
  const views = v.views >= 1e6 ? `${(v.views/1e6).toFixed(1)}M` : v.views >= 1e3 ? `${(v.views/1e3).toFixed(0)}K` : v.views

  return (
    <div className="card flex flex-col gap-3 hover:border-white/10 transition-colors duration-150 group">
      {/* Thumbnail */}
      <a href={v.url} target="_blank" rel="noreferrer" className="block relative overflow-hidden rounded-lg">
        <img src={v.thumbnail} alt={v.title}
          className="w-full object-cover rounded-lg group-hover:scale-105 transition-transform duration-300"
          style={{ aspectRatio: '16/9' }} />
        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-200"
          style={{ background: 'rgba(0,0,0,0.4)' }}>
          <span className="text-3xl">▶</span>
        </div>
      </a>

      {/* Meta */}
      <div className="flex-1 min-w-0">
        <a href={v.url} target="_blank" rel="noreferrer"
          className="font-display font-semibold text-sm leading-snug hover:underline line-clamp-2 block mb-1"
          style={{ color: 'var(--text-primary)' }}>
          {v.title}
        </a>
        <div className="text-xs mb-2" style={{ color: 'var(--text-muted)' }}>{v.channel}</div>
        <div className="flex items-center gap-2">
          <Badge color="blue">{views} views</Badge>
          {v.likes > 0 && <Badge color="green">{v.likes >= 1000 ? `${(v.likes/1000).toFixed(0)}K` : v.likes} likes</Badge>}
          {v.published_at && (
            <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
              {new Date(v.published_at).toLocaleDateString()}
            </span>
          )}
        </div>
      </div>

      {/* Tags */}
      {v.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-2 border-t" style={{ borderColor: 'var(--surface-border)' }}>
          {v.tags.slice(0, 6).map(tag => (
            <span key={tag} className="tag-pill">{tag}</span>
          ))}
          {v.tags.length > 6 && (
            <span className="tag-pill" style={{ color: 'var(--text-muted)' }}>+{v.tags.length - 6}</span>
          )}
        </div>
      )}
    </div>
  )
}
