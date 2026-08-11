import { useEffect, useRef } from 'react'

interface GeoPoint { id: string; title: string; lat: number; lng: number; severity?: number }
interface Props { events: GeoPoint[] }

export default function GlobeView({ events }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const globeRef = useRef<any>(null)

  useEffect(() => {
    if (globeRef.current || !containerRef.current) return

    import('globe.gl').then(mod => {
      const Globe = (mod as any).default || mod
      const el = containerRef.current
      if (!el) return

      // WorldMonitor-style: new Globe(element)
      const g = Globe()(el)
        .globeImageUrl('//unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
        .bumpImageUrl('//unpkg.com/three-globe/example/img/earth-topology.png')
        .backgroundColor('#0f131a')
        .atmosphereColor('#3b82f6')
        .atmosphereAltitude(0.15)
        .pointLat('lat')
        .pointLng('lng')
        .pointColor('color')
        .pointRadius('size')
        .pointLabel('label')
        .pointsData([])

      // Auto-rotate
      g.controls().autoRotate = true
      g.controls().autoRotateSpeed = 0.5

      globeRef.current = g
      updatePoints(events)
    })
  }, [])

  const updatePoints = (pts: GeoPoint[]) => {
    const g = globeRef.current
    if (!g) return
    const points = pts
      .filter(e => e.lat && e.lng)
      .map(e => ({
        lat: e.lat, lng: e.lng,
        size: Math.min((e.severity || 1) * 0.12, 0.6),
        color: e.severity && e.severity >= 7 ? '#ef4444' : e.severity && e.severity >= 5 ? '#f97316' : '#eab308',
        label: (e.title || '').substring(0, 60),
      }))
    g.pointsData(points)
  }

  useEffect(() => { updatePoints(events) }, [events])

  return <div ref={containerRef} style={{ width: '100%', height: '100%', background: '#0f131a' }} />
}
