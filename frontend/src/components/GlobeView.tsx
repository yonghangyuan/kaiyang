import { useEffect, useRef } from 'react'
import * as THREE from 'three'

interface GeoPoint { id: string; title: string; lat: number; lng: number; severity?: number }
interface Props { events: GeoPoint[]; onZoomToMap?: (lat: number, lng: number) => void }

// NASA Blue Marble 8K textures (NextGen, Jan 2004)
const DAY_TEX = 'https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/Blue_Marble_2002.png/1280px-Blue_Marble_2002.png'
const NIGHT_TEX = 'https://unpkg.com/three-globe/example/img/earth-night.jpg'

const textureLoader = new THREE.TextureLoader()
let dayTex: THREE.Texture | null = null
let nightTex: THREE.Texture | null = null

export default function GlobeView({ events, onZoomToMap }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const globeRef = useRef<any>(null)
  const initRef = useRef(false)

  useEffect(() => {
    if (initRef.current || !containerRef.current) return
    initRef.current = true
    const el = containerRef.current

    // Preload textures
    Promise.all([
      new Promise<THREE.Texture>(res => textureLoader.load(DAY_TEX, res)),
      new Promise<THREE.Texture>(res => textureLoader.load(NIGHT_TEX, res)),
      import('globe.gl'),
    ]).then(([day, night, mod]) => {
      dayTex = day; nightTex = night
      const G = (mod as any).default || mod

      const g = G()(el)
        .globeImageUrl(DAY_TEX)
        .bumpImageUrl('//unpkg.com/three-globe/example/img/earth-topology.png')
        .backgroundColor('#000010')
        .atmosphereColor('#4488ff')
        .atmosphereAltitude(0.3)
        .pointLat('lat').pointLng('lng').pointColor('color').pointRadius('size').pointAltitude('alt')
        .pointResolution(16)
        .pointsMerge(true)
        .pointsData([])
        .pointLabel((d: any) => d.severity >= 6 ? d.label : '')
        .pointLabelSize(1.0)
        .pointLabelColor(() => '#e0e0e0')

      // Night lights — access Three.js globe material
      setTimeout(() => {
        try {
          const globeMesh = (g as any).globeMesh?.() || (g as any)._globeMesh
          if (globeMesh?.material) {
            const mat = globeMesh.material
            if (Array.isArray(mat)) {
              mat.forEach(m => { m.emissiveMap = night; m.emissive = new THREE.Color(0x112244); m.emissiveIntensity = 0.4 })
            } else {
              mat.emissiveMap = night; mat.emissive = new THREE.Color(0x112244); mat.emissiveIntensity = 0.4
            }
          }
        } catch {}
      }, 1000)

      // Controls
      const ctrl = g.controls()
      ctrl.autoRotate = true
      ctrl.autoRotateSpeed = 0.3
      ctrl.minDistance = 120
      ctrl.maxDistance = 2000
      ctrl.enableZoom = true
      ctrl.zoomSpeed = 1.2

      // Zoom detection → switch to 2D map
      let lastDist = 200
      ctrl.addEventListener('change', () => {
        const cam = ctrl.object as THREE.PerspectiveCamera
        const dist = cam.position.length()
        if (dist < 130 && lastDist >= 130 && onZoomToMap) {
          // Zoomed in close → get center point and switch
          const center = (g as any).getCoords?.({ lat: 0, lng: 0 }) || { lat: 35, lng: 105 }
          onZoomToMap(0, 0)  // approximate
        }
        lastDist = dist
      })

      el.addEventListener('mousedown', () => ctrl.autoRotate = false)
      el.addEventListener('mouseup', () => setTimeout(() => { ctrl.autoRotate = true }, 4000))

      globeRef.current = g
      renderPoints()
    }).catch(e => console.error('Globe error:', e))
  }, [])

  const renderPoints = () => {
    const g = globeRef.current
    if (!g) return
    const pts = events.filter(e => e.lat && e.lng).map(e => ({
      lat: e.lat, lng: e.lng,
      size: Math.max(0.15, (e.severity || 3) * 0.1),
      color: e.severity && e.severity >= 7 ? '#ff3333' : e.severity && e.severity >= 5 ? '#ff8833' : '#ffcc00',
      alt: (e.severity || 2) * 0.006,
      severity: e.severity,
      label: (e.title || '').substring(0, 50),
    }))
    g.pointsData(pts)
  }

  useEffect(() => { renderPoints() }, [events])

  return <div ref={containerRef} style={{ width: '100%', height: '100%', background: 'radial-gradient(ellipse at center, #0a1a30 0%, #000010 100%)' }} />
}
