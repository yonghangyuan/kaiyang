import { useEffect, useRef } from 'react'

interface GeoPoint { id: string; title: string; lat: number; lng: number; severity?: number; country_code?: string }
interface Props { events: GeoPoint[] }

const globeState = { instance: null as any, ready: false }

export default function GlobeView({ events }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (globeState.ready || !containerRef.current) return
    // Load globe.gl from CDN (simpler than npm chunk loading)
    const script = document.createElement('script')
    script.src = 'https://unpkg.com/globe.gl@2'
    script.onload = () => {
      const G = (window as any).Globe
      if (!G || !containerRef.current) return
      const globe = G()(containerRef.current)
        .globeImageUrl('//unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
        .backgroundColor('#0f131a')
        .atmosphereColor('#3b82f6')
        .atmosphereAltitude(0.15)
        .pointLat('lat').pointLng('lng').pointColor('color').pointRadius('size').pointLabel('label')
        .pointsData([])
      globeState.instance = globe
      globeState.ready = true
      // Render current events
      updatePoints(events)
    }
    document.head.appendChild(script)
  }, [])

  const updatePoints = (pts: GeoPoint[]) => {
    const g = globeState.instance
    if (!g) return
    const points = pts
      .filter(e => e.lat && e.lng)
      .map(e => ({
        lat: e.lat, lng: e.lng,
        size: Math.min((e.severity || 1) * 0.15, 0.8),
        color: (e.severity||1) >= 7 ? '#ef4444' : (e.severity||1) >= 5 ? '#f97316' : (e.severity||1) >= 3 ? '#eab308' : '#22c55e',
        label: `${e.country_code||''} ${(e.title||'').substring(0,60)}`,
      }))
    g.pointsData(points)
  }

  useEffect(() => { updatePoints(events) }, [events])

  return <div ref={containerRef} style={{ width: '100%', height: '100%', background: '#0f131a' }} />
}
