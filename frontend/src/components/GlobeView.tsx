import { useEffect, useRef } from 'react'

interface GeoPoint { id: string; title: string; lat: number; lng: number; severity?: number }
interface Props { events: GeoPoint[]; onZoomToMap?: () => void }

export default function GlobeView({ events, onZoomToMap }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const globeRef = useRef<any>(null)
  const initRef = useRef(false)

  useEffect(() => {
    if (initRef.current || !containerRef.current) return
    initRef.current = true

    import('globe.gl').then(mod => {
      const G = (mod as any).default || mod
      const g = G()(containerRef.current!)
        .globeImageUrl('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
        .bumpImageUrl('https://unpkg.com/three-globe/example/img/earth-topology.png')
        .backgroundColor('#000011')
        .atmosphereColor('#4488ff')
        .atmosphereAltitude(0.25)
        .pointLat('lat').pointLng('lng').pointColor('color').pointRadius('size')
        .pointsMerge(true).pointsData([])

      g.controls().autoRotate = false
      g.controls().minDistance = 150
      g.controls().maxDistance = 2000

      globeRef.current = g
      updatePoints()
    })
  }, [])

  const updatePoints = () => {
    const g = globeRef.current
    if (!g) return
    g.pointsData(events.filter(e => e.lat && e.lng).map(e => ({
      lat: e.lat, lng: e.lng,
      size: 0.2 + (e.severity || 3) * 0.06,
      color: e.severity && e.severity >= 7 ? '#ff3333' : e.severity && e.severity >= 5 ? '#ff8833' : '#ffcc00',
    })))
  }

  useEffect(() => { updatePoints() }, [events])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%', background: '#000011' }} />
      <button onClick={onZoomToMap} style={{ position: 'absolute', top: 10, right: 10, zIndex: 1000, background: 'rgba(0,0,0,0.7)', border: '1px solid #334155', color: '#fff', padding: '4px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}>🗺️ 2D Map</button>
    </div>
  )
}
