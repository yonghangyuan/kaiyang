import { useState } from 'react'
import EntityGraph from './EntityGraph'
import WordCloud from './WordCloud'
import TrendChart from './TrendChart'
import LiveFeed from './LiveFeed'
import EntityProfile from './EntityProfile'

interface Briefing { query: string; summary: string; point_count: number; timeline_count: number; web_count?: number; points: any[]; timeline: any[] }

interface Props {
  briefing: Briefing | null; chatMessages: {role:string;content:string;time:string}[]
  onSearch: (q: string) => void; onChat: (msg: string) => void; status: string
  onClearAnnotations?: () => void
  onFlyTo?: (lat: number, lng: number) => void
  stats?: {sources:number; intel:number; events:number; entities:number}
}

export default function Sidebar({ briefing, chatMessages, onSearch, onChat, status, onClearAnnotations, onFlyTo, stats }: Props) {
  const [tab, setTab] = useState<'live'|'feed'|'chat'>('live')
  const [input, setInput] = useState('')
  const [graphEntity, setGraphEntity] = useState<string | null>(null)
  const [profileEntity, setProfileEntity] = useState<string | null>(null)
  const send = () => { const msg = input.trim(); if (!msg) return; setInput(''); tab === 'chat' ? onChat(msg) : onSearch(msg) }

  const tColor = (t: any) => t.type==='web'?'#a855f7':t.type==='event'?'#eab308':'#3b82f6'

  return (
    <div style={{ width: 380, background: 'var(--bg-card)', borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
        {(['live','feed','chat'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            flex: 1, padding: 8, textAlign: 'center' as const, fontSize: 11, fontWeight: 700, cursor: 'pointer',
            letterSpacing: '0.05em', fontFamily: 'monospace',
            background: 'transparent', color: tab===t ? 'var(--accent)' : 'var(--fg-dim)',
            border: 'none', borderBottom: tab===t ? '2px solid var(--accent)' : '2px solid transparent'
          }}>{t.toUpperCase()}</button>
        ))}
      </div>
      {stats && <div style={{ display:'flex', gap:8, padding:'6px 12px', background:'#131a35', borderBottom:'1px solid var(--border)', fontSize:11 }}>
        <span title="Sources">{stats.sources}源</span>
        <span title="Intel items" style={{color:'#3b82f6'}}>{stats.intel}条</span>
        <span title="Events" style={{color:'#eab308'}}>{stats.events}事件</span>
        <span title="Entities" style={{color:'#a855f7'}}>{stats.entities}实体</span>
        <span style={{marginLeft:'auto',color:'#64748b'}}>●Event ●EQ ●Social ●Search ●Anno</span>
      </div>}
      <div style={{ flex: 1, overflow: 'auto', padding: '10px 12px', fontSize: 13 }}>
        {tab === 'live' && (
          <div>
            {profileEntity ? (
              <EntityProfile entityId={profileEntity} onClose={() => setProfileEntity(null)} />
            ) : (
              <LiveFeed onSelectCountry={c => { onSearch(c) }} onSelectEntity={id => setProfileEntity(id)} onFlyTo={onFlyTo} />
            )}
            {briefing && briefing.summary && (
              <div style={{background:'var(--bg-card)',padding:10,borderRadius:6,marginTop:8,borderLeft:'3px solid var(--accent)'}}>
                <div style={{fontSize:11,color:'var(--fg-dim)',marginBottom:4}}>Search: {briefing.query}</div>
                <div style={{fontSize:12,lineHeight:1.6}}>{briefing.summary.replace(/\*\*/g,'').replace(/^#{1,4}\s/gm,'').trim()}</div>
                <div style={{fontSize:11,color:'var(--fg-dim)',marginTop:4}}>{briefing.timeline_count} items</div>
              </div>
            )}
          </div>
        )}
          <div>
            {briefing.summary && <div style={{ background: 'var(--bg-card)', padding: 10, borderRadius: 6, marginBottom: 12, borderLeft: '3px solid var(--accent)', lineHeight: 1.6 }}>{briefing.summary.replace(/\*\*/g,'').replace(/^#{1,4}\s/gm,'').replace(/^---+/gm,'').replace(/```[\s\S]*?```/g,'').replace(/`([^`]+)`/g,'$1').trim()}</div>}
            <div style={{ color: 'var(--yellow)', marginBottom: 4 }}>Timeline ({briefing.timeline_count}{briefing.web_count ? ' + web'+briefing.web_count : ''})</div>
            {briefing.timeline.slice(0,30).map((t:any,i:number) => (
              <div key={i} style={{ padding: '6px 10px', borderLeft: '2px solid '+tColor(t), marginLeft: 10, marginBottom: 4, fontSize: 12 }}>
                <div style={{ color: 'var(--fg-dim)', fontSize: 10 }}>{(t.time||'').substring(0,16)}</div>
                <div>{(t.title||'').substring(0,80)}</div>
                {t.severity ? <div className="importance-bar" style={{width:Math.min(t.severity*10,100)+'%',background:`hsl(${(10-t.severity)*12},80%,50%)`}} /> : null}
                <div style={{ color: 'var(--fg-dim)', fontSize: 10 }}>
                  {t.type==='web'?'web ':''}{t.country||''}{t.severity?' | imp:'+t.severity+'/10':''}
                  {t.ai_topic ? ' | '+t.ai_topic : ''}
                </div>
              </div>
            ))}
          </div>
        ) : tab==='feed' ? (
          <div style={{fontSize:12}}>
            {profileEntity ? (
              <EntityProfile entityId={profileEntity} onClose={() => setProfileEntity(null)} />
            ) : (
              <>
                <WordCloud />
                <TrendChart />
                {graphEntity && <EntityGraph entityId={graphEntity} onClose={()=>setGraphEntity(null)} />}
              </>
            )}
          </div>
        ) : <div style={{ textAlign: 'center', padding: 40, color: 'var(--fg-dim)', fontSize: 13 }}>Enter search keywords</div>)}
        {tab === 'chat' && (
          <div>
            {chatMessages.length===0 && <div style={{ textAlign: 'center', padding: 40, color: 'var(--fg-dim)', fontSize: 13 }}>Kaiyang AI Assistant</div>}
            {chatMessages.map((m,i) => (
              <div key={i} style={{
                padding: '8px 10px', margin: '4px 0', borderRadius: 6, lineHeight: 1.5, fontSize: 13,
                background: m.role==='user'?'#1e40af':'#131a35',
                border: m.role==='user'?'none':'1px solid var(--border)',
                marginLeft: m.role==='user'?'auto':0, maxWidth: '95%',
                textAlign: (m.role==='user'?'right':'left') as any
              }}>
                <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
                <div style={{ fontSize: 10, color: 'var(--fg-dim)', marginTop: 2 }}>{m.time}</div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div style={{ fontSize: 11, padding: '4px 12px', background: '#0a0e27', color: 'var(--fg-dim)' }}>{status}</div>
      <div style={{ background: 'var(--bg-card)', padding: 8, borderTop: '1px solid var(--border)', display: 'flex', gap: 6 }}>
        <input value={input} onChange={e => setInput(e.target.value)} onKeyPress={e => e.key==='Enter'&&send()}
          placeholder={tab==='chat'?'Message...':'Search...'}
          style={{ flex: 1, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--fg)', padding: '8px 10px', borderRadius: 4, fontSize: 13 }} />
        <button onClick={send} style={{ background: 'var(--accent)', color: '#fff', border: 'none', padding: '8px 14px', borderRadius: 4, fontSize: 12, cursor: 'pointer' }}>Send</button>
        {onClearAnnotations && <button onClick={onClearAnnotations} style={{ background: 'var(--bg-hover)', color: '#fff', border: 'none', padding: '8px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}>Clear</button>}
      </div>
    </div>
  )
}
