import { useState, useEffect, useRef } from 'react'

interface TimelineNode {
  kind: 'chain' | 'intel' | 'finding'
  id: string; title: string; time: string
  relation?: string; severity?: number; source?: string; url?: string
  finding_type?: string; status?: string; proposal?: any
  sources: SourceReport[]
}
interface SourceReport {
  title: string; url: string; source: string; time: string; summary?: string
}
interface WatchIssue {
  id: string; title: string; watch: number; watch_keywords?: string; status: string
}

const fetchJ = async (url: string, init?: RequestInit) => {
  try { const r = await fetch(url, init); return await r.json() } catch { return null }
}

const kindStyle: Record<string, { dot: string; label: string; color: string }> = {
  chain:  { dot: '●', label: '事件', color: 'var(--accent)' },
  intel:  { dot: '◆', label: '报道', color: '#eab308' },
  finding:{ dot: '✦', label: '发现', color: 'var(--purple)' },
}
const stLabel: Record<string, string> = { auto: '已入库', pending: '待审', approved: '已执行', rejected: '已驳回' }
const stColor: Record<string, string> = { auto: 'var(--green)', pending: 'var(--yellow)', approved: 'var(--accent)', rejected: '#ef4444' }

export default function WatchPanel() {
  const [issues, setIssues] = useState<WatchIssue[]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [nodes, setNodes] = useState<TimelineNode[]>([])
  const [poolN, setPoolN] = useState(0)
  const [modal, setModal] = useState<{ node: TimelineNode; sources: SourceReport[] } | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const loadIssues = async () => {
    const d = await fetchJ('/api/issues?limit=50')
    setIssues((d?.issues || []).map((i: any) => ({ ...i, watch: i.watch || 0, watch_keywords: i.watch_keywords || '' })))
  }
  useEffect(() => { loadIssues() }, [])

  const loadTimeline = async (id: string) => {
    const d = await fetchJ(`/api/issues/${id}/timeline`)
    setNodes(d?.nodes || [])
    setPoolN((d?.nodes || []).filter((n: TimelineNode) => n.kind === 'intel').length)
  }
  useEffect(() => { if (sel) loadTimeline(sel) }, [sel])

  const watching = issues.filter(i => i.watch)
  const current = issues.find(i => i.id === sel)
  const pendingCount = nodes.filter(n => n.kind === 'finding' && n.status === 'pending').length

  const openNode = async (node: TimelineNode) => {
    if (node.kind === 'intel') {
      setModal({ node, sources: node.sources })
      return
    }
    let sources: SourceReport[] = []
    if (node.kind === 'chain') {
      const evId = node.id.replace('chain-', '')
      const d = await fetchJ(`/api/events/${evId}/sources`)
      sources = d?.sources || []
    } else {
      const fid = node.id.replace('find-', '')
      const d = await fetchJ(`/api/findings/${fid}/sources`)
      sources = d?.sources || []
    }
    setModal({ node, sources })
  }

  const toggleWatch = async (issue: WatchIssue, on: boolean, kw?: string) => {
    const keywords = on ? (kw || issue.watch_keywords || '') : (issue.watch_keywords || '')
    if (on && !keywords.trim()) { setMsg('请先填订阅关键词'); return }
    setBusy(true)
    await fetchJ(`/api/issues/${issue.id}/watch`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on, keywords }),
    })
    await loadIssues(); setBusy(false); setMsg(on ? '追踪已开启' : '追踪已关闭')
    if (sel === issue.id) loadTimeline(issue.id)
  }

  const review = async (fid: string, approve: boolean) => {
    setBusy(true)
    await fetchJ(`/api/findings/${fid}/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve, note: '' }),
    })
    if (sel) loadTimeline(sel); setBusy(false)
  }

  const analyzeNow = async () => {
    if (!sel) return
    setBusy(true); setMsg('分析中...')
    const d = await fetchJ(`/api/issues/${sel}/analyze`, { method: 'POST' })
    setMsg(d?.error ? `失败: ${d.error}` : `完成: +${d?.notes || 0}笔记 +${d?.chains || 0}建议${d?.fallback ? ' (规则兜底)' : ''}`)
    if (sel) loadTimeline(sel); setBusy(false)
  }

  const fmtTime = (iso: string) => {
    if (!iso) return ''
    const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z')
    if (isNaN(d.getTime())) return iso.substring(0, 16)
    return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }

  const S: any = {
    sec: { background: 'var(--bg-card)', padding: 10, borderRadius: 6, marginBottom: 8, border: '1px solid var(--border)', fontSize: 12 },
    btn: (bg: string): any => ({ background: bg, color: '#fff', border: 'none', padding: '4px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer' }),
  }

  const modalRef = useRef<HTMLDivElement>(null)

  return (
    <div>
      {/* 追踪中的专题 */}
      <div style={S.sec}>
        <b style={{ fontSize: 10, color: 'var(--fg-dim)', letterSpacing: '0.05em' }}>追踪中 {watching.length}</b>
        {watching.map(i => (
          <div key={i.id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
            <span className="live-dot" style={{ width: 6, height: 6 }} />
            <a onClick={() => setSel(i.id)} style={{ flex: 1, cursor: 'pointer', color: sel === i.id ? 'var(--accent)' : 'var(--fg)' }}>{i.title}</a>
            <button onClick={() => toggleWatch(i, false)} disabled={busy} style={{ ...S.btn('#475569'), fontSize: 10 }}>停</button>
          </div>
        ))}
        {watching.length === 0 && <div style={{ color: 'var(--fg-dim)', marginTop: 6, fontSize: 11 }}>暂无。从下面列表开启</div>}
      </div>

      {/* 时间链 */}
      {sel && current && (
        <div style={S.sec}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <b style={{ flex: 1 }}>时间链</b>
            <span style={{ fontSize: 10, color: 'var(--fg-dim)' }}>{nodes.length} 节点</span>
            <button onClick={analyzeNow} disabled={busy} style={S.btn('var(--accent)')}>立即分析</button>
          </div>
          {pendingCount > 0 && <div style={{ color: 'var(--yellow)', fontSize: 11 }}>⚠ {pendingCount} 条结构性建议待审</div>}
          {current.watch_keywords && <div style={{ fontSize: 10, color: 'var(--fg-dim)' }}>订阅: {current.watch_keywords}</div>}
        </div>
      )}

      {sel && nodes.length === 0 && (
        <div style={{ ...S.sec, color: 'var(--fg-dim)', textAlign: 'center' }}>
          暂无节点。等新情报命中关键词，或点「立即分析」
        </div>
      )}

      {/* 时间线主体：最新→最旧，竖线贯穿 */}
      {sel && nodes.length > 0 && (
        <div style={{ position: 'relative', paddingLeft: 18, marginBottom: 8 }}>
          {/* 竖线 */}
          <div style={{ position: 'absolute', left: 6, top: 8, bottom: 8, width: 2, background: 'var(--border)' }} />
          {nodes.map(n => {
            const ks = kindStyle[n.kind]
            return (
              <div key={n.id} style={{ position: 'relative', marginBottom: 2 }}>
                {/* 节点圆点 */}
                <div style={{
                  position: 'absolute', left: -17, top: 10, width: 10, height: 10, borderRadius: '50%',
                  background: n.kind === 'finding' && n.status === 'pending' ? 'var(--yellow)' : ks.color,
                  boxShadow: '0 0 0 2px var(--bg-card)',
                }} />
                <div
                  onClick={() => openNode(n)}
                  style={{ cursor: 'pointer', padding: '6px 8px', borderRadius: 4, background: '#0d1330',
                    borderLeft: `2px solid ${n.kind === 'finding' && n.status === 'pending' ? 'var(--yellow)' : ks.color}` }}
                >
                  <div style={{ display: 'flex', gap: 6, fontSize: 10, marginBottom: 2, alignItems: 'center' }}>
                    <span style={{ color: ks.color }}>{ks.label}</span>
                    {n.relation && <span style={{ color: 'var(--fg-dim)' }}>{n.relation}</span>}
                    {n.kind === 'intel' && <span style={{ color: 'var(--fg-dim)' }}>{n.source}</span>}
                    {n.kind === 'finding' && <span style={{ color: stColor[n.status || 'auto'] }}>{stLabel[n.status || 'auto']}</span>}
                    <span style={{ color: 'var(--fg-dim)', marginLeft: 'auto' }}>{fmtTime(n.time)}</span>
                  </div>
                  <div style={{ lineHeight: 1.45, fontSize: 12 }}>{n.title?.substring(0, 90)}</div>
                  {n.proposal && (
                    <div style={{ fontSize: 10, color: 'var(--fg-dim)', marginTop: 2 }}>
                      建议: 新建事件「{n.proposal.title}」[{n.proposal.relation}]
                    </div>
                  )}
                  {n.status === 'pending' && (
                    <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                      <button onClick={e => { e.stopPropagation(); review(n.id.replace('find-', ''), true) }} disabled={busy} style={S.btn('#16a34a')}>批准</button>
                      <button onClick={e => { e.stopPropagation(); review(n.id.replace('find-', ''), false) }} disabled={busy} style={S.btn('#ef4444')}>驳回</button>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* 全部 Issue 列表（开启追踪入口） */}
      <div style={S.sec}>
        <b style={{ fontSize: 10, color: 'var(--fg-dim)' }}>全部议题</b>
        {issues.filter(i => !i.watch).map(i => (
          <div key={i.id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 11 }}>
            <a onClick={() => setSel(i.id)} style={{ flex: 1, cursor: 'pointer', color: sel === i.id ? 'var(--accent)' : 'var(--fg)' }}>{i.title}</a>
            <button onClick={() => toggleWatch(i, true, undefined)} disabled={busy} style={{ ...S.btn('#1d4ed8'), fontSize: 10 }}>追踪</button>
          </div>
        ))}
      </div>

      {msg && <div style={{ fontSize: 11, color: 'var(--fg-dim)', textAlign: 'center' }}>{msg}</div>}

      {/* 源报道弹窗 */}
      {modal && (
        <div
          onClick={() => setModal(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
        >
          <div
            ref={modalRef}
            onClick={e => e.stopPropagation()}
            style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, width: 560, maxWidth: '90vw', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}
          >
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <div style={{ flex: 1, fontSize: 13, fontWeight: 700, lineHeight: 1.4 }}>{modal.node.title}</div>
              <span style={{ fontSize: 10, color: kindStyle[modal.node.kind].color }}>{kindStyle[modal.node.kind].label}</span>
              <button onClick={() => setModal(null)} style={{ background: 'none', border: 'none', color: 'var(--fg-dim)', cursor: 'pointer', fontSize: 16 }}>✕</button>
            </div>
            <div style={{ padding: '10px 16px', overflow: 'auto', flex: 1 }}>
              {modal.node.kind === 'finding' && modal.node.proposal && (
                <div style={{ fontSize: 11, color: 'var(--fg-dim)', marginBottom: 8 }}>
                  建议: 新建事件「{modal.node.proposal.title}」[{modal.node.proposal.relation}] — {modal.node.proposal.evidence}
                </div>
              )}
              {modal.sources.length === 0 && (
                <div style={{ color: 'var(--fg-dim)', fontSize: 12, textAlign: 'center', padding: 20 }}>
                  {modal.node.kind === 'intel' ? '无源报道' : '此节点暂无关联源报道'}
                </div>
              )}
              {modal.sources.map((s, i) => (
                <div key={i} style={{ padding: 10, background: '#0d1330', borderRadius: 6, marginBottom: 8, borderLeft: '2px solid var(--yellow)' }}>
                  <div style={{ display: 'flex', gap: 6, fontSize: 10, marginBottom: 4 }}>
                    <span style={{ color: 'var(--yellow)' }}>{s.source}</span>
                    <span style={{ color: 'var(--fg-dim)' }}>{fmtTime(s.time)}</span>
                  </div>
                  <a href={s.url} target="_blank" rel="noreferrer" style={{ fontSize: 13, color: 'var(--fg)', textDecoration: 'none' }}>
                    {s.title} ↗
                  </a>
                  {s.summary && <div style={{ fontSize: 11, color: 'var(--fg-dim)', marginTop: 4, lineHeight: 1.5 }}>{s.summary.substring(0, 200)}</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
