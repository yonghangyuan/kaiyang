// 开阳地图图标与配色（2026-10-29 视觉升级）
// 目标：替换原来的"纯色圆圈"——统一 SVG 徽章图标 + 类型配色 + 平滑出入场/脉冲动画。
import L from 'leaflet'

export type PinKind =
  | 'conflict' | 'military' | 'disaster' | 'political'
  | 'economic' | 'social' | 'tech' | 'other'

// 类型配色（地图图标主体色；严重度用尺寸 + 脉冲环表达）
export const TYPE_COLORS: Record<PinKind, string> = {
  conflict: '#ef4444',
  military: '#3b82f6',
  disaster: '#f97316',
  political: '#a855f7',
  economic: '#22c55e',
  social: '#06b6d4',
  tech: '#14b8a6',
  other: '#94a3b8',
}

const GLYPHS: Record<string, string> = {
  // 冲突：爆裂星芒
  conflict: '<path d="M12 2.8l2.2 6.3 6.6 2.3-6.6 2.3L12 20l-2.2-6.3L3.2 11.4l6.6-2.3z"/>',
  // 军事：盾牌
  military: '<path d="M12 3l6.8 2.7v5c0 4.3-2.8 7.3-6.8 9-4-1.7-6.8-4.7-6.8-9v-5z"/><path d="M12 8v4.2"/><circle cx="12" cy="15" r="1.1"/>',
  // 灾害：警示三角
  disaster: '<path d="M12 3.6L20.8 19H3.2z"/><path d="M12 9.2v4.1"/><circle cx="12" cy="16.1" r="1.05"/>',
  // 政治：旗帜
  political: '<path d="M6.2 3.5v17"/><path d="M6.2 4.6h10.2l-2.3 3.4 2.3 3.4H6.2"/>',
  // 经济：趋势线
  economic: '<path d="M4 18.4l5.1-5.1 2.9 2.3L19.5 8"/><path d="M14.6 8h4.9v4.9"/>',
  // 社会：人群
  social: '<circle cx="9.2" cy="8.4" r="2.6"/><path d="M3.9 19c0-3 2.3-5 5.3-5s5.3 2 5.3 5"/><circle cx="16.6" cy="9.6" r="2"/><path d="M15.2 14.4c2.4.5 4 2.1 4 4.6"/>',
  // 科技：芯片
  tech: '<rect x="7" y="7" width="10" height="10" rx="2.2"/><path d="M10 3.2v3.8M14 3.2v3.8M10 17v3.8M14 17v3.8M3.2 10h3.8M3.2 14h3.8M17 10h3.8M17 14h3.8"/>',
  other: '<circle cx="12" cy="12" r="6.2"/><circle cx="12" cy="12" r="1.5"/>',
  // 地震波形
  quake: '<path d="M2.4 12.6h4l2-5.6 3 11.2 2.6-8.4 1.8 2.8h5.8"/>',
  search: '<circle cx="10.6" cy="10.6" r="5.4"/><path d="M14.6 14.6l4.6 4.6"/>',
  annotation: '<path d="M12 20.8s-6.3-5.9-6.3-10.3a6.3 6.3 0 1112.6 0c0 4.4-6.3 10.3-6.3 10.3z"/><circle cx="12" cy="10.2" r="2.2"/>',
  // 设施库
  base: '<path d="M3.6 20.2h16.8"/><path d="M6.8 20.2V9.4l5.2-4 5.2 4v10.8"/><path d="M10 20.2v-4.8h4v4.8"/>',
  nuclear: '<circle cx="12" cy="12" r="1.7"/><path d="M12 3.5a8.5 8.5 0 011.7 0M5.4 17.2a8.5 8.5 0 01-1-1.6M18.6 17.2a8.5 8.5 0 00-1.7 2.4M5.4 17.2a8.5 8.5 0 011.7 2.4"/>',
  port: '<path d="M12 3.2v12.2"/><circle cx="12" cy="4.9" r="1.5"/><path d="M5.6 12.2a6.4 6.4 0 0012.8 0"/><path d="M3.4 12.2h4.4M16.2 12.2h4.4"/>',
  airport: '<path d="M10.6 20.6l1.5-6 7.1 1.8v-2L11.7 10V4.1a1.9 1.9 0 10-3.8 0V10l-6.5 4.4v2l6.5-1.8 1.5 6z"/>',
  spaceport: '<path d="M12 2.9c2.6 2.6 3.9 5.9 3.9 9.9L12 16l-3.9-3.2c0-4 1.3-7.3 3.9-9.9z"/><path d="M8 16.4l-2 4.9M16 16.4l2 4.9"/>',
  chokepoint: '<path d="M12 3.6L20.8 19H3.2z"/><path d="M12 9.2v4.1"/><circle cx="12" cy="16.1" r="1.05"/>',
}

export interface PinOpts {
  size?: number
  pulse?: 'slow' | 'fast' | null
  label?: string
  animate?: boolean
}

/** 圆形/圆角徽章图标：主题色底 + 白色线性图标；severity 高时带慢/快脉冲环。 */
export function pinIcon(kind: string, color: string, opts: PinOpts = {}): L.DivIcon {
  const size = Math.round(opts.size ?? 22)
  const glyph = GLYPHS[kind] ?? GLYPHS.other
  const cls = ['ky-pin']
  if (opts.pulse) cls.push(`ky-pin--pulse-${opts.pulse}`)
  if (opts.animate === false) cls.push('ky-pin--static')
  const label = opts.label ? `<span class="ky-pin__label">${opts.label}</span>` : ''
  const html =
    `<div class="${cls.join(' ')}" style="--ky-c:${color};width:${size}px;height:${size}px">` +
    `<span class="ky-pin__halo"></span>` +
    `<span class="ky-pin__body"><svg viewBox="0 0 24 24" aria-hidden="true">${glyph}</svg></span>` +
    `${label}</div>`
  return L.divIcon({ html, className: 'ky-marker', iconSize: [size, size], iconAnchor: [size / 2, size / 2] })
}

/** 事件链节点：编号圆徽章（关系色）。 */
export function nodeIcon(index: number, color: string): L.DivIcon {
  const html =
    `<div class="ky-node" style="--ky-c:${color}"><span>${index}</span></div>`
  return L.divIcon({ html, className: 'ky-marker', iconSize: [22, 22], iconAnchor: [11, 11] })
}

export function eventKind(eventType?: string | null): PinKind {
  const t = (eventType || '').toLowerCase()
  if (t === 'conflict' || t === 'military' || t === 'disaster' || t === 'political' ||
      t === 'economic' || t === 'social' || t === 'tech') {
    return t as PinKind
  }
  return 'other'
}

export function facilityKind(facilityType?: string | null): string {
  const t = (facilityType || '').toLowerCase()
  const map: Record<string, string> = {
    military_base: 'base',
    nuclear: 'nuclear',
    port: 'port',
    airport: 'airport',
    spaceport: 'spaceport',
    chokepoint: 'chokepoint',
  }
  return map[t] || 'base'
}

export function relationColor(relation?: string | null): string {
  const map: Record<string, string> = {
    cause: '#3b82f6',
    trigger: '#f97316',
    core: '#ef4444',
    consequence: '#eab308',
    response: '#22c55e',
  }
  return map[(relation || '').toLowerCase()] || '#a855f7'
}
