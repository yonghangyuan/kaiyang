import { useState } from 'react'

interface Briefing { query: string; summary: string; point_count: number; timeline_count: number; web_count?: number; points: any[]; timeline: any[] }

interface Props {
  briefing: Briefing | null; chatMessages: {role:string;content:string;time:string}[]
  onSearch: (q: string) => void; onChat: (msg: string) => void; status: string
  onClearAnnotations?: () => void
  stats?: {sources:number; intel:number; events:number; entities:number}
}

export default function Sidebar({ briefing, chatMessages, onSearch, onChat, status, onClearAnnotations, stats }: Props) {
  const [tab, setTab] = useState<'search'|'chat'>('chat')
  const [input, setInput] = useState('')
  const send = () => { const msg = input.trim(); if (!msg) return; setInput(''); tab === 'search' ? onSearch(msg) : onChat(msg) }

  const tColor = (t: any) => t.type==='web'?'#a855f7':t.type==='event'?'#eab308':'#3b82f6'

  return (
    <div style={{ width: 380, background: 'var(--bg-card)', borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
        <button onClick={() => setTab('search')} style={{
          flex: 1, padding: 10, textAlign: 'center' as const, fontSize: 13, fontWeight: 600, cursor: 'pointer',
          background: tab==='search' ? '#0f1630' : '#131a35', color: tab==='search' ? '#e2c860' : '#64748b',
          border: 'none', borderBottom: tab==='search' ? '2px solid #e2c860' : '2px solid transparent'
        }}>Search</button>
        <button onClick={() => setTab('chat')} style={{
          flex: 1, padding: 10, textAlign: 'center' as const, fontSize: 13, fontWeight: 600, cursor: 'pointer',
          background: tab==='chat' ? '#0f1630' : '#131a35', color: tab==='chat' ? '#e2c860' : '#64748b',
          border: 'none', borderBottom: tab==='chat' ? '2px solid #e2c860' : '2px solid transparent'
        }}>Chat</button>
      </div>
      {stats && <div style={{ display:'flex', gap:8, padding:'6px 12px', background:'#131a35', borderBottom:'1px solid var(--border)', fontSize:11 }}>
        <span title="Sources">{stats.sources}源</span>
        <span title="Intel items" style={{color:'#3b82f6'}}>{stats.intel}条</span>
        <span title="Events" style={{color:'#eab308'}}>{stats.events}事件</span>
        <span title="Entities" style={{color:'#a855f7'}}>{stats.entities}实体</span>
        <span style={{marginLeft:'auto',color:'#64748b'}}>●Event ●EQ ●Social ●Search ●Anno</span>
      </div>}
      <div style={{ flex: 1, overflow: 'auto', padding: '10px 12px', fontSize: 13 }}>
        {tab === 'search' && (briefing ? (
          <div>
            {briefing.summary && <div style={{ background: 'var(--bg-card)', padding: 10, borderRadius: 6, marginBottom: 12, borderLeft: '3px solid var(--accent)', lineHeight: 1.6 }}>{briefing.summary.replace(/\*\*/g,'').replace(/^#{1,4}\s/gm,'').replace(/^---+/gm,'').replace(/```[\s\S]*?```/g,'').replace(/`([^`]+)`/g,'$1').trim()}</div>}
            <div style={{ color: 'var(--yellow)', marginBottom: 4 }}>Timeline ({briefing.timeline_count}{briefing.web_count ? ' + web'+briefing.web_count : ''})</div>
            {briefing.timeline.slice(0,30).map((t:any,i:number) => (
              <div key={i} style={{ padding: '6px 10px', borderLeft: '2px solid '+tColor(t), marginLeft: 10, marginBottom: 4, fontSize: 12 }}>
                <div style={{ color: 'var(--fg-dim)', fontSize: 10 }}>{(t.time||'').substring(0,16)}</div>
                <div>{(t.title||'').substring(0,80)}</div>
                <div style={{ color: 'var(--fg-dim)', fontSize: 10 }}>{t.type==='web'?'web ':''}{t.country||''}</div>
              </div>
            ))}
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
          placeholder={tab==='search'?'Search...':'Message...'}
          style={{ flex: 1, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--fg)', padding: '8px 10px', borderRadius: 4, fontSize: 13 }} />
        <button onClick={send} style={{ background: 'var(--accent)', color: '#fff', border: 'none', padding: '8px 14px', borderRadius: 4, fontSize: 12, cursor: 'pointer' }}>Send</button>
        {onClearAnnotations && <button onClick={onClearAnnotations} style={{ background: 'var(--bg-hover)', color: '#fff', border: 'none', padding: '8px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}>Clear</button>}
      </div>
    </div>
  )
}
