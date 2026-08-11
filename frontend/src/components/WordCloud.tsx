import { useEffect, useState } from 'react'

interface WordItem { text: string; count: number }

export default function WordCloud() {
  const [words, setWords] = useState<WordItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/trends/top?days=7&limit=30')
      .then(r => r.json())
      .then(d => {
        const items: WordItem[] = (d.top_countries || []).map((c: any) => ({
          text: c.country, count: c.count
        }))
        setWords(items)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  if (loading) return <div style={{color:'var(--fg-dim)',fontSize:12,padding:8}}>Loading keywords...</div>
  if (!words.length) return null

  const max = words[0]?.count || 1
  const colors = ['#3b82f6','#eab308','#ef4444','#22c55e','#a855f7','#f97316','#06b6d4']

  return (
    <div style={{background:'var(--bg-card)',border:'1px solid var(--border)',borderRadius:6,padding:10,marginTop:8}}>
      <div style={{fontSize:11,fontWeight:600,color:'var(--fg-dim)',marginBottom:8}}>Top Countries (7 days)</div>
      <div style={{display:'flex',flexWrap:'wrap',gap:6,lineHeight:1.5}}>
        {words.map((w, i) => {
          const size = 10 + (w.count / max) * 16
          const color = colors[i % colors.length]
          return (
            <span key={w.text} style={{
              fontSize: size, color,
              opacity: 0.4 + (w.count / max) * 0.6,
              fontWeight: w.count > max * 0.5 ? 700 : 400,
              cursor: 'pointer',
              transition: 'transform 0.15s',
            }}
            title={`${w.text}: ${w.count} mentions`}
            onMouseEnter={e => (e.currentTarget.style.transform='scale(1.2)')}
            onMouseLeave={e => (e.currentTarget.style.transform='scale(1)')}
            >
              {w.text}
            </span>
          )
        })}
      </div>
    </div>
  )
}
