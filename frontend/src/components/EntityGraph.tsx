import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'

interface GraphNode { id: string; name: string; type: string; group: number }
interface GraphLink { source: string; target: string; type?: string }

interface Props { entityId: string; onClose: () => void }

export default function EntityGraph({ entityId, onClose }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [data, setData] = useState<{nodes:GraphNode[]; links:GraphLink[]} | null>(null)
  const [entity, setEntity] = useState<{id:string;name:string;type:string} | null>(null)

  useEffect(() => {
    fetch(`/api/entities/${entityId}/graph`).then(r => r.json()).then(d => {
      setData(d)
      setEntity(d.entity)
    })
  }, [entityId])

  useEffect(() => {
    if (!data || !svgRef.current) return
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const width = 360, height = 320
    svg.attr('viewBox', `0 0 ${width} ${height}`)

    const color = d3.scaleOrdinal(['#3b82f6','#eab308','#ef4444','#22c55e','#a855f7'])

    const simulation = d3.forceSimulation(data.nodes as any)
      .force('link', d3.forceLink(data.links).id((d: any) => d.id).distance(60))
      .force('charge', d3.forceManyBody().strength(-120))
      .force('center', d3.forceCenter(width/2, height/2))

    const link = svg.append('g')
      .selectAll('line').data(data.links).join('line')
      .attr('stroke', '#334155').attr('stroke-width', 1.5)

    const node = svg.append('g')
      .selectAll('circle').data(data.nodes).join('circle')
      .attr('r', d => d.id === entityId ? 10 : 6)
      .attr('fill', (d: any) => color(d.group))
      .attr('stroke', '#fff').attr('stroke-width', 1)
      .call(d3.drag<SVGCircleElement, any>()
        .on('start', (e,d) => { if(!e.active) simulation.alphaTarget(0.3).restart(); d.fx=d.x;d.fy=d.y })
        .on('drag', (e,d) => { d.fx=e.x;d.fy=e.y })
        .on('end', (e,d) => { if(!e.active) simulation.alphaTarget(0); d.fx=null;d.fy=null })
      )

    const label = svg.append('g')
      .selectAll('text').data(data.nodes).join('text')
      .text((d: any) => d.name.substring(0,12))
      .attr('font-size', 9).attr('fill', '#94a3b8')
      .attr('text-anchor', 'middle').attr('dy', -12)

    simulation.on('tick', () => {
      link.attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
          .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
      node.attr('cx', (d: any) => d.x).attr('cy', (d: any) => d.y)
      label.attr('x', (d: any) => d.x).attr('y', (d: any) => d.y)
    })

    return () => { simulation.stop() }
  }, [data, entityId])

  if (!data) return <div style={{padding:20,textAlign:'center',color:'var(--fg-dim)'}}>Loading graph...</div>

  return (
    <div style={{background:'var(--bg-card)',border:'1px solid var(--border)',borderRadius:6,padding:8,marginTop:8,position:'relative'}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:4}}>
        <span style={{fontSize:12,fontWeight:600}}>Entity Graph: {entity?.name}</span>
        <button onClick={onClose} style={{background:'none',border:'none',color:'var(--fg-dim)',cursor:'pointer',fontSize:14}}>×</button>
      </div>
      <svg ref={svgRef} style={{width:'100%',height:320,background:'var(--bg)'}} />
    </div>
  )
}
