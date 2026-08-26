import { useState } from 'react'
import EntityGraph from './EntityGraph'
import WordCloud from './WordCloud'
import TrendChart from './TrendChart'
import PredictionCard from './PredictionCard'
import ThreatDashboard from './ThreatDashboard'
import BriefingCard from './BriefingCard'
import LiveFeed from './LiveFeed'
import EntityProfile from './EntityProfile'
import WatchPanel from './WatchPanel'
import FetchingMonitor from './FetchingMonitor'

interface Briefing { query: string; summary: string; point_count: number; timeline_count: number; web_count?: number; points: any[]; timeline: any[] }

interface Props {
  briefing: Briefing | null; chatMessages: {role:string;content:string;time:string}[]
  onSearch: (q: string) => void; onChat: (msg: string) => void; status: string
  onClearAnnotations?: () => void; onFlyTo?: (lat: number, lng: number) => void
  stats?: {sources:number; intel:number; events:number; entities:number}
}

export default function Sidebar({ briefing, chatMessages, onSearch, onChat, status, onClearAnnotations, onFlyTo, stats }: Props) {
  const [tab, setTab] = useState<'live'|'feed'|'chat'|'watch'>('live')
  const [input, setInput] = useState('')
  const [graphEntity, setGraphEntity] = useState<string | null>(null)
  const [profileEntity, setProfileEntity] = useState<string | null>(null)
  const send = () => { const msg = input.trim(); if (!msg) return; setInput(''); tab === 'chat' ? onChat(msg) : onSearch(msg) }

  const tColor = (t: any) => t.type==='web'?'#a855f7':t.type==='event'?'#eab308':'#3b82f6'
  const S: any = { tabBtn: (active: boolean) => ({
    flex:1,padding:8,textAlign:'center',fontSize:11,fontWeight:700,cursor:'pointer',
    letterSpacing:'0.05em',fontFamily:'monospace',background:'transparent',
    color:active?'var(--accent)':'var(--fg-dim)',border:'none',
    borderBottom:active?'2px solid var(--accent)':'2px solid transparent'
  })}

  return (
    <div style={{ width:380, background:'var(--bg-card)', borderLeft:'1px solid var(--border)', display:'flex', flexDirection:'column' }}>
      <div style={{ display:'flex', borderBottom:'1px solid var(--border)' }}>
        {(['live','feed','chat','watch'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={S.tabBtn(tab===t)}>{{live:'实时',feed:'分析',chat:'对话',watch:'专题'}[t]}</button>
        ))}
      </div>
      {stats && <div style={{ display:'flex',gap:8,padding:'6px 12px',background:'#131a35',borderBottom:'1px solid var(--border)',fontSize:11 }}>
        <span>{stats.sources}源</span>
        <span style={{color:'var(--accent)'}}>{stats.intel}条</span>
        <span style={{color:'var(--yellow)'}}>{stats.events}事件</span>
        <span style={{color:'var(--purple)'}}>{stats.entities}实体</span>
        <span style={{marginLeft:'auto',color:'var(--fg-dim)',fontSize:10}}>●EVT ●EQ ●SOC ●SRH ●ANO</span>
      </div>}
      <div style={{ flex:1, overflow:'auto', padding:'10px 12px', fontSize:13 }}>
        {tab === 'live' && (
          profileEntity
            ? <EntityProfile entityId={profileEntity} onClose={() => setProfileEntity(null)} />
            : <>
                <LiveFeed onSelectCountry={c => onSearch(c)} onSelectEntity={id => setProfileEntity(id)} onFlyTo={onFlyTo} />
                {briefing?.summary && <div style={{background:'var(--bg-card)',padding:10,borderRadius:6,marginTop:8,borderLeft:'3px solid var(--accent)',fontSize:12,lineHeight:1.6}}>
                  <b style={{fontSize:10,color:'var(--fg-dim)'}}>搜索: {briefing.query}</b><br/>
                  {briefing.summary.replace(/\*\*/g,'').replace(/^#{1,4}\s/gm,'').trim()}
                  <div style={{fontSize:10,color:'var(--fg-dim)',marginTop:4}}>{briefing.timeline_count} 条</div>
                </div>}
              </>
        )}
        {tab === 'feed' && (
          profileEntity
            ? <EntityProfile entityId={profileEntity} onClose={() => setProfileEntity(null)} />
            : <>
                <FetchingMonitor /><BriefingCard /><ThreatDashboard /><WordCloud /><TrendChart /><PredictionCard />
                {graphEntity && <EntityGraph entityId={graphEntity} onClose={() => setGraphEntity(null)} />}
              </>
        )}
        {tab === 'watch' && <WatchPanel />}
        {tab === 'chat' && (
          chatMessages.length===0
            ? <div style={{textAlign:'center',padding:40,color:'var(--fg-dim)',fontSize:13}}>开阳 AI 助手</div>
            : chatMessages.map((m,i) => (
                <div key={i} style={{padding:'8px 10px',margin:'4px 0',borderRadius:6,lineHeight:1.5,fontSize:13,
                  background:m.role==='user'?'#1e40af':'var(--bg-card)',border:m.role==='user'?'none':'1px solid var(--border)',
                  marginLeft:m.role==='user'?'auto':0,maxWidth:'95%',textAlign:m.role==='user'?'right':'left'}}>
                  <div style={{whiteSpace:'pre-wrap'}}>{m.content}</div>
                  <div style={{fontSize:10,color:'var(--fg-dim)',marginTop:2}}>{m.time}</div>
                </div>
              ))
        )}
      </div>
      <div style={{fontSize:11,padding:'4px 12px',background:'#0a0e27',color:'var(--fg-dim)'}}>{status}</div>
      <div style={{background:'var(--bg-card)',padding:8,borderTop:'1px solid var(--border)',display:'flex',gap:6}}>
        <input value={input} onChange={e => setInput(e.target.value)} onKeyPress={e => e.key==='Enter'&&send()}
          placeholder={tab==='chat'?'输入消息...':'搜索...'}
          style={{flex:1,background:'var(--bg-card)',border:'1px solid var(--border)',color:'var(--fg)',padding:'8px 10px',borderRadius:4,fontSize:13}} />
        <button onClick={send} style={{background:'var(--accent)',color:'#fff',border:'none',padding:'8px 14px',borderRadius:4,fontSize:12,cursor:'pointer'}}>发送</button>
        {onClearAnnotations && <button onClick={onClearAnnotations} style={{background:'var(--bg-hover)',color:'#fff',border:'none',padding:'8px 10px',borderRadius:4,fontSize:11,cursor:'pointer'}}>清除</button>}
      </div>
    </div>
  )
}
