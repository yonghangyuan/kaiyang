import { useState, useEffect } from 'react'
import MapView from './components/MapView'
import Sidebar from './components/Sidebar'

interface GeoPoint { id: string; title: string; lat: number; lng: number; country_code?: string; severity?: number; confidence?: number; source_count?: number; time_start?: string; published_at?: string; type?: string; url?: string }
interface Briefing { query: string; summary: string; point_count: number; timeline_count: number; web_count?: number; points: GeoPoint[]; timeline: any[] }
interface Annotation { id: string; name: string; description?: string; type: string; coordinates: any; style?: any }

export default function App() {
  const [events, setEvents] = useState<GeoPoint[]>([])
  const [searchResults, setSearchResults] = useState<GeoPoint[]>([])
  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [briefing, setBriefing] = useState<Briefing | null>(null)
  const [chatMessages, setChatMessages] = useState<{role:string;content:string;time:string}[]>([])
  const [status, setStatus] = useState('ready')

  const loadEvents = async () => {
    try {
      const r = await fetch('/api/map/plot', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:100})})
      const d = await r.json(); setEvents(d.points||[]); setStatus('Events: '+d.count)
    } catch { setStatus('load failed') }
  }
  const loadAnnotations = async () => {
    try { const r = await fetch('/api/annotations'); setAnnotations((await r.json()).annotations||[]) } catch {}
  }
  useEffect(() => { loadEvents(); loadAnnotations() }, [])

  const doSearch = async (query:string) => {
    setStatus('searching...')
    try {
      const r = await fetch('/api/search/briefing', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,limit:30})})
      const d = await r.json(); setSearchResults(d.points||[]); setBriefing(d)
      setStatus(d.point_count+' points, '+d.timeline_count+' timeline')
    } catch(e:any) { setStatus('search failed: '+e.message) }
  }

  const doChat = async (msg:string) => {
    const now = new Date().toLocaleTimeString()
    setChatMessages(p=>[...p,{role:'user',content:msg,time:now}])
    setStatus('thinking...')
    const [chatR,searchR] = await Promise.allSettled([
      fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})}),
      fetch('/api/search/briefing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:msg,limit:20})})
    ])
    if(chatR.status==='fulfilled'){
      try{
        const d=await chatR.value.json()
        setChatMessages(p=>[...p,{role:'ai',content:(d.reply||'').replace(/\*\*/g,'').replace(/^#{1,4}\s/gm,'').replace(/^---+/gm,'').replace(/```[\s\S]*?```/g,'').replace(/`([^`]+)`/g,'$1').replace(/^>\s/gm,'').trim(),time:new Date().toLocaleTimeString()}])
        setStatus(d.model||'replied')
        const ar=await fetch('/api/annotations/from-text',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:d.reply})})
        const ad=await ar.json(); if(ad.ok){loadAnnotations();setStatus(s=>s+' | '+ad.coordinates_count+' annotations')}
      }catch{}
    }
    if(searchR.status==='fulfilled'){
      try{const d=await searchR.value.json();setSearchResults(d.points||[]);setBriefing(d)}catch{}
    }
    if(chatR.status==='rejected' && searchR.status==='rejected'){
      setChatMessages(p=>[...p,{role:'ai',content:'connection failed',time:now}])
    }
  }

  const clearAnnotations = () => { fetch('/api/annotations',{method:'DELETE'}); loadAnnotations() }

  return (
    <div style={{display:'flex',height:'100vh',background:'#0a0e27',color:'#c9d1d9',fontFamily:'-apple-system,sans-serif'}}>
      <div style={{flex:1}}><MapView events={events} searchResults={searchResults} annotations={annotations}/></div>
      <Sidebar briefing={briefing} chatMessages={chatMessages} onSearch={doSearch} onChat={doChat} onClearAnnotations={clearAnnotations} status={status}/>
    </div>
  )
}
