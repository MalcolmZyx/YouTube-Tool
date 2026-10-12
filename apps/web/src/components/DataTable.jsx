import { useState, useRef, useCallback } from 'react'
import clsx from 'clsx'

const fmt = (val, type) => {
  if (val === null || val === undefined || val === '') return '—'
  if (type === 'percent') {
    const n = parseFloat(val)
    return isNaN(n) ? val : `${n.toFixed(1)}%`
  }
  if (type === 'numeric') {
    const n = parseFloat(val)
    if (isNaN(n)) return val
    return n >= 1000 ? n.toLocaleString('en-US', { maximumFractionDigits: 1 }) : n.toFixed(2)
  }
  return String(val)
}

const getSort = (row, col) => {
  const v = row[col]
  const n = parseFloat(String(v).replace(/[,%]/g, ''))
  return isNaN(n) ? String(v ?? '').toLowerCase() : n
}

export default function DataTable({ rows, columns, textCols, numericCols, percentCols, shares, videoIdCol, totalRow }) {
  const [colOrder, setColOrder]   = useState(columns)
  const [sortCol, setSortCol]     = useState(null)
  const [sortDir, setSortDir]     = useState('desc')
  const dragFrom = useRef(null)

  // ── Sort ──────────────────────────────────────────────────────────────
  const handleSort = col => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('desc') }
  }

  const sorted = [...rows].sort((a, b) => {
    if (!sortCol) return 0
    const va = getSort(a, sortCol), vb = getSort(b, sortCol)
    if (typeof va === 'number' && typeof vb === 'number')
      return sortDir === 'asc' ? va - vb : vb - va
    return sortDir === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va))
  })

  // ── Drag-to-reorder ───────────────────────────────────────────────────
  const onDragStart = useCallback(i => { dragFrom.current = i }, [])
  const onDragOver  = useCallback(e => e.preventDefault(), [])
  const onDrop      = useCallback(i => {
    if (dragFrom.current === null || dragFrom.current === i) return
    const next = [...colOrder]
    const [moved] = next.splice(dragFrom.current, 1)
    next.splice(i, 0, moved)
    setColOrder(next)
    dragFrom.current = null
  }, [colOrder])

  // ── Helpers ───────────────────────────────────────────────────────────
  const colType = col => {
    if (percentCols.includes(col)) return 'percent'
    if (numericCols.includes(col)) return 'numeric'
    return 'text'
  }

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div className="overflow-auto" style={{ maxHeight: '70vh' }}>
      <table className="data-table">
        <thead>
          <tr>
            {/* Thumbnail col */}
            <th style={{ width: 100, minWidth: 100 }}>Thumbnail</th>
            {colOrder.filter(c => c !== videoIdCol).map((col, i) => (
              <th
                key={col}
                draggable
                onDragStart={() => onDragStart(i)}
                onDragOver={onDragOver}
                onDrop={() => onDrop(i)}
                onClick={() => handleSort(col)}
                className={clsx('select-none', sortCol === col && 'sorted')}
                style={{ cursor: 'grab', minWidth: 90 }}
              >
                <span className="flex items-center gap-1">
                  {col}
                  {sortCol === col
                    ? <span style={{ color: 'var(--brand)' }}>{sortDir === 'asc' ? ' ↑' : ' ↓'}</span>
                    : <span style={{ opacity: 0.2 }}> ↕</span>}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {/* Total row */}
          {totalRow && (
            <tr className="total-row">
              <td>
                <span className="text-xs font-display font-bold uppercase tracking-widest px-2"
                  style={{ color: 'var(--brand)' }}>Total</span>
              </td>
              {colOrder.filter(c => c !== videoIdCol).map(col => (
                <TotalCell key={col} col={col} totalRow={totalRow} type={colType(col)} />
              ))}
            </tr>
          )}
          {sorted.map((row, rowIdx) => (
            <DataRow key={rowIdx} row={row} colOrder={colOrder} videoIdCol={videoIdCol}
              numericCols={numericCols} percentCols={percentCols}
              shares={shares} colType={colType} rowIdx={rowIdx} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── TotalCell ── */
function TotalCell({ col, totalRow, type }) {
  const val = totalRow[col]
  return (
    <td className="text-right font-mono text-sm">
      <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
        {fmt(val, type)}
      </span>
    </td>
  )
}

/* ── DataRow ── */
function DataRow({ row, colOrder, videoIdCol, numericCols, percentCols, shares, colType, rowIdx }) {
  const ACCENT_COLORS = ['#ff3c3c','#4ade80','#60a5fa','#fbbf24','#c084fc']
  const accent = ACCENT_COLORS[rowIdx % ACCENT_COLORS.length]
  const thumb  = row.thumbnail_url
  const vid    = String(row[videoIdCol] ?? '').trim()

  return (
    <tr style={{ borderLeft: rowIdx < 5 ? `3px solid ${accent}` : '3px solid transparent' }}>
      {/* Thumbnail */}
      <td style={{ padding: '6px 10px', width: 100 }}>
        {thumb
          ? <a href={`https://www.youtube.com/watch?v=${vid}`} target="_blank" rel="noreferrer">
              <img src={thumb} alt="thumb"
                className="rounded-md object-cover transition-transform duration-200 hover:scale-105"
                style={{ width: 90, height: 52 }} />
            </a>
          : vid
            ? <a href={`https://www.youtube.com/watch?v=${vid}`} target="_blank" rel="noreferrer"
                className="text-xs font-mono" style={{ color: 'var(--accent-blue)' }}>
                {vid}
              </a>
            : <span className="text-xs" style={{ color: 'var(--text-muted)' }}>—</span>
        }
      </td>

      {colOrder.filter(c => c !== videoIdCol).map(col => {
        const type = colType(col)
        const val  = row[col]

        if (type === 'numeric') {
          const pct = shares?.[col]?.[String(row._idx ?? '')] ?? 0
          return (
            <td key={col} className="text-right">
              <div className="flex items-center justify-end gap-2">
                <span className="font-mono text-xs" style={{ color: 'var(--text-primary)' }}>
                  {fmt(val, 'numeric')}
                </span>
                <span className="text-xs font-mono" style={{ color: 'var(--text-muted)', minWidth: 36 }}>
                  {typeof pct === 'number' ? `${pct.toFixed(0)}%` : ''}
                </span>
              </div>
            </td>
          )
        }
        if (type === 'percent') {
          const n = parseFloat(String(val).replace('%', ''))
          return (
            <td key={col} className="text-right">
              <span className="font-mono text-xs"
                style={{ color: isNaN(n) ? 'var(--text-muted)' : n > 5 ? '#4ade80' : 'var(--text-primary)' }}>
                {fmt(val, 'percent')}
              </span>
            </td>
          )
        }
        // text / date
        if (col === 'Video publish time' && val) {
          const d = new Date(val)
          return (
            <td key={col} className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
              {d.toLocaleDateString()}
            </td>
          )
        }
        return (
          <td key={col} className="text-xs" style={{ color: 'var(--text-primary)', maxWidth: 200, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {fmt(val, 'text')}
          </td>
        )
      })}
    </tr>
  )
}
