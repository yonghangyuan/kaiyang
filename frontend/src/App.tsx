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
        if (d.type === 'fetch_complete' && d.new_items > 0) {
          setStatus(`新增: ${d.new_items} 条` + (d.new_events ? ` +${d.new_events} events` : ''))
          loadEvents(); loadStats()
        }
      } catch {}
    }
    es.onerror = () => { /* auto-reconnect built into EventSource */ }
    return () => es.close()
  }, [])

  // Periodic fallback refresh (every 90s)
  useEffect(() => { const t = setInterval(() => { loadEvents(); loadStats() }, 90000); return () => clearInterval(t) }, [])
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

  // Build ticker items from events + search results (more real-time)
  const tickerItems = [
    ...events.slice(0, 20).map(e => ({
      title: (e.title||'').substring(0,80),
      country: e.country_code||'',
      severity: e.severity||1,
      time: (e.time_start||e.published_at||'').substring(11,16),
      type: 'event' as const,
    })),
    ...searchResults.slice(0, 10).map(e => ({
      title: (e.title||'').substring(0,80),
      country: e.country_code||'',
      severity: 1,
      time: (e.published_at||e.time_start||'').substring(11,16),
      type: 'search' as const,
    })),
  ].sort((a,b) => b.time.localeCompare(a.time)).slice(0, 30)

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
            <MapView events={events} searchResults={searchResults} annotations={annotations} chain={chain} flyTo={flyTo}/>
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
              const c = t.severity >= 7 ? 'var(--red)' : t.severity >= 5 ? 'var(--orange)' : t.severity >= 3 ? 'var(--yellow)' : 'var(--green)'
              return <span key={i} className="ticker-item">
                <span className="dot" style={{background:c}} />
                <span style={{color:'var(--fg-dim)',opacity:0.5}}>{t.time}</span>
                <span style={{color:'var(--fg)'}}>{t.title}</span>
                {t.country && <span style={{color:c,fontSize:10}}>[{t.country}]</span>}
              </span>
            })}
          </div>
        </div>
      )}
    </div>
  )
}
