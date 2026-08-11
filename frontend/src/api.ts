// 开阳 (Kaiyang) — API 客户端。
// 参考 MediaCrawler webui/src/lib/ 模式: 集中管理所有 API 调用。

const BASE = ''

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + url, init)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export interface Source { id: string; name: string; type: string; status: string; credibility_tier: number; last_fetch_at?: string }
export interface GeoPoint { id: string; title: string; lat: number; lng: number; country_code?: string; severity?: number; confidence?: number; source_count?: number; time_start?: string; published_at?: string; type?: string; url?: string }
export interface Briefing { query: string; summary: string; point_count: number; timeline_count: number; web_count?: number; points: GeoPoint[]; timeline: any[] }
export interface Annotation { id: string; name: string; description?: string; type: string; coordinates: any; style?: any }
export interface Stats { sources: number; intel: number; events: number; entities: number }

export const api = {
  health: () => fetchJson<any>('/health'),
  sources: () => fetchJson<{count:number; sources:Source[]}>('/api/sources'),
  stats: async (): Promise<Stats> => {
    const [s,i,e,ent] = await Promise.all([
      fetchJson<{count:number}>('/api/sources'),
      fetchJson<{total:number}>('/api/intel?limit=1'),
      fetchJson<{count:number}>('/api/events?limit=1'),
      fetchJson<{total:number}>('/api/entities/stats/summary'),
    ])
    return {sources:s.count, intel:i.total, events:e.count, entities:ent.total}
  },
  events: (limit=100) => fetchJson<{count:number; points:GeoPoint[]}>('/api/map/plot', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit})}),
  search: (query:string, limit=30) => fetchJson<Briefing>('/api/search/briefing', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,limit})}),
  chat: (message:string) => fetchJson<{reply:string; model?:string; decision_id?:string; error?:boolean}>('/api/chat', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})}),
  annotations: {
    list: () => fetchJson<{count:number; annotations:Annotation[]}>('/api/annotations'),
    fromText: (text:string) => fetchJson<any>('/api/annotations/from-text', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})}),
    delete: (id:string) => fetch('/api/annotations/'+id, {method:'DELETE'}),
    clear: () => fetch('/api/annotations', {method:'DELETE'}),
  },
}
