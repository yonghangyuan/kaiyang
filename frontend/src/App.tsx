import { useState, useEffect } from 'react'
import MapView from './components/MapView'
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
  const [status, setStatus] = useState('ready')
  const [stats, setStats] = useState<Stats>({sources:0, intel:0, events:0, entities:0})

  const loadEvents = async () => {
    try { const d = await api.events(); setEvents(d.points||[]); setStatus('Events: '+d.count) } catch { setStatus('load failed') }
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
          setStatus(`new: ${d.new_items} items` + (d.new_events ? ` +${d.new_events} events` : ''))
          setTimeout(() => { loadEvents(); loadStats() }, 2000)
        }
      } catch {}
    }
    es.onerror = () => { /* auto-reconnect built into EventSource */ }
    return () => es.close()
  }, [])

  useEffect(() => { loadEvents(); loadAnnotations(); loadStats() }, [])

  const doSearch = async (query:string) => {
    setStatus('searching...')
    try { const d = await api.search(query); setSearchResults(d.points||[]); setBriefing(d); setStatus(d.point_count+' points') } catch(e:any) { setStatus('search failed') }
  }

  const doChat = async (msg:string) => {
    const now = new Date().toLocaleTimeString()
    setChatMessages(p=>[...p,{role:'user',content:msg,time:now}])
    setStatus('thinking...')
    const [chatR,searchR] = await Promise.allSettled([api.chat(msg), api.search(msg, 20)])
    if(chatR.status==='fulfilled'){
      const d=chatR.value
      setChatMessages(p=>[...p,{role:'ai',content:(d.reply||'').replace(/\*\*/g,'').replace(/^#{1,4}\s/gm,'').replace(/^---+/gm,'').replace(/```[\s\S]*?```/g,'').replace(/`([^`]+)`/g,'$1').trim(),time:new Date().toLocaleTimeString()}])
      setStatus(d.model||'replied')
      try{const ad=await api.annotations.fromText(d.reply);if(ad.ok){loadAnnotations();setStatus(s=>s+' | '+ad.coordinates_count+' annotations')}}catch{}
    }
    if(searchR.status==='fulfilled'){setSearchResults(searchR.value.points||[]);setBriefing(searchR.value)}
  }

  const clearAnnotations = () => { api.annotations.clear(); loadAnnotations() }

  return (
    <div style={{display:'flex',height:'100vh',position:'relative',zIndex:1}}>
      <div style={{flex:1}}><MapView events={events} searchResults={searchResults} annotations={annotations}/></div>
      <Sidebar briefing={briefing} chatMessages={chatMessages} onSearch={doSearch} onChat={doChat} onClearAnnotations={clearAnnotations} status={status} stats={stats}/>
    </div>
  )
}
