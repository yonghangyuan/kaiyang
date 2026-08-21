import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

interface GeoPoint { id: string; title: string; lat: number; lng: number; country_code?: string; severity?: number; confidence?: number; source_count?: number; time_start?: string; published_at?: string; type?: string; url?: string; relation?: string; seq?: number; prev_id?: string | null; issue_id?: string; issue_title?: string }
interface Annotation { id: string; name: string; description?: string; type: string; coordinates: any; style?: any }

interface ChainData { nodes: {id:string; lat:number; lng:number; relation:string; title:string; severity:number}[]; edges: {from:string; to:string; from_relation:string; to_relation:string}[] }
interface TopicLayer { issue_id: string; name: string; category?: string; events?: number; mappable_events?: number }
interface Props { events: GeoPoint[]; searchResults: GeoPoint[]; annotations: Annotation[]; chain?: ChainData | null; flyTo?: {lat:number;lng:number} | null; topicLayers?: TopicLayer[]; activeTopics?: string[]; onToggleTopic?: (issueId: string) => void }

export default function MapView({ events, searchResults, annotations, chain, flyTo, topicLayers = [], activeTopics = [], onToggleTopic }: Props) {
  const mapRef = useRef<L.Map | null>(null)
  const groupsRef = useRef<Record<string, L.LayerGroup>>({})

  // Separate events by type
  const earthquakeEvents = events.filter(e => e.title?.toLowerCase().includes('earthquake') || e.title?.toLowerCase().includes('magnitude'))
  const otherEvents = events.filter(e => !earthquakeEvents.includes(e))

  useEffect(() => {
    if (mapRef.current) return
    const map = L.map('map-container').setView([35, 105], 4)

    const baseTiles: Record<string, L.TileLayer> = {
      '高德地图': L.tileLayer('https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}', { subdomains: '1234', maxZoom: 18 }),
      '卫星影像': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 17 }),
      // 注: CartoDB/OSM 的国界渲染不符合中国地图出版标准（台湾/藏南/阿克赛钦），
      // 已从底图选项移除 (2026-08-21)。国内场景用高德，全球影像用 ESRI 卫星图（无边界标注）。
    }
    baseTiles['高德地图'].addTo(map)

    // Create data layer groups
    const overlays: Record<string, L.LayerGroup> = {
      '实时事件': L.layerGroup(),
      '地震': L.layerGroup(),
      'Chains': L.layerGroup(),
      '设施库': L.layerGroup(),
      'Annotations': L.layerGroup(),
      'Search Results': L.layerGroup(),
    }
    Object.entries(overlays).forEach(([, g]) => g.addTo(map))
    groupsRef.current = overlays

    L.control.layers(baseTiles, overlays as any, { position: 'bottomright', collapsed: true }).addTo(map)
    mapRef.current = map
  }, [])

  // Update data layers
  useEffect(() => {
    const g = groupsRef.current
    if (!g) return
    const esc = (s: string) => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')

    // Popup helper — uses global functions to avoid inline JS complexity
    const fmtLocal = (iso?: string) => {
      if (!iso) return ''
      const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z')
      if (isNaN(d.getTime())) return iso.substring(0,16)
      return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
    }
    const COUNTRY_LABEL: Record<string, string> = { TW: '中国台湾', HK: '中国香港', MO: '中国澳门' }
    const makePopup = (e: GeoPoint, extra: string) => {
      const sev = e.severity || 1
      let html = `<div style="max-width:300px"><b>${esc(e.title||'')}</b>`
      html += `<br><small style="color:#64748b">${COUNTRY_LABEL[e.country_code||''] || e.country_code || '?'} | ${fmtLocal(e.time_start || e.published_at)} | imp:${sev}/10`
      if (e.source_count) html += ` | ${e.source_count}sources`
      html += `</small>${extra}`
      html += `<br><a href="#" onclick="event.preventDefault();window.loadEventItems('${e.id}')" style="font-size:11px">查看报道</a>`
      html += ` | <a href="#" onclick="event.preventDefault();window.tianshuPopup('${encodeURIComponent((e.title||'').substring(0,80))}')" style="font-size:11px">Tianshu</a>`
      html += `<div id="evt-items-${e.id}" style="margin-top:4px"></div></div>`
      return html
    }

    // Events layer
    g['实时事件'].clearLayers()
    otherEvents.forEach(e => {
      if (!e.lat || !e.lng) return
      const sev = e.severity || 1
      const c = sev >= 7 ? '#ef4444' : sev >= 5 ? '#f97316' : sev >= 3 ? '#eab308' : '#22c55e'
      const r = Math.min(6 + sev * 1.5, 20)
      const m = L.circleMarker([e.lat, e.lng], { radius: r, fillColor: c, color: '#fff', weight: 1, fillOpacity: 0.85 })
        .bindPopup(makePopup(e, ''))
        .addTo(g['实时事件'])
      if (sev >= 7) (m as any)._path?.classList?.add('severity-critical')
      else if (sev >= 5) (m as any)._path?.classList?.add('severity-high')
    })

    // Earthquakes layer
    g['地震'].clearLayers()
    earthquakeEvents.forEach(e => {
      if (!e.lat || !e.lng) return
      const mag = parseFloat((e.title||'').match(/M(\d+\.?\d*)/)?.[1] || '0')
      const r = Math.max(6, mag * 3)
      const c = mag >= 7 ? '#7f1d1d' : mag >= 6 ? '#dc2626' : mag >= 5 ? '#f97316' : '#eab308'
      L.circleMarker([e.lat, e.lng], { radius: r, fillColor: c, color: '#fff', weight: 2, fillOpacity: 0.7 })
        .bindPopup(makePopup(e, `<br><small style="color:${c}">M${mag.toFixed(1)}</small>`))
        .addTo(g['地震'])
    })

    // Search layer
    g['Search Results'].clearLayers()
    searchResults.forEach(e => {
      if (!e.lat || !e.lng) return
      let extra = ''
      if (e.url) extra += `<br><a href="${esc(e.url)}" target="_blank" style="font-size:11px;color:#60a5fa">source ↗</a>`
      if (e.published_at) extra += ` | ${e.published_at.substring(0,16)}`
      L.circleMarker([e.lat, e.lng], { radius: 7, fillColor: '#3b82f6', color: '#fff', weight: 1, fillOpacity: 0.7 })
        .bindPopup(`<div style="max-width:280px"><b>${esc(e.title||'')}</b><br><small style="color:#64748b">${e.country_code||''}${extra}</small></div>`)
        .addTo(g['Search Results'])
    })

    // Annotations layer
    g['Annotations'].clearLayers()
    annotations.forEach(a => {
      const coords = a.coordinates
      if (a.type === 'polyline' && Array.isArray(coords) && coords.length >= 2 && Array.isArray(coords[0])) {
        L.polyline(coords as [number,number][], { color: (a.style as any)?.color || '#ef4444', weight: 3, opacity: 0.8 })
          .bindPopup(`<b>${esc(a.name)}</b><br><small>${esc(a.description||'')}</small>`).addTo(g['Annotations'])
      } else if (a.type === 'point' && Array.isArray(coords) && coords.length >= 2) {
        L.circleMarker([coords[0] as number, coords[1] as number], { radius: 8, fillColor: '#a855f7', color: '#fff', weight: 2, fillOpacity: 0.9 })
          .bindPopup(`<b>${esc(a.name)}</b><br><small>${esc(a.description||'')}</small>`).addTo(g['Annotations'])
      }
    })
    // Chain layer
    g['Chains'].clearLayers()
    if (chain) {
      const relColors: Record<string,string> = { cause:'#3b82f6', trigger:'#f97316', core:'#ef4444', consequence:'#eab308', response:'#22c55e' }
      const nodeMap: Record<string, any> = {}
      chain.nodes.forEach((n, i) => {
        nodeMap[n.id] = n
        const c = relColors[n.relation] || '#64748b'
        L.circleMarker([n.lat, n.lng], { radius: 10, fillColor: c, color: '#fff', weight: 2, fillOpacity: 0.9 })
          .bindPopup(`<b>${n.relation}</b>: ${esc(n.title||'')}`).addTo(g['Chains'])
        L.divIcon({ html: `<div style="background:${c};color:#fff;border-radius:50%;width:20px;height:20px;text-align:center;line-height:20px;font-size:11px;font-weight:700">${i+1}</div>`, className: '', iconSize: [20,20] })
      })
      chain.edges.forEach(e => {
        const a = nodeMap[e.from], b = nodeMap[e.to]
        if (a && b) {
          L.polyline([[a.lat,a.lng],[b.lat,b.lng]], { color: '#eab308', weight: 2, dashArray: '6,4', opacity: 0.7 })
            .bindPopup(`${e.from_relation} → ${e.to_relation}`).addTo(g['Chains'])
        }
      })
    }

    // Facilities layer (loaded once)
    if (!g['设施库'].getLayers().length) {
      fetch('/api/facilities?limit=200').then(r => r.json()).then(d => {
        d.facilities.forEach((f: any) => {
          if (!f.lat || !f.lng) return
          const c = f.threat >= 5 ? '#ff4444' : f.threat >= 4 ? '#ff9944' : f.threat >= 3 ? '#ffcc00' : '#3b82f6'
          const icons: Record<string,string> = { military_base:'🔴', nuclear:'☢️', port:'⚓', airport:'✈️', spaceport:'🚀', chokepoint:'⚠️' }
          L.circleMarker([f.lat, f.lng], { radius: 6, fillColor: c, color: '#fff', weight: 1, fillOpacity: 0.9 })
            .bindPopup(`<b>${icons[f.type]||'📍'} ${f.name}</b><br><small>${f.type} | ${f.country} | threat:${f.threat}/5<br>${f.description||''}</small>`)
            .addTo(g['设施库'])
        })
      })
    }

    // FlyTo
    if (flyTo) mapRef.current?.flyTo([flyTo.lat, flyTo.lng], 6, { duration: 1.5 })
  }, [events, searchResults, annotations, otherEvents, earthquakeEvents, chain, flyTo])

  // ── 专题图层（Issue 批次）：勾选显示、取消隐藏 ──
  const loadedTopicsRef = useRef<Record<string, GeoPoint[]>>({})
  useEffect(() => {
    const g = groupsRef.current
    if (!g) return
    const map = mapRef.current
    if (!map) return
    const esc = (s: string) => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    const relColors: Record<string,string> = { cause:'#3b82f6', trigger:'#f97316', core:'#ef4444', consequence:'#eab308', response:'#22c55e' }

    // 移除已取消勾选的专题组
    Object.keys(g).forEach(key => {
      if (key.startsWith('topic:') && !activeTopics.includes(key.slice(6))) {
        map.removeLayer(g[key])
        delete g[key]
      }
    })

    activeTopics.forEach(tid => {
      const layerKey = `topic:${tid}`
      // 已加载则跳过（数据不变）
      if (g[layerKey]) return

      const layer = L.layerGroup()
      fetch(`/api/map/issue-points?issue_id=${tid}`).then(r => r.json()).then(d => {
        const pts: GeoPoint[] = d.points || []
        loadedTopicsRef.current[tid] = pts
        const byId: Record<string, GeoPoint> = {}
        pts.forEach(p => { byId[p.id] = p })
        // 连线（事件链顺序）
        pts.forEach(p => {
          if (p.prev_id && byId[p.prev_id] && p.lat && p.lng && byId[p.prev_id].lat) {
            L.polyline([[byId[p.prev_id].lat!, byId[p.prev_id].lng!],[p.lat!, p.lng!]],
              { color: relColors[p.relation||''] || '#94a3b8', weight: 2, dashArray: '4,4', opacity: 0.7 })
              .bindTooltip(`${p.relation||''}: ${p.title||''}`)
              .addTo(layer)
          }
        })
        // 节点
        pts.forEach(p => {
          if (!p.lat || !p.lng) return
          const c = relColors[p.relation||''] || '#a855f7'
          L.circleMarker([p.lat, p.lng], { radius: 8, fillColor: c, color: '#fff', weight: 2, fillOpacity: 0.9 })
            .bindPopup(`<div style="max-width:280px"><b>${esc(p.title||'')}</b><br><small style="color:#64748b">${esc(p.issue_title||'')} | ${p.relation||''} | ${p.time_start?.substring(0,10)||''} | conf:${p.confidence}</small></div>`)
            .addTo(layer)
        })
        layer.addTo(map)
        g[layerKey] = layer
      })
    })
  }, [activeTopics])

  return (
    <>
      <div id="map-container" style={{ width: '100%', height: '100%', position: 'relative' }} />
      {/* 专题图层管理面板 */}
      <div style={{
        position: 'absolute', top: 10, right: 10, zIndex: 1000,
        background: 'rgba(15,23,42,0.92)', borderRadius: 8, padding: '10px 12px',
        color: '#e2e8f0', fontSize: 12, minWidth: 180, border: '1px solid #334155',
      }}>
        <div style={{ fontWeight: 700, marginBottom: 6, color: '#e2c860' }}>专题图层</div>
        {topicLayers.length === 0 && <div style={{ color: '#64748b' }}>（无议题）</div>}
        {topicLayers.map(t => (
          <label key={t.issue_id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={activeTopics.includes(t.issue_id)}
              style={{ accentColor: '#e2c860' }}
              onChange={() => onToggleTopic?.(t.issue_id)}
            />
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {t.name}
            </span>
            <span style={{ color: '#64748b' }}>{t.mappable_events ?? 0}点</span>
          </label>
        ))}
      </div>
    </>
  )
}
