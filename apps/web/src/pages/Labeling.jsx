import { useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { useApi } from '../hooks/useApi'
import { EmptyState, PageHeader } from '../components/ui'
import { RULES } from './labelingRules'

const QUEUE_SIZE = 8
const REFILL_BELOW = 4   // top the queue up from the server when it runs this low and nothing is waiting to be saved

const DEPTHS = [
  { value: 'basic',    label: 'Basic',    key: '1' },
  { value: 'specific', label: 'Specific', key: '2' },
  { value: 'advanced', label: 'Advanced', key: '3' },
]
const ASPECTS = [
  { value: 'audio',            label: 'Audio',               key: '4' },
  { value: 'video_quality',    label: 'Video quality',       key: '5' },
  { value: 'pacing',           label: 'Pacing or length',    key: '6' },
  { value: 'content_accuracy', label: 'Content accuracy',    key: '7' },
  { value: 'title_thumbnail',  label: 'Title or thumbnail',  key: '8' },
  { value: 'delivery',         label: 'Delivery',            key: '9' },
  { value: 'other',            label: 'Other',               key: '0' },
]

const isTyping = el => el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable)
const percent = x => `${Math.round(x * 100)}%`

export default function Labeling() {
  const { get, post } = useApi()
  const [queue, setQueue] = useState([])
  const [stats, setStats] = useState(null)
  const [ready, setReady] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [problem, setProblem] = useState('')
  const [depth, setDepth] = useState(null)
  const [aspects, setAspects] = useState([])
  const [rulesOpen, setRulesOpen] = useState(true)
  const [attempt, setAttempt] = useState(0)

  // The queue is also kept in a ref so that the saves running one after another always see the latest list.
  const queueRef = useRef([])
  const chain = useRef(Promise.resolve())   // saves and undos run strictly in the order they were pressed
  const pending = useRef(new Set())         // comments decided on screen whose save has not finished
  const refilling = useRef(false)

  const update = useCallback(change => {
    queueRef.current = change(queueRef.current)
    setQueue(queueRef.current)
  }, [])

  const refill = useCallback(async () => {
    if (pending.current.size || refilling.current || queueRef.current.length >= REFILL_BELOW) return
    refilling.current = true
    try {
      const { items } = await get('/labeling/queue', { count: QUEUE_SIZE })
      update(q => [...q, ...items.filter(i => !q.some(x => x.comment_id === i.comment_id) && !pending.current.has(i.comment_id))])
    } catch (err) { setProblem(err.message) } finally { refilling.current = false }
  }, [get, update])

  useEffect(() => {
    let live = true
    setReady(false)
    setLoadError('')
    Promise.all([get('/labeling/queue', { count: QUEUE_SIZE }), get('/labeling/stats')])
      .then(([q, s]) => {
        if (!live) return
        update(() => q.items)
        setStats(s)
        setReady(true)
      })
      .catch(err => { if (live) setLoadError(err.message) })
    return () => { live = false }
  }, [get, update, attempt])

  const resetTags = () => { setDepth(null); setAspects([]) }
  const enqueue = task => { chain.current = chain.current.then(task) }

  const decide = useCallback(decision => {
    const item = queueRef.current[0]
    if (!item) return
    const body = { comment_id: item.comment_id, decision }
    if (decision === 'constructive') {
      if (depth) body.depth = depth
      body.aspects = aspects
    }
    // Move on at once; the save happens in the background and the comment comes back if it fails.
    update(q => q.slice(1))
    resetTags()
    pending.current.add(item.comment_id)
    enqueue(async () => {
      try {
        const result = await post('/labeling/labels', body)
        setStats(result.stats)
        setProblem('')
        const next = result.next
        if (next) update(q => q.some(i => i.comment_id === next.comment_id) || pending.current.has(next.comment_id) ? q : [...q, next])
      } catch (err) {
        if (/expired/.test(err.message)) {
          toast.error('That comment expired before it could be saved, so it was dropped.')
        } else {
          update(q => [item, ...q.filter(i => i.comment_id !== item.comment_id)])
          setProblem(`Not saved: ${err.message}. The comment is back on screen.`)
        }
      } finally {
        pending.current.delete(item.comment_id)
        refill()
      }
    })
  }, [depth, aspects, post, update, refill])  // eslint-disable-line

  const undo = useCallback(() => {
    enqueue(async () => {
      try {
        const result = await post('/labeling/labels/undo')
        setStats(result.stats)
        setProblem('')
        resetTags()
        if (result.undone) update(q => [result.undone, ...q.filter(i => i.comment_id !== result.undone.comment_id)])
        else toast('Undone. The comment itself has expired, so it is not shown again.')
      } catch (err) { toast.error(err.message) }
    })
  }, [post, update])

  const toggleDepth = value => setDepth(d => (d === value ? null : value))
  const toggleAspect = value => setAspects(a => (a.includes(value) ? a.filter(x => x !== value) : [...a, value]))

  useEffect(() => {
    const onKey = e => {
      if (e.repeat || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return
      const key = e.key.toLowerCase()
      const depthHit = DEPTHS.find(d => d.key === key)
      const aspectHit = ASPECTS.find(a => a.key === key)
      if (key === 'c') decide('constructive')
      else if (key === 'n') decide('not_constructive')
      else if (key === 's') decide('skip')
      else if (key === 'd') decide('discard')
      else if (key === 'u') undo()
      else if (depthHit) toggleDepth(depthHit.value)
      else if (aspectHit) toggleAspect(aspectHit.value)
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [decide, undo])

  // A click leaves the button focused, and Enter or Space would then press it again on the next comment.
  const click = action => e => { e.currentTarget.blur(); action() }

  const current = queue[0]

  if (loadError) {
    return (
      <>
        <PageHeader title="Label comments" subtitle="Constructive criticism or not" />
        <div className="card text-sm">
          <p className="font-semibold mb-1" style={{ color: 'var(--brand)' }}>The comments could not be loaded.</p>
          <p className="mb-4" style={{ color: 'var(--text-muted)' }}>{loadError}</p>
          <button className="btn btn-primary" onClick={() => setAttempt(n => n + 1)}>Try again</button>
        </div>
      </>
    )
  }

  if (ready && !current && !pending.current.size) {
    const done = stats && stats.labeled_total > 0
    return (
      <>
        <PageHeader title="Label comments" subtitle="Constructive criticism or not" />
        <Progress stats={stats} />
        <EmptyState icon="💬"
          title={done ? 'Nothing left to label' : 'No comments to label'}
          desc={done ? 'Every comment in the pool has a decision. Run the crawler to collect more.'
            : 'Run the crawler to collect comments, then come back.'}
          action={<button className="btn btn-ghost" onClick={() => setAttempt(n => n + 1)}>Check again</button>} />
        {stats && Object.values(stats.counts).some(n => n > 0) && (
          <div className="flex justify-center"><Undo onClick={click(undo)} /></div>
        )}
      </>
    )
  }

  return (
    <>
      <PageHeader title="Label comments" subtitle="Constructive criticism or not" />
      <Progress stats={stats} />

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_24rem] gap-6">
        <section className="card">
          {!ready ? <div className="skeleton h-40" /> : (
            <>
              <div className="text-xs mb-3 truncate" style={{ color: 'var(--text-muted)' }}
                title={current?.video_title ?? ''}>
                {current?.video_title ?? 'Video title unavailable'}
              </div>
              {/* Comment text comes from YouTube, so it is rendered as text only (React escapes it). */}
              <p className="text-2xl leading-relaxed whitespace-pre-wrap break-words min-h-32"
                style={{ color: 'var(--text-primary)' }}>
                {current?.text}
              </p>
              <div className="flex gap-4 mt-4 text-xs" style={{ color: 'var(--text-muted)' }}>
                <span>{current?.like_count ?? 0} likes</span>
                {current?.stratum?.category_id && <span>category {current.stratum.category_id}</span>}
                {current?.published_at && <span>{new Date(current.published_at).toLocaleDateString()}</span>}
              </div>
            </>
          )}

          {problem && (
            <p className="mt-4 text-sm rounded-lg px-3 py-2" role="alert"
              style={{ background: 'var(--brand-dim)', color: '#ff6b6b' }}>{problem}</p>
          )}

          <div className="grid grid-cols-2 gap-3 mt-6">
            <button className="btn justify-center py-4 text-base" disabled={!current}
              style={{ background: 'rgba(74,222,128,0.15)', color: 'var(--accent-green)', border: '1px solid rgba(74,222,128,0.4)' }}
              onClick={click(() => decide('constructive'))}>
              Constructive criticism <Key>C</Key>
            </button>
            <button className="btn justify-center py-4 text-base btn-ghost" disabled={!current}
              style={{ color: 'var(--text-primary)' }}
              onClick={click(() => decide('not_constructive'))}>
              Not constructive <Key>N</Key>
            </button>
          </div>
          <div className="flex gap-2 mt-3">
            <button className="btn btn-ghost" disabled={!current} onClick={click(() => decide('skip'))}
              title="Put it at the back of the queue">Skip <Key>S</Key></button>
            <button className="btn btn-ghost" disabled={!current} onClick={click(() => decide('discard'))}
              title="Remove it from the dataset for good; its text is not kept">Discard <Key>D</Key></button>
            <span className="ml-auto"><Undo onClick={click(undo)} /></span>
          </div>

          <div className="mt-6 pt-4 border-t space-y-3" style={{ borderColor: 'var(--surface-border)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Optional tags, saved only with Constructive criticism and cleared after each decision.
            </div>
            <Choices label="Depth" options={DEPTHS} selected={d => depth === d} onToggle={toggleDepth} />
            <Choices label="Aspect" options={ASPECTS} selected={a => aspects.includes(a)} onToggle={toggleAspect} />
          </div>
        </section>

        <aside className="space-y-6">
          <Rules open={rulesOpen} onToggle={() => setRulesOpen(o => !o)} />
          <UpNext queue={queue} />
        </aside>
      </div>
    </>
  )
}

function Key({ children }) {
  return <kbd className="font-mono text-xs px-1.5 rounded" style={{ background: 'rgba(255,255,255,0.1)' }}>{children}</kbd>
}

function Undo({ onClick }) {
  return <button className="btn btn-ghost" onClick={onClick} title="Take back the last decision">Undo <Key>U</Key></button>
}

function Choices({ label, options, selected, onToggle }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs uppercase tracking-wider w-14" style={{ color: 'var(--text-muted)' }}>{label}</span>
      {options.map(o => (
        <button key={o.value} aria-pressed={selected(o.value)}
          className={clsx('btn text-xs py-1 px-3', selected(o.value) ? 'btn-primary' : 'btn-ghost')}
          onClick={e => { e.currentTarget.blur(); onToggle(o.value) }}>
          {o.label} <Key>{o.key}</Key>
        </button>
      ))}
    </div>
  )
}

function Progress({ stats }) {
  if (!stats) return null
  const p = stats.prevalence
  return (
    <div className="card mb-6 !py-3">
      <div className="flex gap-8 flex-wrap text-sm">
        <Figure label="Labeled" value={stats.labeled_total.toLocaleString()} />
        <Figure label="Constructive share" title={p.note}
          value={p.share == null ? 'n/a' : `${percent(p.share)} (${percent(p.low)} to ${percent(p.high)})`} />
        <Figure label="Labeled today" value={stats.labeled_today.toLocaleString()} />
        <Figure label="Left in the pool" value={stats.remaining.toLocaleString()} />
      </div>
      <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>
        The share is a 95% interval and only means something for the {p.queue_mode} queue, based on {p.n.toLocaleString()} labels.
      </p>
    </div>
  )
}

function Figure({ label, value, title }) {
  return (
    <div title={title}>
      <div className="text-xs uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="font-display font-bold text-lg">{value}</div>
    </div>
  )
}

function Rules({ open, onToggle }) {
  return (
    <section className="card !p-4">
      <button className="flex w-full items-center justify-between font-display font-bold text-base"
        aria-expanded={open} onClick={e => { e.currentTarget.blur(); onToggle() }}>
        <span>Labeling rules <span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>v{RULES.version}</span></span>
        <span style={{ color: 'var(--text-muted)' }}>{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div className="mt-3 text-xs space-y-3 max-h-[28rem] overflow-y-auto pr-1">
          <p>{RULES.definition}</p>
          <table className="w-full">
            <tbody>
              {RULES.rulings.map(([when, label]) => (
                <tr key={when} className="align-top border-t" style={{ borderColor: 'var(--surface-border)' }}>
                  <td className="py-1.5 pr-2">{when}</td>
                  <td className="py-1.5 whitespace-nowrap font-semibold"
                    style={{ color: label === 'Constructive' ? 'var(--accent-green)' : 'var(--text-muted)' }}>{label}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ color: 'var(--text-muted)' }}>{RULES.tags}</p>
          <ul className="list-disc pl-4 space-y-1">{RULES.open.map(o => <li key={o}>{o}</li>)}</ul>
        </div>
      )}
    </section>
  )
}

function UpNext({ queue }) {
  return (
    <section className="card !p-4">
      <h2 className="font-display font-bold text-base mb-2">Up next</h2>
      <ol className="space-y-1 text-xs">
        {queue.slice(0, QUEUE_SIZE).map((item, i) => (
          <li key={item.comment_id} className="rounded-lg px-2 py-1.5 line-clamp-2 break-words"
            style={i === 0
              ? { background: 'var(--brand-dim)', border: '1px solid var(--brand)' }
              : { color: 'var(--text-muted)' }}>
            {item.text}
          </li>
        ))}
      </ol>
    </section>
  )
}
