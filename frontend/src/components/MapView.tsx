import { useEffect, useRef, useState, useMemo } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import {
  TYPE_COLORS, eventKind, facilityKind, nodeIcon, pinIcon, relationColor,
} from './mapIcons'

interface GeoPoint { id: string; title: string; lat: number; lng: number; country_code?: string; severity?: number; confidence?: number; source_count?: number; time_start?: string; published_at?: string; type?: string; event_type?: string; url?: string; relation?: string; seq?: number; prev_id?: string | null; issue_id?: string; issue_title?: string }
interface Annotation { id: string; name: string; description?: string; type: string; coordinates: any; style?: any }

interface ChainData { nodes: {id:string; lat:number; lng:number; relation:string; title:string; severity:number}[]; edges: {from:string; to:string; from_relation:string; to_relation:string}[] }
interface TopicLayer { issue_id: string; name: string; category?: string; events?: number; mappable_events?: number }
interface Props { events: GeoPoint[]; searchResults: GeoPoint[]; annotations: Annotation[]; chain?: ChainData | null; flyTo?: {lat:number;lng:number} | null; topicLayers?: TopicLayer[]; activeTopics?: string[]; onToggleTopic?: (issueId: string) => void }

interface MarkerCache { [id: string]: { m: L.Marker; sig: string } }

// 差分更新图层标记：同 id 同签名 → 原地保留（避免每次轮询整层重建造成的闪烁/重播动画）；
// 新 id → 新建 marker 并播放入场动画；消失的 id → 移除。
function diffMarkers(
  cache: MarkerCache,
  layer: L.LayerGroup,
  items: GeoPoint[],
  build: (item: GeoPoint, isNew: boolean) => L.Marker,
  sigOf: (item: GeoPoint) => string,
) {
  const alive = new Set<string>()
  for (const it of items) {
    if (!it.lat || !it.lng) continue
    alive.add(it.id)
    const sig = sigOf(it)
    const hit = cache[it.id]
    if (hit && hit.sig === sig) {
      hit.m.setLatLng([it.lat, it.lng])
      continue
    }
    if (hit) layer.removeLayer(hit.m)
    const marker = build(it, !hit)
    marker.addTo(layer)
    cache[it.id] = { m: marker, sig }
  }
  for (const [id, hit] of Object.entries(cache)) {
    if (!alive.has(id)) {
      layer.removeLayer(hit.m)
      delete cache[id]
    }
  }
}

const fmtLocal = (iso?: string) => {
  if (!iso) return ''
  const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z')
  if (isNaN(d.getTime())) return iso.substring(0, 16)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}
const COUNTRY_LABEL: Record<string, string> = { TW: '中国台湾', HK: '中国香港', MO: '中国澳门' }
const escHtml = (s: string) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')

