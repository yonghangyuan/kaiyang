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
interface InvestigateReport {
  id: string; title: string; subject: string; issue_id?: string | null
  kind: string; engine: string; evidence_count: number; published_at: string
  content?: string
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
    if (sel) loadTimeline(sel)
    loadIntake(); setBusy(false)
  }

  // ── 源准入收件箱 ──────────────────────────────────────────
  const [intake, setIntake] = useState<Finding[]>([])
  const loadIntake = async () => {
    const d = await fetchJ('/api/intake/pending')
    setIntake(d?.findings || [])
  }
  useEffect(() => { loadIntake() }, [])

  const analyzeNow = async () => {
    if (!sel) return
    setBusy(true); setMsg('分析中...')
    const d = await fetchJ(`/api/issues/${sel}/analyze`, { method: 'POST' })
    setMsg(d?.error ? `失败: ${d.error}` : `完成: +${d?.notes || 0}笔记 +${d?.chains || 0}建议${d?.fallback ? ' (规则兜底)' : ''}`)
    if (sel) loadTimeline(sel); setBusy(false)
  }

  // ── 调查报告 ──────────────────────────────────────────────
  const [reports, setReports] = useState<InvestigateReport[]>([])
  const [topicInput, setTopicInput] = useState('')
  const [reportView, setReportView] = useState<InvestigateReport | null>(null)

  const loadReports = async () => {
    const d = await fetchJ('/api/investigate/reports?limit=30')
    setReports(d?.reports || [])
  }
  useEffect(() => { loadReports() }, [])

  const openReport = async (rid: string) => {
    const d = await fetchJ(`/api/investigate/reports/${rid}`)
    if (d && !d.error) setReportView(d)
  }

  // 生成调查报告（专题版或自由主题版）。同步请求, 分析员跑 30-90s。
  const generateReport = async (body: Record<string, unknown>) => {
    setBusy(true); setMsg('调查中... 分析员在成文, 约 1 分钟')
    try {
      const r = await fetch('/api/investigate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      if (d?.ok) {
        setMsg(`报告已生成 (${d.engine}, 证据${d.stats?.evidence_count ?? 0}条)`)
        await loadReports()
        setReportView({ id: d.report_id, title: `调查报告: ${d.pack?.subject || ''}`, subject: d.pack?.subject || '', kind: d.pack?.kind || '', engine: d.engine, evidence_count: d.stats?.evidence_count ?? 0, published_at: new Date().toISOString(), content: d.report })
      } else {
        setMsg(d?.error || '生成失败')
      }
    } catch (e: any) {
      setMsg(`生成失败: ${e.message}`)
    }
    setBusy(false)
  }

  const investigateIssue = () => sel && generateReport({ issue_id: sel })
  const investigateTopic = () => {
    const t = topicInput.trim()
    if (!t) { setMsg('请输入调查主题'); return }
    generateReport({ topic: t })
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

      {/* 源准入收件箱（自主补源的建议落这里） */}
      {intake.length > 0 && (
        <div style={{ ...S.sec, borderLeft: '3px solid var(--yellow)' }}>
          <b style={{ fontSize: 10, color: 'var(--yellow)', letterSpacing: '0.05em' }}>
            信源准入 {intake.length} 待审
          </b>
          {intake.map(f => (
            <div key={f.id} style={{ marginTop: 8, padding: 8, borderRadius: 4, background: '#0d1330' }}>
              <div style={{ display: 'flex', gap: 6, fontSize: 10, marginBottom: 4 }}>
                <span style={{ color: 'var(--yellow)' }}>T{f.proposal?.tier ?? '?'}</span>
                <span style={{ color: 'var(--fg-dim)', marginLeft: 'auto' }}>{f.created_at?.substring(5, 16)}</span>
              </div>
              <div style={{ fontSize: 12, fontWeight: 700 }}>{f.proposal?.name}</div>
              <div style={{ fontSize: 10, color: '#60a5fa', wordBreak: 'break-all' }}>{f.proposal?.url}</div>
              {f.proposal?.reason && <div style={{ fontSize: 11, color: 'var(--fg-dim)', marginTop: 2 }}>{f.proposal.reason}</div>}
              <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <button onClick={() => review(f.id, true)} disabled={busy} style={S.btn('#16a34a')}>批准入库</button>
                <button onClick={() => review(f.id, false)} disabled={busy} style={S.btn('#ef4444')}>驳回</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 时间链 */}
      {sel && current && (
        <div style={S.sec}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <b style={{ flex: 1 }}>时间链</b>
            <span style={{ fontSize: 10, color: 'var(--fg-dim)' }}>{nodes.length} 节点</span>
            <button onClick={investigateIssue} disabled={busy} style={S.btn('var(--purple)')}>生成调查报告</button>
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

      {/* 调查报告：自由主题入口 + 历史报告 */}
      <div style={{ ...S.sec, borderTop: '2px solid var(--purple)' }}>
        <b style={{ fontSize: 10, color: 'var(--purple)', letterSpacing: '0.05em' }}>调查报告</b>
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <input
            value={topicInput}
            onChange={e => setTopicInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !busy && investigateTopic()}
            placeholder="任意主题，如「霍尔木兹海峡航运」"
            style={{ flex: 1, background: '#0d1330', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--fg)', fontSize: 11, padding: '4px 8px', outline: 'none' }}
          />
          <button onClick={investigateTopic} disabled={busy} style={S.btn('var(--purple)')}>调查</button>
        </div>
        {reports.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {reports.map(r => (
              <div key={r.id} onClick={() => openReport(r.id)} style={{ cursor: 'pointer', display: 'flex', gap: 6, alignItems: 'center', padding: '5px 6px', marginTop: 3, borderRadius: 4, background: '#0d1330', borderLeft: '2px solid var(--purple)' }}>
                <span style={{ fontSize: 11, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.subject}</span>
                <span style={{ fontSize: 9, color: 'var(--fg-dim)' }} title={r.engine === 'embedded-tianshu' ? '嵌入式天枢' : r.engine}>{r.evidence_count}证</span>
                <span style={{ fontSize: 9, color: 'var(--fg-dim)' }}>{fmtTime(r.published_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

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

      {/* 调查报告查看器 */}
      {reportView && (
        <div
          onClick={() => setReportView(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, width: 640, maxWidth: '90vw', maxHeight: '82vh', display: 'flex', flexDirection: 'column' }}
          >
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <div style={{ flex: 1, fontSize: 13, fontWeight: 700, lineHeight: 1.4 }}>{reportView.subject ? `调查报告: ${reportView.subject}` : reportView.title}</div>
              <a href={`/api/investigate/reports/${reportView.id}/export?format=md`} style={{ ...S.btn('#1d4ed8'), textDecoration: 'none', display: 'inline-block' }}>md</a>
              <a href={`/api/investigate/reports/${reportView.id}/export?format=docx`} style={{ ...S.btn('#1d4ed8'), textDecoration: 'none', display: 'inline-block' }}>docx</a>
              <button onClick={() => setReportView(null)} style={{ background: 'none', border: 'none', color: 'var(--fg-dim)', cursor: 'pointer', fontSize: 16 }}>✕</button>
            </div>
            <div style={{ padding: '8px 16px 16px', overflow: 'auto', flex: 1, fontSize: 12, lineHeight: 1.7 }}>
              {(reportView.content || '').split('\n').map((line, i) => {
                const key = `l${i}`
                if (line.startsWith('## ')) return <div key={key} style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent)', margin: '14px 0 6px' }}>{line.slice(3)}</div>
                if (line.startsWith('# ')) return <div key={key} style={{ fontSize: 16, fontWeight: 700, margin: '6px 0' }}>{line.slice(2)}</div>
                if (line.startsWith('> ')) return <div key={key} style={{ color: 'var(--fg-dim)', fontSize: 10, borderLeft: '2px solid var(--purple)', paddingLeft: 8, margin: '4px 0' }}>{line.slice(2)}</div>
                if (/^\s*[-*]\s/.test(line)) return <div key={key} style={{ paddingLeft: 14, margin: '2px 0' }}>• {line.replace(/^\s*[-*]\s/, '')}</div>
                if (line.trim() === '---') return <hr key={key} style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '10px 0' }} />
                if (!line.trim()) return <div key={key} style={{ height: 6 }} />
                return <div key={key}>{line}</div>
              })}
            </div>
          </div>
        </div>
      )}

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
