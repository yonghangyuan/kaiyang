import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

interface GeoPoint { id: string; title: string; lat: number; lng: number; country_code?: string; severity?: number }
interface Annotation { id: string; name: string; description?: string; type: string; coordinates: any; style?: any }

interface Props {
  events: GeoPoint[]; searchResults: GeoPoint[]; annotations: Annotation[]
}

export default function MapView({ events, searchResults, annotations }: Props) {
  const mapRef = useRef<L.Map | null>(null)

  useEffect(() => {
    if (mapRef.current) return
    const map = L.map('map-container').setView([35, 105], 4)
    const tiles: Record<string, L.TileLayer> = {
      'CartoDB': L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', { subdomains: 'abcd', maxZoom: 19 }),
      'Amap': L.tileLayer('https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}', { subdomains: '1234', maxZoom: 18 }),
      'ESRI': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 17 }),
      'OSM': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { subdomains: 'abc', maxZoom: 19 }),
    }
    tiles['CartoDB'].addTo(map)
    L.control.layers(tiles, undefined, { position: 'bottomright' }).addTo(map)
    mapRef.current = map
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    // Clear previous markers (simple approach: we re-render via key, but for now just add)
    events.forEach(e => {
      if (!e.lat || !e.lng) return
      const c = (e.severity||1) >= 7 ? '#ef4444' : (e.severity||1) >= 5 ? '#f97316' : (e.severity||1) >= 3 ? '#eab308' : '#22c55e'
      L.circleMarker([e.lat, e.lng], { radius: 8, fillColor: c, color: '#fff', weight: 1, fillOpacity: 0.8 })
        .bindPopup('<b>'+(e.title||'')+'</b><br>'+(e.country_code||'')).addTo(map)
    })
    searchResults.forEach(e => {
      if (!e.lat || !e.lng) return
      L.circleMarker([e.lat, e.lng], { radius: 7, fillColor: '#3b82f6', color: '#fff', weight: 1, fillOpacity: 0.7 })
        .bindPopup('<b>'+(e.title||'')+'</b>').addTo(map)
    })
    annotations.forEach(a => {
      const coords = a.coordinates
      if (a.type === 'polyline' && Array.isArray(coords) && coords.length>=2 && Array.isArray(coords[0])) {
        L.polyline(coords as [number,number][], { color: '#ef4444', weight: 3, opacity: 0.8 })
          .bindPopup('<b>'+(a.name||'')+'</b>').addTo(map)
      } else if (a.type === 'point' && Array.isArray(coords) && coords.length>=2) {
        L.marker([coords[0] as number, coords[1] as number]).bindPopup('<b>'+(a.name||'')+'</b>').addTo(map)
      }
    })
  }, [events, searchResults, annotations])

  return <div id="map-container" style={{ width: '100%', height: '100%' }} />
}
