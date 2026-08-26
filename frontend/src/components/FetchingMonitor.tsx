import { useState, useEffect } from 'react'

interface PEvent {
  ts: string; type: string; source?: string
  fetched?: number; stored?: number; ok?: boolean
  error?: string; elapsed_ms?: number; kind?: string
}

export default function FetchingMonitor() {
  const [events, setEvents] = useState<PEvent[]>([])
  const [stats, setStats] = useState<{runs:number;fails:number;stored:number} | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    // 拉最近 + 统计
    fetch('/api/pipeline/events?limit=50').then(r => r.json())
      .then(d => setEvents((d?.events || []).reverse())).catch(() => {})
    fetch('/api/pipeline/stats?hours=24').then(r => r.json())
      .then(setStats).catch(() => {})
    // SSE 跟流
    const es = new EventSource('/api/pipeline/stream')
    es.onmessage = (evt) => {
      try {
        const d = JSON.parse(evt.data)
        if (d.type === 'pipeline_run') {
          setEvents(p => [...p.slice(-99), d])
        }
      } catch {}
    }
    es.onerror = () => {}
    return () => es.close()
  }, [])

  const fails = events.filter(e => e.ok === false).length
  const totalStored = events.reduce((s, e) => s + (e.stored || 0), 0)

  return (
    <div style={{ background: 'var(--bg-card)', padding: 10, borderRadius: 6, border: '1px solid var(--border)', fontSize: 12, marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }} onClick={() => setOpen(v => !v)}>
        <span className="live-dot" style={{ width: 6, height: 6 }} />
        <b>管道监控</b>
        {stats && (
          <span style={{ fontSize: 10, color: 'var(--fg-dim)' }}>
            24h: {stats.runs}轮 / {stats.fails}败 / +{stats.stored}条
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 10, color: fails > 0 ? '#ef4444' : 'var(--green)' }}>
          {fails > 0 ? `${fails} 失败` : '正常'}
        </span>
      </div>
      {open && (
        <div style={{ marginTop: 8, maxHeight: 260, overflow: 'auto' }}>
          {events.length === 0 && <div style={{ color: 'var(--fg-dim)', fontSize: 11 }}>暂无事件（管道每 60-90s 一轮）</div>}
          {events.slice().reverse().map((e, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, fontSize: 10, padding: '2px 0', color: 'var(--fg-dim)' }}>
              <span style={{ color: 'var(--fg-dim)', opacity: 0.6 }}>{(e.ts || '').substring(11, 19)}</span>
              <span style={{ color: e.ok === false ? '#ef4444' : (e.stored || 0) > 0 ? 'var(--green)' : 'var(--fg-dim)' }}>
                {e.ok === false ? '✗' : (e.stored || 0) > 0 ? '●' : '·'}
              </span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--fg)' }}>
                {e.source || e.type}
                {e.error ? ` — ${e.error.substring(0, 50)}` : ''}
              </span>
              {(e.fetched || 0) > 0 && <span>{e.fetched}→{e.stored}</span>}
              {e.elapsed_ms != null && <span style={{ opacity: 0.5 }}>{e.elapsed_ms}ms</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
