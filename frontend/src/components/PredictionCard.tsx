import { useState } from 'react'

export default function PredictionCard() {
  const [keyword, setKeyword] = useState('')
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const predict = () => {
    if (!keyword.trim()) return
    setLoading(true)
    fetch('/api/trends/predict', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keyword: keyword.trim() }),
    }).then(r => r.json()).then(d => {
      setResult(d); setLoading(false)
    }).catch(() => setLoading(false))
  }

  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: 10, marginTop: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--fg-dim)', marginBottom: 6 }}>
        AI Prediction
      </div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
        <input value={keyword} onChange={e => setKeyword(e.target.value)}
          onKeyPress={e => e.key === 'Enter' && predict()}
          placeholder="Keyword or country..."
          style={{ flex: 1, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--fg)', padding: '4px 8px', borderRadius: 3, fontSize: 11 }} />
        <button onClick={predict} disabled={loading}
          style={{ background: 'var(--accent)', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: 3, fontSize: 11, cursor: 'pointer' }}>
          {loading ? '...' : 'Predict'}
        </button>
      </div>
      {result && (
        <div>
          <div style={{ fontSize: 10, color: 'var(--fg-dim)', marginBottom: 4 }}>
            {result.total_mentions} mentions in 14 days
          </div>
          {result.prediction && (
            <div style={{ background: 'var(--bg)', padding: 8, borderRadius: 4, borderLeft: '3px solid var(--accent)' }}>
              <div style={{ fontSize: 12, color: 'var(--fg)', lineHeight: 1.5 }}>{result.prediction.forecast}</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 4, fontSize: 10, color: 'var(--fg-dim)' }}>
                <span>Confidence: {Math.round((result.prediction.confidence || 0) * 100)}%</span>
                {result.prediction.reasoning && <span>| {result.prediction.reasoning}</span>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
