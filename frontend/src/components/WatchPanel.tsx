import { useState, useEffect } from 'react'

interface Finding {
  id: string; type: string; status: string; content: string
  proposal?: any; created_by: string; created_at: string
}
interface WatchIssue {
  id: string; title: string; watch: number; watch_keywords?: string
  status: string; category?: string
}

const fetchJ = async (url: string, init?: RequestInit) => {
  try { const r = await fetch(url, init); return await r.json() } catch { return null }
}

const stLabel: Record<string, string> = { auto: '已入库', pending: '待审', approved: '已执行', rejected: '已驳回' }
const stColor: Record<string, string> = { auto: 'var(--green)', pending: 'var(--yellow)', approved: 'var(--accent)', rejected: '#ef4444' }

export default function WatchPanel() {
  const [issues, setIssues] = useState<WatchIssue[]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [poolN, setPoolN] = useState<number>(0)
  const [kwDraft, setKwDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const loadIssues = async () => {
    const d = await fetchJ('/api/issues?limit=50')
    setIssues((d?.issues || []).map((i: any) => ({ ...i, watch: i.watch || 0, watch_keywords: i.watch_keywords || '' })))
  }
  useEffect(() => { loadIssues() }, [])

  const loadDetail = async (id: string) => {
    const [fd, pool] = await Promise.all([
      fetchJ(`/api/issues/${id}/findings`),
      fetchJ(`/api/issues/${id}/pool?limit=100`),
    ])
    setFindings(fd?.findings || [])
    setPoolN(pool?.count || 0)
  }
  useEffect(() => { if (sel) loadDetail(sel) }, [sel])

  const watching = issues.filter(i => i.watch)
  const current = issues.find(i => i.id === sel)
  const pendingCount = findings.filter(f => f.status === 'pending').length

  const toggleWatch = async (issue: WatchIssue, on: boolean) => {
    const keywords = on ? (kwDraft || issue.watch_keywords || '') : (issue.watch_keywords || '')
    if (on && !keywords.trim()) { setMsg('请先填订阅关键词'); return }
    setBusy(true)
    await fetchJ(`/api/issues/${issue.id}/watch`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on, keywords }),
    })
    await loadIssues(); setBusy(false); setMsg(on ? '追踪已开启' : '追踪已关闭')
    if (on && sel === issue.id) loadDetail(issue.id)
  }

  const review = async (fid: string, approve: boolean) => {
    setBusy(true)
    await fetchJ(`/api/findings/${fid}/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve, note: '' }),
    })
    if (sel) loadDetail(sel); setBusy(false)
  }

  const analyzeNow = async () => {
    if (!sel) return
    setBusy(true); setMsg('分析中...')
    const d = await fetchJ(`/api/issues/${sel}/analyze`, { method: 'POST' })
    setMsg(d?.error ? `失败: ${d.error}` : `完成: 新增${d?.notes || 0}笔记 ${d?.chains || 0}建议${d?.fallback ? ' (规则兜底)' : ''}`)
    if (sel) loadDetail(sel); setBusy(false)
  }

  const S: any = {
    sec: { background: 'var(--bg-card)', padding: 10, borderRadius: 6, marginBottom: 8, border: '1px solid var(--border)', fontSize: 12 },
    btn: (bg: string): any => ({ background: bg, color: '#fff', border: 'none', padding: '4px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer' }),
  }

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

      {/* 选中专题详情 */}
      {current && (
        <div style={S.sec}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <b style={{ flex: 1 }}>{current.title}</b>
            <span style={{ fontSize: 10, color: 'var(--fg-dim)' }}>池 {poolN} 条</span>
            <button onClick={analyzeNow} disabled={busy} style={S.btn('var(--accent)')}>立即分析</button>
          </div>
          {current.watch_keywords && (
            <div style={{ fontSize: 10, color: 'var(--fg-dim)', marginTop: 4 }}>订阅: {current.watch_keywords}</div>
          )}
          {pendingCount > 0 && (
            <div style={{ color: 'var(--yellow)', fontSize: 11, marginTop: 4 }}>⚠ {pendingCount} 条结构性建议待审</div>
          )}
        </div>
      )}

      {/* 发现流（note 自动 + chain 待审） */}
      {sel && findings.length > 0 && (
        <div style={S.sec}>
          <b style={{ fontSize: 10, color: 'var(--fg-dim)' }}>调研发现 {findings.length}</b>
          {findings.map(f => (
            <div key={f.id} style={{ marginTop: 8, padding: 8, borderRadius: 4, background: '#0d1330', borderLeft: `3px solid ${stColor[f.status]}` }}>
              <div style={{ display: 'flex', gap: 6, fontSize: 10, marginBottom: 4 }}>
                <span style={{ color: stColor[f.status] }}>{stLabel[f.status]}</span>
                <span style={{ color: 'var(--fg-dim)' }}>{f.type === 'chain' ? '结构性' : '笔记'}</span>
                <span style={{ color: 'var(--fg-dim)', marginLeft: 'auto' }}>{f.created_at?.substring(5, 16)}</span>
              </div>
              <div style={{ lineHeight: 1.5 }}>{f.content}</div>
              {f.proposal && (
                <div style={{ fontSize: 11, color: 'var(--fg-dim)', marginTop: 4 }}>
                  建议: {f.proposal.action === 'create_event' ? '新建事件' : f.proposal.action} → {f.proposal.title} [{f.proposal.relation}]
                </div>
              )}
              {f.status === 'pending' && (
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  <button onClick={() => review(f.id, true)} disabled={busy} style={S.btn('#16a34a')}>批准执行</button>
                  <button onClick={() => review(f.id, false)} disabled={busy} style={S.btn('#ef4444')}>驳回</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 全部 Issue 列表（开启追踪入口） */}
      <div style={S.sec}>
        <b style={{ fontSize: 10, color: 'var(--fg-dim)' }}>全部议题</b>
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <input value={kwDraft} onChange={e => setKwDraft(e.target.value)} placeholder="订阅关键词,逗号分隔"
            style={{ flex: 1, background: '#0d1330', border: '1px solid var(--border)', color: 'var(--fg)', padding: '4px 8px', borderRadius: 4, fontSize: 11 }} />
        </div>
        {issues.map(i => (
          <div key={i.id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 11 }}>
            <a onClick={() => setSel(i.id)} style={{ flex: 1, cursor: 'pointer', color: sel === i.id ? 'var(--accent)' : 'var(--fg)' }}>{i.title}</a>
            {i.watch
              ? <span style={{ color: 'var(--green)', fontSize: 10 }}>●追踪</span>
              : <button onClick={() => toggleWatch(i, true)} disabled={busy || !kwDraft.trim()} style={{ ...S.btn('#1d4ed8'), fontSize: 10 }}>追踪</button>}
          </div>
        ))}
      </div>

      {msg && <div style={{ fontSize: 11, color: 'var(--fg-dim)', textAlign: 'center' }}>{msg}</div>}
    </div>
  )
}
