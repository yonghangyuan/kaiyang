import { useEffect, useRef, useState } from 'react'

interface GeoPoint { id: string; title: string; lat: number; lng: number; severity?: number }
interface Props { events: GeoPoint[] }

export default function GlobeView({ events }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const globeRef = useRef<any>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (globeRef.current || !containerRef.current) return

    const el = containerRef.current
    // Ensure container has dimensions
    if (el.clientWidth === 0 || el.clientHeight === 0) {
      const timer = setTimeout(() => {
        if (el.clientWidth > 0) initGlobe()
      }, 500)
      return () => clearTimeout(timer)
    }

    initGlobe()

    async function initGlobe() {
      try {
        const mod = await import('globe.gl')
        const G = (mod as any).default || mod
        const g = G()(el)
          .globeImageUrl('//unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
          .backgroundColor('#0f131a')
          .atmosphereColor('#3b82f6')
          .atmosphereAltitude(0.2)
          .pointLat('lat').pointLng('lng').pointColor('color').pointRadius('size')
          .pointsData([])
        g.controls().autoRotate = true
        g.controls().autoRotateSpeed = 0.4
        globeRef.current = g
        setReady(true)
      } catch (e) {
        console.error('Globe init failed:', e)
      }
    }
  }, [])

  useEffect(() => {
    const g = globeRef.current
    if (!g) return
    const pts = events.filter(e => e.lat && e.lng).map(e => ({
      lat: e.lat, lng: e.lng,
      size: Math.min((e.severity || 1) * 0.12, 0.6),
      color: e.severity && e.severity >= 7 ? '#ef4444' : e.severity && e.severity >= 5 ? '#f97316' : '#eab308',
    }))
    g.pointsData(pts)
  }, [events, ready])

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', minHeight: 400, background: '#0f131a' }}>
      {!ready && <div style={{color:'#64748b',textAlign:'center',paddingTop:'40vh',fontSize:14}}>Loading 3D Globe...</div>}
    </div>
  )
}
