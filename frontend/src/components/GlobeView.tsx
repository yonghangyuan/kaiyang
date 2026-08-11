import { useEffect, useRef } from 'react'

interface GeoPoint { id: string; title: string; lat: number; lng: number; severity?: number }
interface Props { events: GeoPoint[] }

export default function GlobeView({ events }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const globeRef = useRef<any>(null)
  const pointsRef = useRef<GeoPoint[]>([])

  pointsRef.current = events

  useEffect(() => {
    if (globeRef.current || !containerRef.current) return
    let cancelled = false

    async function init() {
      const mod = await import('globe.gl')
      if (cancelled || !containerRef.current) return
      const G = (mod as any).default || mod

      const g = G()(containerRef.current)
        .globeImageUrl('//unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
        .backgroundColor('#0f131a')
        .atmosphereColor('#3b82f6')
        .atmosphereAltitude(0.2)
        .pointLat('lat').pointLng('lng').pointColor('color').pointRadius('size')
        .pointsData([])

      g.controls().autoRotate = true
      g.controls().autoRotateSpeed = 0.4

      globeRef.current = g
      renderPoints()
    }

    function renderPoints() {
      const g = globeRef.current
      if (!g) return
      const pts = pointsRef.current.filter(e => e.lat && e.lng).map(e => ({
        lat: e.lat, lng: e.lng,
        size: Math.min((e.severity || 1) * 0.12, 0.6),
        color: e.severity && e.severity >= 7 ? '#ef4444' : e.severity && e.severity >= 5 ? '#f97316' : '#eab308',
      }))
      if (pts.length > 0) g.pointsData(pts)
    }

    init()
    return () => { cancelled = true }
  }, [])

  // Update points when events change
  useEffect(() => {
    const g = globeRef.current
    if (!g) return
    const pts = events.filter(e => e.lat && e.lng).map(e => ({
      lat: e.lat, lng: e.lng,
      size: Math.min((e.severity || 1) * 0.12, 0.6),
      color: e.severity && e.severity >= 7 ? '#ef4444' : e.severity && e.severity >= 5 ? '#f97316' : '#eab308',
    }))
    if (pts.length > 0) g.pointsData(pts)
  }, [events])

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
  )
}
