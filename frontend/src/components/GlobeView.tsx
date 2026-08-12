import { useEffect, useRef } from 'react'

interface GeoPoint { id: string; title: string; lat: number; lng: number; severity?: number }
interface Props { events: GeoPoint[] }

export default function GlobeView({ events }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const globeRef = useRef<any>(null)
  const initRef = useRef(false)

  useEffect(() => {
    if (initRef.current || !containerRef.current) return
    initRef.current = true

    const el = containerRef.current

    import('globe.gl').then(mod => {
      const G = (mod as any).default || mod
      const g = G()(el)
        // NASA Blue Marble textures
        .globeImageUrl('//unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
        .bumpImageUrl('//unpkg.com/three-globe/example/img/earth-topology.png')
        // Atmosphere — Redroom-style blue glow
        .backgroundColor('#000011')
        .atmosphereColor('#3b7dff')
        .atmosphereAltitude(0.25)
        // Points
        .pointLat('lat').pointLng('lng')
        .pointColor('color').pointRadius('size').pointAltitude('alt')
        .pointResolution(12)
        .pointsMerge(true)
        .pointsData([])
        // Labels for high-severity events
        .pointLabel((d: any) => d.severity >= 7 ? d.label : '')
        .pointLabelSize(1.2)
        .pointLabelColor(() => '#ffffff')

      // Auto-rotate (slow, cinematic)
      g.controls().autoRotate = true
      g.controls().autoRotateSpeed = 0.3
      g.controls().enableZoom = true
      g.controls().minDistance = 150
      g.controls().maxDistance = 600

      // Pause auto-rotate on user interaction
      el.addEventListener('mousedown', () => g.controls().autoRotate = false)
      el.addEventListener('mouseup', () => setTimeout(() => { g.controls().autoRotate = true }, 5000))

      globeRef.current = g
      updatePoints()
    }).catch(e => {
      console.error('Globe init error:', e)
    })
  }, [])

  const updatePoints = () => {
    const g = globeRef.current
    if (!g) return
    const pts = events
      .filter(e => e.lat && e.lng)
      .map(e => ({
        lat: e.lat, lng: e.lng,
        size: Math.max(0.15, (e.severity || 3) * 0.08),
        color: e.severity && e.severity >= 7 ? '#ff4444' : e.severity && e.severity >= 5 ? '#ff9944' : '#ffcc00',
        alt: (e.severity || 1) * 0.005,
        severity: e.severity,
        label: (e.title || '').substring(0, 50),
      }))
    g.pointsData(pts)
  }

  useEffect(() => { updatePoints() }, [events])

  return (
    <div ref={containerRef} style={{
      width: '100%', height: '100%',
      background: 'radial-gradient(ellipse at center, #0a1628 0%, #000011 100%)',
    }}>
      <style>{`
        @keyframes twinkle {
          0%, 100% { opacity: 0.3; }
          50% { opacity: 0.8; }
        }
      `}</style>
    </div>
  )
}
