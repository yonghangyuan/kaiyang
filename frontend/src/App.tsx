import { useState, useEffect } from 'react'
import MapView from './components/MapView'
import GlobeView from './components/GlobeView'
import Sidebar from './components/Sidebar'
import { api } from './api'
import type { GeoPoint, Briefing, Annotation, Stats } from './api'

export type { GeoPoint, Briefing, Annotation, Stats }

export default function App() {
  const [events, setEvents] = useState<GeoPoint[]>([])
  const [searchResults, setSearchResults] = useState<GeoPoint[]>([])
  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [briefing, setBriefing] = useState<Briefing | null>(null)
  const [chatMessages, setChatMessages] = useState<{role:string;content:string;time:string}[]>([])
  const [status, setStatus] = useState('就绪')
  const [stats, setStats] = useState<Stats>({sources:0, intel:0, events:0, entities:0})
  const [viewMode, setViewMode] = useState<'2d'|'3d'>('2d')
  const [flyTo, setFlyTo] = useState<{lat:number;lng:number} | null>(null)
  const [chain, setChain] = useState<any>(null)
  const [topicLayers, setTopicLayers] = useState<{issue_id:string;name:string;category?:string;events?:number;mappable_events?:number}[]>([])
  const [activeTopics, setActiveTopics] = useState<string[]>([])
  const [latestIntel, setLatestIntel] = useState<{id:string;title:string;published_at?:string;source:string;country_code?:string;url?:string}[]>([])

  const loadLatestIntel = async () => {
    try { const d = await fetch('/api/intel/latest?limit=30').then(r => r.json()); setLatestIntel(d.items||[]) } catch {}
  }
  useEffect(() => { loadLatestIntel(); const t = setInterval(loadLatestIntel, 60000); return () => clearInterval(t) }, [])

  const loadTopicLayers = async () => {
    try { const d = await fetch('/api/map/layers').then(r => r.json()); setTopicLayers(d.topic_layers||[]) } catch {}
  }
  useEffect(() => { loadTopicLayers() }, [])
  const toggleTopic = (issueId: string) => {
    setActiveTopics(prev => prev.includes(issueId) ? prev.filter(id => id !== issueId) : [...prev, issueId])
  }

  const loadEvents = async () => {
    try { const d = await api.events(); setEvents(d.points||[]); setStatus('事件: '+d.count) } catch { setStatus('加载失败') }
  }
  const loadAnnotations = async () => {
    try { const d = await api.annotations.list(); setAnnotations(d.annotations||[]) } catch {}
  }
  const loadStats = async () => {
    try { setStats(await api.stats()) } catch {}
  }
  // SSE 实时连接 (参考 Redroom SSE data pump)
  useEffect(() => {
    const es = new EventSource('/api/sse')
    es.onmessage = (evt) => {
      try {
        const d = JSON.parse(evt.data)
        if (d.type === 'new_event') {
          setStatus(`新事件: ${(d.title||'').substring(0,40)}`)
          loadEvents(); loadStats()
          if (d.level === 'warning' && (Notification as any).permission === 'granted') {
            new Notification('开阳 新事件', { body: `${(d.title||'').substring(0,60)} sev:${d.severity}`, icon: '/favicon.svg' })
          }
        }
        if (d.type === 'fetch_complete' && d.new_items > 0) {
          setStatus(`新增: ${d.new_items} 条`)
          loadEvents(); loadStats(); loadLatestIntel()
          // 浏览器通知
          if (d.level === 'warning' && (Notification as any).permission === 'granted') {
            new Notification('开阳 情报更新', { body: d.body, icon: '/favicon.svg' })
          }
        }
      } catch {}
    }
    es.onerror = () => { /* auto-reconnect built into EventSource */ }
    return () => es.close()
  }, [])

  // Periodic fallback refresh (every 90s)
  useEffect(() => { const t = setInterval(() => { loadEvents(); loadStats() }, 90000); return () => clearInterval(t) }, [])
  // Request notification permission
  useEffect(() => { if ('Notification' in window && (Notification as any).permission === 'default') { Notification.requestPermission() } }, [])
  useEffect(() => { loadEvents(); loadAnnotations(); loadStats() }, [])

  const doSearch = async (query:string) => {
    setStatus('搜索中...')
    try { const d = await api.search(query); setSearchResults(d.points||[]); setBriefing(d); setStatus(d.point_count+' 个标注') } catch(e:any) { setStatus('搜索失败') }
  }

  const doChat = async (msg:string) => {
    const now = new Date().toLocaleTimeString()
    setChatMessages(p=>[...p,{role:'user',content:msg,time:now}])
    setStatus('思考中...')
    const [chatR,searchR] = await Promise.allSettled([api.chat(msg), api.search(msg, 20)])
    if(chatR.status==='fulfilled'){
      const d=chatR.value
      setChatMessages(p=>[...p,{role:'ai',content:(d.reply||'').replace(/\*\*/g,'').replace(/^#{1,4}\s/gm,'').replace(/^---+/gm,'').replace(/```[\s\S]*?```/g,'').replace(/`([^`]+)`/g,'$1').trim(),time:new Date().toLocaleTimeString()}])
      setStatus(d.model||'已回复')
      try{const ad=await api.annotations.fromText(d.reply);if(ad.ok){loadAnnotations();setStatus(s=>s+' | '+ad.coordinates_count+' annotations')}}catch{}
    }
    if(searchR.status==='fulfilled'){setSearchResults(searchR.value.points||[]);setBriefing(searchR.value)}
  }

  const clearAnnotations = () => { api.annotations.clear(); loadAnnotations() }

  // Ticker: 最新情报流（不再复用地图事件——那个按 severity 排序，老事件会霸屏）
  // published_at 是 UTC ISO 串——解析后转本地时间显示
  const fmtTime = (iso?: string) => {
    if (!iso) return ''
    const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z')
    if (isNaN(d.getTime())) return iso.substring(11,16)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  const tickerItems = latestIntel.map(e => ({
    title: (e.title||'').substring(0,90),
    country: e.country_code||'',
    source: (e.source||'').substring(0,12),
    time: fmtTime(e.published_at),
    url: e.url,
  }))

  return (
    <div style={{display:'flex',flexDirection:'column',height:'100vh',position:'relative',zIndex:1}}>
      <div style={{position:'fixed',top:4,left:12,zIndex:50,display:'flex',alignItems:'center',gap:8,fontSize:11,fontFamily:'monospace',color:'var(--fg-dim)',pointerEvents:'none'}}>
        <span className="live-dot" />
        <span style={{letterSpacing:'0.1em'}}>开阳 系统:运行中</span>
        <span style={{color:'var(--fg-dim)',opacity:0.5}}>| TC-{status.includes('critical')?'3':status.includes('high')?'2':'1'}/5</span>
        <span style={{color:'var(--fg-dim)',opacity:0.5}}>| {stats.sources}SRC | {stats.intel}ART | {stats.entities}ENT</span>
      </div>
      <div style={{display:'flex',flex:1,overflow:'hidden'}}>
        <div style={{flex:1,position:'relative'}}>
          <div style={{display:viewMode==='2d'?'block':'none',width:'100%',height:'100%'}}>
            <MapView events={events} searchResults={searchResults} annotations={annotations} chain={chain} flyTo={flyTo} topicLayers={topicLayers} activeTopics={activeTopics} onToggleTopic={toggleTopic}/>
          </div>
          <div style={{display:viewMode==='3d'?'block':'none',width:'100%',height:'100%'}}>
            <GlobeView events={[...events, ...searchResults]} onZoomToMap={() => setViewMode('2d')}/>
          </div>
          <button onClick={() => setViewMode(v => v==='2d'?'3d':'2d')}
            style={{position:'absolute',top:80,left:10,zIndex:1000,
              background:'var(--bg-card)',border:'1px solid var(--border)',color:'var(--fg)',
              padding:'4px 10px',borderRadius:4,fontSize:12,cursor:'pointer'}}>
            {viewMode==='2d'?'🌍':'🗺️'}
          </button>
        </div>
        <Sidebar briefing={briefing} chatMessages={chatMessages} onSearch={doSearch} onChat={doChat} onClearAnnotations={clearAnnotations} onFlyTo={(lat,lng) => setFlyTo({lat,lng})} status={status} stats={stats}/>
      </div>
      {tickerItems.length > 0 && (
        <div className="ticker-bar">
          <div className="ticker-content">
            <span className="ticker-label"><span className="live-dot" style={{width:6,height:6}} />LIVE</span>
            {[...tickerItems, ...tickerItems].map((t, i) => {
              return <span key={i} className="ticker-item">
                <span className="dot" style={{background:'var(--green)'}} />
                <span style={{color:'var(--fg-dim)',opacity:0.5}}>{t.time}</span>
                <span style={{color:'var(--fg)'}}>{t.title}</span>
                <span style={{color:'var(--fg-dim)',fontSize:10,opacity:0.7}}>{t.source}</span>
              </span>
            })}
          </div>
        </div>
      )}
    </div>
  )
}
