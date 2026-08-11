import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

interface GeoPoint { id: string; title: string; lat: number; lng: number; country_code?: string; severity?: number; confidence?: number; source_count?: number; time_start?: string; published_at?: string; type?: string; url?: string }
interface Annotation { id: string; name: string; description?: string; type: string; coordinates: any; style?: any }

interface Props { events: GeoPoint[]; searchResults: GeoPoint[]; annotations: Annotation[] }

export default function MapView({ events, searchResults, annotations }: Props) {
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

    // Events layer
    g['Events'].clearLayers()
    otherEvents.forEach(e => {
      if (!e.lat || !e.lng) return
      const sev = e.severity || 1
      const c = sev >= 7 ? '#ef4444' : sev >= 5 ? '#f97316' : sev >= 3 ? '#eab308' : '#22c55e'
      const r = Math.min(6 + sev * 1.5, 20)
      const m = L.circleMarker([e.lat, e.lng], { radius: r, fillColor: c, color: '#fff', weight: 1, fillOpacity: 0.85 })
        .bindPopup(`<b>${esc(e.title||'')}</b><br><small>${e.country_code||''} | importance:${sev}/10 | ${e.source_count||0}sources</small>`)
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
        .bindPopup(`<b>${esc(e.title||'')}</b><br><small>${e.country_code||''} | M${mag.toFixed(1)}</small>`)
        .addTo(g['Earthquakes'])
    })

    // Search layer
    g['Search Results'].clearLayers()
    searchResults.forEach(e => {
      if (!e.lat || !e.lng) return
      L.circleMarker([e.lat, e.lng], { radius: 7, fillColor: '#3b82f6', color: '#fff', weight: 1, fillOpacity: 0.7 })
        .bindPopup(`<b>${esc(e.title||'')}</b><br><small>${e.country_code||''}</small>`)
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
  }, [events, searchResults, annotations, otherEvents, earthquakeEvents])

  return <div id="map-container" style={{ width: '100%', height: '100%' }} />
}
