import { useEffect, useRef, useState } from 'react'

interface GeoPoint { id: string; title: string; lat: number; lng: number; severity?: number }
interface Props { events: GeoPoint[]; onZoomToMap?: () => void }

export default function GlobeView({ events, onZoomToMap }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const globeRef = useRef<any>(null)
  const [status, setStatus] = useState('Loading globe...')

  useEffect(() => {
    if (globeRef.current) return
    const el = containerRef.current
    if (!el) return

    // Load globe.gl from CDN (most reliable)
    const script = document.createElement('script')
    script.src = 'https://unpkg.com/globe.gl'
    script.onload = () => {
      const G = (window as any).Globe
      if (!G) { setStatus('Globe library failed to load'); return }

      try {
        const g = G()(el)
          .globeImageUrl('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
          .bumpImageUrl('https://unpkg.com/three-globe/example/img/earth-topology.png')
          .backgroundColor('#000011')
          .atmosphereColor('#4488ff')
          .atmosphereAltitude(0.25)
          .pointLat('lat').pointLng('lng').pointColor('color').pointRadius('size').pointAltitude('alt')
          .pointsMerge(true)
          .pointsData([])

        g.controls().autoRotate = true
        g.controls().autoRotateSpeed = 0.3
        g.controls().minDistance = 150

        globeRef.current = g
        setStatus('')
        updatePoints()
      } catch (e: any) {
        setStatus('Error: ' + e.message)
      }
    }
    script.onerror = () => setStatus('CDN load failed')
    document.head.appendChild(script)
  }, [])

  const updatePoints = () => {
    const g = globeRef.current
    if (!g) return
    g.pointsData(events.filter(e => e.lat && e.lng).map(e => ({
      lat: e.lat, lng: e.lng,
      size: 0.2 + (e.severity || 3) * 0.06,
      color: e.severity && e.severity >= 7 ? '#ff3333' : e.severity && e.severity >= 5 ? '#ff8833' : '#ffcc00',
      alt: 0.005,
    })))
  }

  useEffect(() => { updatePoints() }, [events])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%', background: '#000011' }} />
      {status && <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', color: '#64748b', fontSize: 14 }}>{status}</div>}
      <button onClick={onZoomToMap}
        style={{ position: 'absolute', top: 10, right: 10, zIndex: 1000, background: 'rgba(0,0,0,0.7)', border: '1px solid #334155', color: '#fff', padding: '4px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}>
        🗺️ 2D Map
      </button>
    </div>
  )
}
