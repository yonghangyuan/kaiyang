import { useEffect, useState, useRef } from 'react'
import * as d3 from 'd3'

interface TrendData { date: string; count: number; spike?: boolean }

export default function TrendChart() {
  const svgRef = useRef<SVGSVGElement>(null)
  const [data, setData] = useState<TrendData[]>([])
  const [keyword, setKeyword] = useState('Iran')
  const [days, setDays] = useState(14)

  const fetchTrend = (kw: string, d: number) => {
    fetch(`/api/trends?keyword=${encodeURIComponent(kw)}&days=${d}`)
      .then(r => r.json()).then(d => setData(d.data || []))
  }

  useEffect(() => { fetchTrend(keyword, days) }, [keyword, days])

  useEffect(() => {
    if (!data.length || !svgRef.current) return
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    const W = 340, H = 140, M = { top: 10, right: 10, bottom: 20, left: 35 }
    const w = W - M.left - M.right, h = H - M.top - M.bottom

    const x = d3.scaleTime().domain(d3.extent(data, d => new Date(d.date)) as [Date,Date]).range([0, w])
    const y = d3.scaleLinear().domain([0, d3.max(data, d => d.count) || 10]).range([h, 0])

    const g = svg.attr('viewBox', `0 0 ${W} ${H}`).append('g').attr('transform', `translate(${M.left},${M.top})`)

    // 网格线
    g.append('g').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x).ticks(5) as any)
    g.selectAll('.tick text').attr('fill', '#475569').attr('font-size', 8)
    g.selectAll('.domain,.tick line').attr('stroke', '#262d38')

    // 柱状图
    g.selectAll('rect').data(data).join('rect')
      .attr('x', d => x(new Date(d.date)) - w / data.length / 2)
      .attr('y', d => y(d.count))
      .attr('width', w / data.length - 2)
      .attr('height', d => h - y(d.count))
      .attr('fill', d => d.spike ? '#ef4444' : '#3b82f6')
      .attr('rx', 2)
      .attr('opacity', 0.8)

    // 数值标签 (只标 spike)
    g.selectAll('.label').data(data.filter(d => d.spike)).join('text')
      .attr('x', d => x(new Date(d.date)))
      .attr('y', d => y(d.count) - 4)
      .attr('text-anchor', 'middle')
      .attr('fill', '#ef4444')
      .attr('font-size', 9)
      .text(d => d.count)

  }, [data])

  return (
    <div style={{background:'var(--bg-card)',border:'1px solid var(--border)',borderRadius:6,padding:10,marginTop:8}}>
      <div style={{display:'flex',gap:6,alignItems:'center',marginBottom:6}}>
        <span style={{fontSize:11,fontWeight:600,color:'var(--fg-dim)'}}>Trend</span>
        <input value={keyword} onChange={e => setKeyword(e.target.value)}
          style={{width:80,background:'var(--bg)',border:'1px solid var(--border)',color:'var(--fg)',padding:'2px 6px',borderRadius:3,fontSize:11}} />
        <select value={days} onChange={e => setDays(Number(e.target.value))}
          style={{background:'var(--bg)',border:'1px solid var(--border)',color:'var(--fg-dim)',padding:'2px 4px',borderRadius:3,fontSize:10}}>
          {[7,14,30].map(d => <option key={d} value={d}>{d}d</option>)}
        </select>
      </div>
      <svg ref={svgRef} style={{width:'100%',height:150}} />
    </div>
  )
}
