import { useEffect, useState } from 'react'

interface Threat { country: string; threat_level: number; threat_label: string; threat_color: string; components: any }

export default function ThreatDashboard() {
  const [threats, setThreats] = useState<Threat[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/threat').then(r => r.json()).then(d => {
      setThreats(d.threats || []); setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  if (loading) return <div style={{fontSize:11,color:'var(--fg-dim)',padding:8}}>评估中...</div>

  const labels: Record<number, string> = {1:'正常',2:'关注',3:'警戒',4:'高危',5:'危急'}

  return (
    <div style={{background:'var(--bg-card)',border:'1px solid var(--border)',borderRadius:6,padding:10,marginTop:8}}>
      <div style={{fontSize:11,fontWeight:600,color:'var(--fg-dim)',marginBottom:8}}>威胁评估 THREATCON</div>
      <div style={{display:'flex',flexDirection:'column',gap:4}}>
        {threats.slice(0, 12).map(t => (
          <div key={t.country} style={{display:'flex',alignItems:'center',gap:8,padding:'4px 6px',borderRadius:3,background:t.threat_level>=4?'rgba(239,68,68,0.05)':'transparent'}}>
            <span style={{fontSize:10,fontWeight:700,fontFamily:'monospace',color:'var(--fg-dim)',width:24}}>{t.country}</span>
            <div style={{flex:1,height:4,background:'var(--bg)',borderRadius:2,overflow:'hidden'}}>
              <div style={{width:(t.threat_level/5*100)+'%',height:'100%',background:t.threat_color,borderRadius:2,transition:'width 0.5s'}} />
            </div>
            <span style={{fontSize:10,fontWeight:700,color:t.threat_color,width:28,textAlign:'right',fontFamily:'monospace'}}>{labels[t.threat_level]}</span>
            <span style={{fontSize:10,fontWeight:900,color:t.threat_color}}>TC-{t.threat_level}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
