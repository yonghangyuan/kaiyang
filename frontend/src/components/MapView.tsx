import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

interface GeoPoint { id: string; title: string; lat: number; lng: number; country_code?: string; severity?: number; confidence?: number; source_count?: number; time_start?: string; published_at?: string; type?: string; url?: string }
interface Annotation { id: string; name: string; description?: string; type: string; coordinates: any; style?: any }

interface ChainData { nodes: {id:string; lat:number; lng:number; relation:string; title:string; severity:number}[]; edges: {from:string; to:string; from_relation:string; to_relation:string}[] }
interface Props { events: GeoPoint[]; searchResults: GeoPoint[]; annotations: Annotation[]; chain?: ChainData | null; flyTo?: {lat:number;lng:number} | null }

export default function MapView({ events, searchResults, annotations, chain, flyTo }: Props) {
  const mapRef = useRef<L.Map | null>(null)
  const groupsRef = useRef<Record<string, L.LayerGroup>>({})

  // Separate events by type
  const earthquakeEvents = events.filter(e => e.title?.toLowerCase().includes('earthquake') || e.title?.toLowerCase().includes('magnitude'))
  const otherEvents = events.filter(e => !earthquakeEvents.includes(e))

  useEffect(() => {
    if (mapRef.current) return
    const map = L.map('map-container').setView([35, 105], 4)

    const baseTiles: Record<string, L.TileLayer> = {
      'CartoDB': L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', { subdomains: 'abcd', maxZoom: 19 }),
      'Amap': L.tileLayer('https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}', { subdomains: '1234', maxZoom: 18 }),
      'ESRI': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 17 }),
      'OSM': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { subdomains: 'abc', maxZoom: 19 }),
    }
    baseTiles['CartoDB'].addTo(map)

    // Create data layer groups
    const overlays: Record<string, L.LayerGroup> = {
      'Chains': L.layerGroup(),
      'Events': L.layerGroup(),
      'Earthquakes': L.layerGroup(),
      'Social': L.layerGroup(),
	      'Search Results': L.layerGroup(),
      'Annotations': L.layerGroup(),
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
    const makePopup = (e: GeoPoint, extra: string) => {
      const sev = e.severity || 1
      const time = e.time_start || e.published_at || ''
      let html = `<div style="max-width:300px"><b>${esc(e.title||'')}</b>`
      html += `<br><small style="color:#64748b">${e.country_code||'?'} | ${time.substring(0,16)} | imp:${sev}/10`
      if (e.source_count) html += ` | ${e.source_count}sources`
      html += `</small>${extra}`
      html += `<br><a href="#" onclick="event.preventDefault();window.loadEventItems('${e.id}')" style="font-size:11px">查看报道</a>`
      html += ` | <a href="#" onclick="event.preventDefault();window.tianshuPopup('${encodeURIComponent((e.title||'').substring(0,80))}')" style="font-size:11px">Tianshu</a>`
      html += `<div id="evt-items-${e.id}" style="margin-top:4px"></div></div>`
      return html
    }

    // Events layer
    g['Events'].clearLayers()
    otherEvents.forEach(e => {
      if (!e.lat || !e.lng) return
      const sev = e.severity || 1
      const c = sev >= 7 ? '#ef4444' : sev >= 5 ? '#f97316' : sev >= 3 ? '#eab308' : '#22c55e'
      const r = Math.min(6 + sev * 1.5, 20)
      const m = L.circleMarker([e.lat, e.lng], { radius: r, fillColor: c, color: '#fff', weight: 1, fillOpacity: 0.85 })
        .bindPopup(makePopup(e, ''))
        .addTo(g['Events'])
      if (sev >= 7) (m as any)._path?.classList?.add('severity-critical')
      else if (sev >= 5) (m as any)._path?.classList?.add('severity-high')
    })

    // Earthquakes layer
    g['Earthquakes'].clearLayers()
    earthquakeEvents.forEach(e => {
      if (!e.lat || !e.lng) return
      const mag = parseFloat((e.title||'').match(/M(\d+\.?\d*)/)?.[1] || '0')
      const r = Math.max(6, mag * 3)
      const c = mag >= 7 ? '#7f1d1d' : mag >= 6 ? '#dc2626' : mag >= 5 ? '#f97316' : '#eab308'
      L.circleMarker([e.lat, e.lng], { radius: r, fillColor: c, color: '#fff', weight: 2, fillOpacity: 0.7 })
        .bindPopup(makePopup(e, `<br><small style="color:${c}">M${mag.toFixed(1)}</small>`))
        .addTo(g['Earthquakes'])
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

    // FlyTo
    if (flyTo) mapRef.current?.flyTo([flyTo.lat, flyTo.lng], 6, { duration: 1.5 })
  }, [events, searchResults, annotations, otherEvents, earthquakeEvents, chain, flyTo])

  return <div id="map-container" style={{ width: '100%', height: '100%' }} />
}
