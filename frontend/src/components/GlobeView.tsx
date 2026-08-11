import { useEffect, useRef } from 'react'

interface GeoPoint { id: string; title: string; lat: number; lng: number; severity?: number }

interface Props { events: GeoPoint[] }

const globeInstance = { current: null as any }

export default function GlobeView({ events }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (globeInstance.current || !containerRef.current) return
    import('globe.gl').then(mod => {
      const G = (mod as any).default || mod
      const globe = G()(containerRef.current)
        .globeImageUrl('//unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
        .backgroundColor('#0f131a')
        .atmosphereColor('#3b82f6')
        .atmosphereAltitude(0.15)
        .pointLat('lat').pointLng('lng').pointColor('color').pointRadius('size').pointLabel('label')
        .pointsData([])
      globeInstance.current = globe
    })
  }, [])

  useEffect(() => {
    const globe = globeInstance.current
    if (!globe) return
    const points = events
      .filter(e => e.lat && e.lng)
      .map(e => ({
        lat: e.lat, lng: e.lng,
        size: Math.min((e.severity || 1) * 0.15, 0.8),
        color: (e.severity||1) >= 7 ? '#ef4444' : (e.severity||1) >= 5 ? '#f97316' : '#eab308',
        label: (e.title || '').substring(0, 60),
      }))
    globe.pointsData(points)
  }, [events])

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
}