export default function MapView({ events, searchResults, annotations, chain, flyTo, topicLayers = [], activeTopics = [], onToggleTopic }: Props) {
  const mapRef = useRef<L.Map | null>(null)
  const groupsRef = useRef<Record<string, L.LayerGroup>>({})
  // 图层 marker 缓存（差分更新用）
  const markersRef = useRef<Record<string, MarkerCache>>({ event: {}, quake: {}, search: {}, annotation: {}, chain: {}, facility: {} })
  const facilitiesLoadedRef = useRef(false)
  // ── 多源卫星底图 (2026-08-26, 奥维方向): 后端 /api/map/basemaps 驱动 ──
  const [basemaps, setBasemaps] = useState<Record<string, any>>({})
  useEffect(() => {
    fetch('/api/map/basemaps').then(r => r.json()).then(d => setBasemaps(d.basemaps || {})).catch(() => {})
  }, [])
  // ── 时间轴回放 (2026-08-26): 滑块拖动 → 只显示该日期前(含)的事件 ──
  const [timeCursor, setTimeCursor] = useState<number | null>(null)  // epoch ms; null=全部
  const [showTimeline, setShowTimeline] = useState(false)

  const timeBounds = useMemo(() => {
    const ts = events.map(e => new Date(e.time_start || e.published_at || '').getTime()).filter(t => !isNaN(t))
    if (!ts.length) return null
    return { min: Math.min(...ts), max: Math.max(...ts) }
  }, [events])

  const visibleEvents = useMemo(() => {
    if (timeCursor === null || !timeBounds) return events
    return events.filter(e => {
      const t = new Date(e.time_start || e.published_at || '').getTime()
      return isNaN(t) || t <= timeCursor
    })
  }, [events, timeCursor, timeBounds])

  useEffect(() => {
    if (mapRef.current) return
    const map = L.map('map-container', {
      zoomSnap: 0.25,
      wheelPxPerZoomLevel: 100,
      fadeAnimation: true,
      zoomAnimation: true,
      markerZoomAnimation: true,
    }).setView([35, 105], 4)

    // 静态底图: 高德矢量(默认)。动态卫星源(NASA/天地图/自定义XYZ)由 basemaps effect 注入
    const baseTiles: Record<string, L.TileLayer> = {
      '高德地图': L.tileLayer('https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}', { subdomains: '1234', maxZoom: 18 }),
    }
    // 注: CartoDB/OSM 的国界渲染不符合中国地图出版标准（台湾/藏南/阿克赛钦），
    // 已从底图选项移除 (2026-08-21)。卫星源走 ESRI/NASA/天地图（无边界标注或官方合规）。
    baseTiles['高德地图'].addTo(map)

    // Create data layer groups
    const overlays: Record<string, L.LayerGroup> = {
      '实时事件': L.layerGroup(),
      '地震': L.layerGroup(),
      'Chains': L.layerGroup(),
      '设施库': L.layerGroup(),
      'Annotations': L.layerGroup(),
      'Search Results': L.layerGroup(),
    }
    Object.entries(overlays).forEach(([name, g]) => {
      // 设施库是 200 个静态点位，默认不压在地图上（避免盖住新闻事件），
      // 需要时在右下角图层控制里勾选。
      if (name !== '设施库') g.addTo(map)
    })
    groupsRef.current = overlays

    L.control.layers(baseTiles, overlays as any, { position: 'bottomright', collapsed: true }).addTo(map)
    mapRef.current = map
    ;(map as any)._kaiyangBaseTiles = baseTiles
  }, [])

  // 动态卫星底图注入: basemaps 配置变化时把新源加进图层切换器
  // (layers control 不可变——重建控件是 Leaflet 惯用法)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !basemaps || !Object.keys(basemaps).length) return
    const existing: Record<string, L.TileLayer> = (map as any)._kaiyangBaseTiles || {}
    // ESRI 卫星保持常驻(旧版默认)
    if (!existing['卫星影像']) {
      existing['卫星影像'] = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 17 })
    }
    for (const [key, cfg] of Object.entries(basemaps)) {
      if (existing[cfg.label]) continue
      let url: string = cfg.url
      if (cfg.date === 'dynamic') {
        // NASA GIBS: 今天(UTC)影像, 回退一天保证瓦片已生成
        const d = new Date()
        const iso = d.toISOString().substring(0, 10)
        url = url.replace('{date}', iso)
      }
      const opts: any = { maxZoom: cfg.maxZoom || 17 }
      if (cfg.subdomains) opts.subdomains = cfg.subdomains
      existing[cfg.label] = L.tileLayer(url, opts)
    }
    // 重建图层控件（含新底图）
    ;(map as any)._kaiyangLayersControl?.remove()
    const overlays = groupsRef.current || {}
    const ctrl = L.control.layers(existing as any, overlays as any, { position: 'bottomright', collapsed: true }).addTo(map)
    ;(map as any)._kaiyangLayersControl = ctrl
    ;(map as any)._kaiyangBaseTiles = existing
  }, [basemaps])

  const makePopup = (e: GeoPoint, extra: string) => {
    const sev = e.severity || 1
    let html = `<div style="max-width:300px"><b>${escHtml(e.title || '')}</b>`
    html += `<br><small style="color:#64748b">${COUNTRY_LABEL[e.country_code || ''] || e.country_code || '?'} | ${fmtLocal(e.time_start || e.published_at)} | imp:${sev}/10`
    if (e.source_count) html += ` | ${e.source_count}sources`
    html += `</small>${extra}`
    html += `<br><a href="#" onclick="event.preventDefault();window.loadEventItems('${e.id}')" style="font-size:11px">查看报道</a>`
    html += ` | <a href="#" onclick="event.preventDefault();window.tianshuPopup('${encodeURIComponent((e.title || '').substring(0, 80))}')" style="font-size:11px">Tianshu</a>`
    html += `<div id="evt-items-${e.id}" style="margin-top:4px"></div></div>`
    return html
  }

  // ── 实时事件 / 地震 / 搜索：差分更新（不整层 clear，避免闪烁和动画重播）──
  useEffect(() => {
    const g = groupsRef.current
    if (!g) return
    const caches = markersRef.current
    const quakes = visibleEvents.filter(e => e.title?.toLowerCase().includes('earthquake') || e.title?.toLowerCase().includes('magnitude'))
    const others = visibleEvents.filter(e => !quakes.includes(e))

    diffMarkers(caches.event, g['实时事件'], others, (e, isNew) => {
      const sev = e.severity || 1
      const kind = eventKind(e.event_type)
      const size = Math.round(17 + sev * 1.15)
      const pulse = sev >= 7 ? 'fast' : sev >= 5 ? 'slow' : null
      const tip = `${(e.title || '').substring(0, 42)}`
      return L.marker([e.lat, e.lng], {
        icon: pinIcon(kind, TYPE_COLORS[kind], { size, pulse, animate: isNew }),
        riseOnHover: true,
        keyboard: false,
      } as any)
        .bindPopup(makePopup(e, ''), { maxWidth: 320, autoPanPadding: [24, 24] })
        .bindTooltip(tip, { direction: 'top', offset: [0, -size / 2 - 2], opacity: 0.95, className: 'ky-tip' })
    }, e => `${e.severity}|${e.event_type}|${e.lat.toFixed(3)}|${e.lng.toFixed(3)}|${e.title}`)

    diffMarkers(caches.quake, g['地震'], quakes, (e, isNew) => {
      const mag = parseFloat((e.title || '').match(/M(\d+\.?\d*)/)?.[1] || '0')
      const color = mag >= 7 ? '#7f1d1d' : mag >= 6 ? '#dc2626' : mag >= 5 ? '#f97316' : '#eab308'
      const size = Math.min(20 + mag * 3.4, 40)
      return L.marker([e.lat, e.lng], {
        icon: pinIcon('quake', color, { size, label: `M${mag.toFixed(1)}`, pulse: mag >= 6 ? 'fast' : null, animate: isNew }),
        riseOnHover: true,
        keyboard: false,
      } as any).bindPopup(makePopup(e, `<br><small style="color:${color}">M${mag.toFixed(1)}</small>`))
    }, e => `${e.title}|${e.lat.toFixed(3)}|${e.lng.toFixed(3)}`)

    diffMarkers(caches.search, g['Search Results'], searchResults, (e, isNew) => {
      const extra = e.url ? `<br><a href="${escHtml(e.url)}" target="_blank" style="font-size:11px;color:#60a5fa">source ↗</a>` : ''
      return L.marker([e.lat, e.lng], {
        icon: pinIcon('search', '#38bdf8', { size: 22, animate: isNew }),
        riseOnHover: true,
        keyboard: false,
      } as any).bindPopup(`<div style="max-width:280px"><b>${escHtml(e.title || '')}</b><br><small style="color:#64748b">${e.country_code || ''}${extra}</small></div>`)
    }, e => `${e.title}|${e.lat.toFixed(3)}|${e.lng.toFixed(3)}`)
  }, [visibleEvents, searchResults])

  // ── Annotations：数据变化才重建 ──
  useEffect(() => {
    const g = groupsRef.current
    if (!g) return
    g['Annotations'].clearLayers()
    annotations.forEach(a => {
      const coords = a.coordinates
      if (a.type === 'polyline' && Array.isArray(coords) && coords.length >= 2 && Array.isArray(coords[0])) {
        L.polyline(coords as [number, number][], { color: (a.style as any)?.color || '#ef4444', weight: 3, opacity: 0.8 })
          .bindPopup(`<b>${escHtml(a.name)}</b><br><small>${escHtml(a.description || '')}</small>`).addTo(g['Annotations'])
      } else if (a.type === 'point' && Array.isArray(coords) && coords.length >= 2) {
        L.marker([coords[0] as number, coords[1] as number], {
          icon: pinIcon('annotation', '#a855f7', { size: 24 }),
          riseOnHover: true,
        } as any).bindPopup(`<b>${escHtml(a.name)}</b><br><small>${escHtml(a.description || '')}</small>`).addTo(g['Annotations'])
      }
    })
  }, [annotations])

  // ── Chain：编号节点 + 关系色连线 ──
  useEffect(() => {
    const g = groupsRef.current
    if (!g) return
    g['Chains'].clearLayers()
    if (chain) {
      const nodeMap: Record<string, any> = {}
      chain.nodes.forEach((n, i) => {
        nodeMap[n.id] = n
        const c = relationColor(n.relation)
        L.marker([n.lat, n.lng], {
          icon: nodeIcon(i + 1, c),
          riseOnHover: true,
        } as any).bindPopup(`<b>${escHtml(n.relation)}</b>: ${escHtml(n.title || '')}`).addTo(g['Chains'])
      })
      chain.edges.forEach(e => {
        const a = nodeMap[e.from], b = nodeMap[e.to]
        if (a && b) {
          L.polyline([[a.lat, a.lng], [b.lat, b.lng]], { color: '#eab308', weight: 2, dashArray: '6,4', opacity: 0.7 })
            .bindPopup(`${e.from_relation} → ${e.to_relation}`).addTo(g['Chains'])
        }
      })
    }
  }, [chain])

  // ── 设施库：只加载一次 + 类型图标 ──
  useEffect(() => {
    const g = groupsRef.current
    if (!g || facilitiesLoadedRef.current) return
    facilitiesLoadedRef.current = true
    fetch('/api/facilities?limit=200').then(r => r.json()).then(d => {
      (d.facilities || []).forEach((f: any) => {
        if (!f.lat || !f.lng) return
        const color = f.threat >= 5 ? '#ef4444' : f.threat >= 4 ? '#f97316' : f.threat >= 3 ? '#eab308' : '#3b82f6'
        const kind = facilityKind(f.type)
        const typeLabel: Record<string, string> = {
          military_base: '军事基地', nuclear: '核设施', port: '港口',
          airport: '机场', spaceport: '航天港', chokepoint: '咽喉要道',
        }
        L.marker([f.lat, f.lng], {
          icon: pinIcon(kind, color, { size: 17, shape: 'square' }),
          riseOnHover: true,
        } as any).bindPopup(`<b>${typeLabel[f.type] || '设施'} · ${escHtml(f.name)}</b><br><small>${escHtml(f.country || '')} | 威胁:${f.threat}/5<br>${escHtml(f.description || '')}</small>`).addTo(g['设施库'])
      })
    }).catch(() => { facilitiesLoadedRef.current = false })
  }, [])

  // ── FlyTo：平滑飞行 ──
  useEffect(() => {
    if (flyTo) mapRef.current?.flyTo([flyTo.lat, flyTo.lng], 6, { duration: 1.6, easeLinearity: 0.22 })
  }, [flyTo])

  // ── 专题图层（Issue 批次）：勾选显示、取消隐藏 ──
  const loadedTopicsRef = useRef<Record<string, GeoPoint[]>>({})
  useEffect(() => {
    const g = groupsRef.current
    if (!g) return
    const map = mapRef.current
    if (!map) return

    // 移除已取消勾选的专题组
    Object.keys(g).forEach(key => {
      if (key.startsWith('topic:') && !activeTopics.includes(key.slice(6))) {
        map.removeLayer(g[key])
        delete g[key]
      }
    })

    activeTopics.forEach(tid => {
      const layerKey = `topic:${tid}`
      // 已加载则跳过（数据不变）
      if (g[layerKey]) return

      const layer = L.layerGroup()
      fetch(`/api/map/issue-points?issue_id=${tid}`).then(r => r.json()).then(d => {
        const pts: GeoPoint[] = d.points || []
        loadedTopicsRef.current[tid] = pts
        const byId: Record<string, GeoPoint> = {}
        pts.forEach(p => { byId[p.id] = p })
        // 连线（事件链顺序）
        pts.forEach(p => {
          if (p.prev_id && byId[p.prev_id] && p.lat && p.lng && byId[p.prev_id].lat) {
            L.polyline([[byId[p.prev_id].lat!, byId[p.prev_id].lng!], [p.lat!, p.lng!]],
              { color: relationColor(p.relation), weight: 2, dashArray: '4,4', opacity: 0.7 })
              .bindTooltip(`${p.relation || ''}: ${p.title || ''}`, { className: 'ky-tip' })
              .addTo(layer)
          }
        })
        // 节点
        pts.forEach(p => {
          if (!p.lat || !p.lng) return
          L.marker([p.lat, p.lng], {
            icon: pinIcon(eventKind(p.event_type), relationColor(p.relation), { size: 20 }),
            riseOnHover: true,
          } as any).bindPopup(`<div style="max-width:280px"><b>${escHtml(p.title || '')}</b><br><small style="color:#64748b">${escHtml(p.issue_title || '')} | ${p.relation || ''} | ${p.time_start?.substring(0, 10) || ''} | conf:${p.confidence}</small></div>`)
            .addTo(layer)
        })
        layer.addTo(map)
        g[layerKey] = layer
      })
    })
  }, [activeTopics])

  return (
    <>
      <div id="map-container" style={{ width: '100%', height: '100%', position: 'relative' }} />

      {/* 图例：类型配色 + 高危脉冲 */}
      <div className="ky-legend">
        <span className="ky-legend__title">图例</span>
        {(Object.keys(TYPE_COLORS) as (keyof typeof TYPE_COLORS)[]).slice(0, 7).map(k => (
          <span key={k} className="ky-legend__item" style={{ color: TYPE_COLORS[k] }}>
            <i />
            <em style={{ fontStyle: 'normal', color: '#94a3b8' }}>
              {{ conflict: '冲突', military: '军事', disaster: '灾害', political: '政治', economic: '经济', social: '社会', tech: '科技' }[k]}
            </em>
          </span>
        ))}
        <span className="ky-legend__sep" />
        <span className="ky-legend__item" style={{ color: '#ef4444' }}><i className="ky-legend__ring" />高危脉冲</span>
      </div>

      {/* 专题图层管理面板 */}
      <div style={{
        position: 'absolute', top: 10, right: 10, zIndex: 1000,
        background: 'rgba(15,23,42,0.92)', borderRadius: 8, padding: '10px 12px',
        color: '#e2e8f0', fontSize: 12, minWidth: 180, border: '1px solid #334155',
      }}>
        <div style={{ fontWeight: 700, marginBottom: 6, color: '#e2c860' }}>专题图层</div>
        {topicLayers.length === 0 && <div style={{ color: '#64748b' }}>（无议题）</div>}
        {topicLayers.map(t => (
          <label key={t.issue_id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={activeTopics.includes(t.issue_id)}
              style={{ accentColor: '#e2c860' }}
              onChange={() => onToggleTopic?.(t.issue_id)}
            />
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {t.name}
            </span>
            <span style={{ color: '#64748b' }}>{t.mappable_events ?? 0}点</span>
          </label>
        ))}
      </div>

      {/* 时间轴回放条 */}
      <div style={{ position: 'absolute', left: 10, bottom: 28, zIndex: 1000, display: 'flex', gap: 6 }}>
        <button
          onClick={() => { setShowTimeline(v => !v); if (showTimeline) setTimeCursor(null) }}
          style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--fg)',
            padding: '4px 10px', borderRadius: 4, fontSize: 12, cursor: 'pointer',
          }}
        >
          {showTimeline ? '✕ 时间轴' : '⏱ 时间轴'}
        </button>
      </div>
      {showTimeline && timeBounds && (
        <div style={{
          position: 'absolute', left: 10, bottom: 56, zIndex: 1000,
          background: 'rgba(15,23,42,0.94)', borderRadius: 8, padding: '8px 12px',
          border: '1px solid #334155', width: 320,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>
            <span>{new Date(timeBounds.min).toLocaleDateString('zh-CN')}</span>
            <span style={{ color: '#e2c860', fontWeight: 700 }}>
              {timeCursor === null ? '全部' : new Date(timeCursor).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}
              {' '}({visibleEvents.length}/{events.length} 事件)
            </span>
            <span>{new Date(timeBounds.max).toLocaleDateString('zh-CN')}</span>
          </div>
          <input
            type="range"
            min={timeBounds.min}
            max={timeBounds.max}
            step={24 * 3600 * 1000}
            value={timeCursor ?? timeBounds.max}
            onChange={e => setTimeCursor(Number(e.target.value))}
            style={{ width: '100%', accentColor: '#e2c860', cursor: 'pointer' }}
          />
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button
              onClick={() => setTimeCursor(timeBounds.max)}
              style={{ flex: 1, background: '#1d4ed8', border: 'none', color: '#fff', padding: '3px 0', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}
            >拉满</button>
            <button
              onClick={() => setTimeCursor(null)}
              style={{ flex: 1, background: '#475569', border: 'none', color: '#fff', padding: '3px 0', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}
            >关闭过滤</button>
          </div>
        </div>
      )}
    </>
  )
}
