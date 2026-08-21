import { useEffect, useState } from 'react'

interface FeedItem {
  id: string; title: string; url: string; published_at: string
  country_code?: string; source_id: string; language: string
  lat?: number; lng?: number; raw_data?: any
}

interface Props { onSelectCountry?: (c: string) => void; onSelectEntity?: (id: string) => void; onFlyTo?: (lat: number, lng: number) => void }

export default function LiveFeed({ onSelectCountry, onSelectEntity, onFlyTo }: Props) {
  const [items, setItems] = useState<FeedItem[]>([])
  const [loading, setLoading] = useState(true)
  const [offset, setOffset] = useState(0)
  const [filter, setFilter] = useState('')

  const load = (reset = false) => {
    const off = reset ? 0 : offset
    setLoading(true)
    let url = `/api/feed?limit=30&offset=${off}`
    if (filter) url += `&country=${filter}`
    fetch(url).then(r => r.json()).then(d => {
      setItems(reset ? d.items : [...items, ...d.items])
      setOffset(off + d.items.length)
      setLoading(false)
    }).catch(() => setLoading(false))
  }

  useEffect(() => { load(true) }, [filter])

  const timeAgo = (ts: string) => {
    // 后端给 UTC ISO 串——无 T 的补 Z 再解析，否则被当本地时间差 8 小时
    const t = new Date(ts.includes('T') ? ts : ts.replace(' ', 'T') + 'Z')
    if (isNaN(t.getTime())) return '?'
    const diff = Date.now() - t.getTime()
    if (diff < 0) return 'now'
    const mins = Math.floor(diff / 60000)
    if (mins < 60) return `${mins}m`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h`
    return `${Math.floor(hrs / 24)}d`
  }

  const platformLabel = (item: FeedItem) => {
    const p = item.raw_data?.platform
    if (p === 'weibo') return { text: 'WB', color: '#ef4444' }
    if (p === 'zhihu') return { text: 'ZH', color: '#3b82f6' }
    if (p === 'xiaohongshu') return { text: 'XHS', color: '#f97316' }
    if (item.language === 'zh') return { text: 'ZH', color: '#64748b' }
    return { text: 'EN', color: '#22c55e' }
  }

  const aiClass = (item: FeedItem) => item.raw_data?.ai_classification

  return (
    <div style={{fontSize:12}}>
      <div style={{display:'flex',gap:4,marginBottom:8,flexWrap:'wrap'}}>
        {['','CN','US','JP','RU','IR','GB','FR','DE'].map(c => (
          <button key={c} onClick={() => setFilter(c)}
            style={{background:filter===c?'var(--accent)':'var(--bg)',color:filter===c?'#fff':'var(--fg-dim)',
              border:'1px solid var(--border)',padding:'2px 8px',borderRadius:3,fontSize:10,cursor:'pointer'}}>
            {c || 'ALL'}
          </button>
        ))}
      </div>

      {items.map(item => {
        const cls = aiClass(item)
        const plat = platformLabel(item)
        return (
          <div key={item.id} style={{padding:'6px 8px',borderBottom:'1px solid var(--border)',cursor:'pointer',
            transition:'background 0.15s',lineHeight:1.4}}
            onMouseEnter={e => e.currentTarget.style.background='var(--bg-hover)'}
            onMouseLeave={e => e.currentTarget.style.background=''}>
            <div style={{display:'flex',gap:6,alignItems:'center',marginBottom:2}}>
              <span style={{fontSize:10,color:'var(--fg-dim)',fontFamily:'monospace',minWidth:28}}>{timeAgo(item.published_at)}</span>
              <span style={{fontSize:9,fontWeight:700,color:plat.color,background:plat.color+'20',padding:'0 4px',borderRadius:2}}>{plat.text}</span>
              {item.country_code && (
                <span onClick={e => { e.stopPropagation(); onSelectCountry?.(item.country_code!) }}
                  style={{fontSize:9,color:'var(--accent)',background:'var(--accent-dim)',padding:'0 4px',borderRadius:2,cursor:'pointer'}}>
                  {item.country_code}
                </span>
              )}
              {cls && (
                <span style={{fontSize:9,color:cls.threat==='high'||cls.threat==='critical'?'var(--red)':'var(--fg-dim)',
                  marginLeft:'auto'}}>
                  {cls.threat} {cls.topic}
                </span>
              )}
            </div>
            <a href={item.url} target="_blank" style={{color:'var(--fg)',textDecoration:'none',fontSize:12}}
              onMouseEnter={e => e.currentTarget.style.color='var(--accent)'}
              onMouseLeave={e => e.currentTarget.style.color='var(--fg)'}>
              {item.title?.substring(0, 100)}
            </a>
            {item.lat && item.lng && (
              <span onClick={e => { e.stopPropagation(); onFlyTo?.(item.lat!, item.lng!) }}
                style={{fontSize:9,color:'var(--accent)',marginLeft:6,cursor:'pointer'}}>📍</span>
            )}
            {item.raw_data?.importance >= 7 && (
              <span style={{fontSize:9,color:'var(--red)',background:'var(--red)20',padding:'0 3px',borderRadius:2,marginLeft:4}}>!{item.raw_data.importance}</span>
            )}
            {item.raw_data?.verification?.status === 'verified' && (
              <span style={{fontSize:9,color:'var(--green)',marginLeft:2}}>✓</span>
            )}
            {item.raw_data?.verification?.status === 'unverified' && (
              <span style={{fontSize:9,color:'var(--fg-dim)',marginLeft:2}}>?</span>
            )}
          </div>
        )
      })}

      <div style={{textAlign:'center',padding:12}}>
        {loading ? <span style={{color:'var(--fg-dim)',fontSize:11}}>加载中...</span> :
          <button onClick={() => load(false)}
            style={{background:'none',border:'1px solid var(--border)',color:'var(--fg-dim)',padding:'4px 16px',borderRadius:4,fontSize:11,cursor:'pointer'}}>
            加载更多
          </button>
        }
      </div>
    </div>
  )
}
