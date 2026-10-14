export default function Empty({ title, desc }) {
  return (
    <div className="card text-center py-12 max-w-xl mx-auto mt-8">
      <h2 className="font-display font-bold text-lg mb-2">{title}</h2>
      <p className="text-sm" style={{ color: 'var(--text-muted)' }}>{desc}</p>
    </div>
  )
}
