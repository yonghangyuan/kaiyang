import { useEffect, useState } from 'react'
import EntityGraph from './EntityGraph'

interface EntityData {
  id: string; type: string; name: string; aliases: string[]
  country_code?: string; first_seen?: string; last_seen?: string
}

interface Props { entityId: string; onClose: () => void }

export default function EntityProfile({ entityId, onClose }: Props) {
  const [entity, setEntity] = useState<EntityData | null>(null)
  const [events, setEvents] = useState<any[]>([])
  const [relations, setRelations] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/entities/${entityId}/dossier`).then(r => r.json()).then(d => {
      setEntity(d.entity)
      setEvents(d.related_events || [])
      setRelations(d.relations)
      setLoading(false)
    })
  }, [entityId])

  if (loading) return <div style={{padding:20,textAlign:'center',color:'var(--fg-dim)'}}>Loading...</div>
  if (!entity) return <div style={{padding:20,textAlign:'center',color:'var(--red)'}}>Entity not found</div>

  const typeColors: Record<string, string> = { country: '#22c55e', institution: '#3b82f6', person: '#f97316', organization: '#a855f7' }

  return (
    <div style={{fontSize:12}}>
      <div style={{background:'var(--bg-card)',border:'1px solid var(--border)',borderRadius:6,padding:12,marginBottom:8}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'start',marginBottom:8}}>
          <div>
            <span style={{fontSize:10,fontWeight:700,color:typeColors[entity.type]||'#64748b',background:(typeColors[entity.type]||'#64748b')+'20',padding:'1px 6px',borderRadius:3,textTransform:'uppercase'}}>{entity.type}</span>
            <h3 style={{margin:'4px 0',fontSize:15,color:'var(--fg)'}}>{entity.name}</h3>
            {entity.aliases?.length > 0 && <div style={{color:'var(--fg-dim)',fontSize:10}}>AKA: {entity.aliases.join(', ')}</div>}
          </div>
          <button onClick={onClose} style={{background:'none',border:'none',color:'var(--fg-dim)',fontSize:16,cursor:'pointer'}}>×</button>
        </div>
        <div style={{display:'flex',gap:16,fontSize:10,color:'var(--fg-dim)'}}>
          {entity.country_code && <span>Country: {entity.country_code}</span>}
          {entity.first_seen && <span>First seen: {entity.first_seen?.substring(0,10)}</span>}
          {entity.last_seen && <span>Last seen: {entity.last_seen?.substring(0,10)}</span>}
        </div>
      </div>

      {relations && <div style={{color:'var(--fg-dim)',fontSize:10,marginBottom:4}}>Relations: {relations.relation_count} connections</div>}

      {events.length > 0 && (
        <div style={{marginBottom:8}}>
          <div style={{fontSize:11,fontWeight:600,color:'var(--fg-dim)',marginBottom:4}}>Related Events ({events.length})</div>
          {events.slice(0, 10).map((e: any) => (
            <div key={e.id} style={{padding:'4px 8px',borderLeft:'2px solid var(--border)',marginLeft:6,marginBottom:3,fontSize:11}}>
              <span style={{color:'var(--fg)'}}>{e.title?.substring(0,80)}</span>
              <span style={{color:'var(--fg-dim)',fontSize:9,marginLeft:6}}>{e.severity ? 'imp:'+e.severity+'/10' : ''}</span>
            </div>
          ))}
        </div>
      )}

      <EntityGraph entityId={entityId} onClose={() => {}} />
    </div>
  )
}
