import { useState } from 'react'

export default function BriefingCard() {
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const generate = (country = '') => {
    setLoading(true)
    fetch(`/api/narrative/briefing?country=${country}&days=1`).then(r => r.json()).then(d => {
      setResult(d); setLoading(false)
    }).catch(() => setLoading(false))
  }

  return (
    <div style={{background:'var(--bg-card)',border:'1px solid var(--border)',borderRadius:6,padding:10,marginTop:8}}>
      <div style={{fontSize:11,fontWeight:600,color:'var(--fg-dim)',marginBottom:6}}>AI 简报</div>
      <div style={{display:'flex',gap:4,marginBottom:8}}>
        <button onClick={() => generate('')} disabled={loading}
          style={{background:'var(--accent)',color:'#fff',border:'none',padding:'3px 10px',borderRadius:3,fontSize:10,cursor:'pointer'}}>
          {loading?'生成中...':'全球简报'}
        </button>
        {['CN','US','JP','IR','RU'].map(c => (
          <button key={c} onClick={() => generate(c)} disabled={loading}
            style={{background:'var(--bg)',border:'1px solid var(--border)',color:'var(--fg-dim)',padding:'3px 8px',borderRadius:3,fontSize:10,cursor:'pointer'}}>
            {c}
          </button>
        ))}
      </div>
      {result?.briefing && (
        <div style={{background:'var(--bg)',padding:8,borderRadius:4,borderLeft:'3px solid var(--accent)',fontSize:12,lineHeight:1.6}}>
          {result.briefing}
          {result.key_findings && <div style={{marginTop:6}}>{result.key_findings.map((k:string,i:number) => <div key={i} style={{fontSize:10,color:'var(--fg-dim)'}}>&bull; {k}</div>)}</div>}
          {result.risk_assessment && <div style={{marginTop:4,fontSize:10,color:result.risk_assessment==='high'?'var(--red)':'var(--fg-dim)'}}>风险评估: {result.risk_assessment}</div>}
        </div>
      )}
    </div>
  )
}
