import { useEffect, useRef, useState } from 'react'

// 直播频道（对标 WM LiveNewsPanel, 2026-09-03）
// HLS 流抄 WM 实测清单——CGTN 系走国内 CDN 必达;
// YouTube 嵌入频道本机网络不可达, 留 geo 播放器字段待服务器环境启用。

interface LiveChannel {
  id: string
  name: string
  hlsUrl?: string          // 原生 HLS (hls.js 播放)
  youtubeId?: string       // YouTube 嵌入 fallback
  region: 'cn' | 'world'
  note?: string
}

export const LIVE_CHANNELS: LiveChannel[] = [
  // ── 中国 (CGTN 官方 HLS, 国内 CDN) ──
  { id: 'cgtn', name: 'CGTN 英语', region: 'cn', hlsUrl: 'https://news.cgtn.com/resource/live/english/cgtn-news.m3u8' },
  { id: 'cgtn-es', name: 'CGTN 西语', region: 'cn', hlsUrl: 'https://news.cgtn.com/resource/live/espanol/cgtn-e.m3u8' },
  { id: 'cgtn-ar', name: 'CGTN 阿语', region: 'cn', hlsUrl: 'https://news.cgtn.com/resource/live/arabic/cgtn-a.m3u8' },
  { id: 'cgtn-fr', name: 'CGTN 法语', region: 'cn', hlsUrl: 'https://news.cgtn.com/resource/live/french/cgtn-f.m3u8' },
  // ── 国际 (HLS 直连, WM 同款) ──
  { id: 'reuters-tv', name: 'Reuters TV', region: 'world', hlsUrl: 'https://reuters-reutersnow-1-eu.rakuten.wurl.tv/playlist.m3u8', note: '欧洲中继' },
  { id: 'aljazeera', name: 'Al Jazeera', region: 'world', youtubeId: 'gCNeDWCI0vo' },
  { id: 'dw', name: 'DW News', region: 'world', youtubeId: 'LuKwFajn37U' },
  { id: 'france24', name: 'France 24', region: 'world', youtubeId: 'u9foWyMSETk' },
]

export default function LiveTVPanel() {
  const [active, setActive] = useState<LiveChannel | null>(null)
  const [filter, setFilter] = useState<'all' | 'cn' | 'world'>('all')
  const [err, setErr] = useState('')
  const videoRef = useRef<HTMLVideoElement>(null)

  const channels = LIVE_CHANNELS.filter(c => filter === 'all' || c.region === filter)

  // 播放器: HLS → hls.js (Safari 原生支持)
  useEffect(() => {
    if (!active?.hlsUrl || !videoRef.current) return
    const video = videoRef.current
    setErr('')
    let hls: any = null
    let cancelled = false

    const start = async () => {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = active.hlsUrl!
        video.play().catch(() => setErr('浏览器阻止了自动播放——点击画面开声音'))
        return
      }
      const { default: Hls } = await import('hls.js')
      if (cancelled) return
      if (Hls.isSupported()) {
        hls = new Hls({ liveDurationInfinity: true, enableWorker: true })
        hls.loadSource(active.hlsUrl!)
        hls.attachMedia(video)
        hls.on(Hls.Events.ERROR, (_e: any, data: any) => {
          if (data.fatal) setErr(`流中断: ${data.details || '网络不可达'}`)
        })
        video.play().catch(() => setErr('浏览器阻止了自动播放——点击画面开声音'))
      } else {
        setErr('此浏览器不支持 HLS')
      }
    }
    start()
    return () => {
      cancelled = true
      if (hls) hls.destroy()
      video.pause()
      video.removeAttribute('src')
    }
  }, [active?.id])

  return (
    <div>
      {/* 频道筛选 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
        {([['all', '全部'], ['cn', '中国'], ['world', '国际']] as const).map(([k, label]) => (
          <button key={k} onClick={() => setFilter(k)}
            style={{ flex: 1, padding: '4px 0', fontSize: 11, borderRadius: 4, cursor: 'pointer',
              background: filter === k ? 'var(--accent)' : '#0d1330',
              color: filter === k ? '#fff' : 'var(--fg-dim)',
              border: '1px solid var(--border)' }}>
            {label}
          </button>
        ))}
      </div>

      {/* 播放器 */}
      {active && (
        <div style={{ marginBottom: 8, border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', background: '#000' }}>
          {active.hlsUrl ? (
            <video ref={videoRef} controls autoPlay muted playsInline
              style={{ width: '100%', aspectRatio: '16/9', display: 'block' }} />
          ) : active.youtubeId ? (
            <iframe
              src={`https://www.youtube.com/embed/${active.youtubeId}?autoplay=1&mute=1`}
              style={{ width: '100%', aspectRatio: '16/9', display: 'block', border: 'none' }}
              allow="autoplay; encrypted-media" />
          ) : null}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', background: 'var(--bg-card)' }}>
            <span className="live-dot" style={{ width: 6, height: 6 }} />
            <span style={{ fontSize: 11, flex: 1 }}>{active.name}</span>
            <button onClick={() => setActive(null)}
              style={{ background: 'none', border: 'none', color: 'var(--fg-dim)', cursor: 'pointer', fontSize: 13 }}>✕</button>
          </div>
          {err && <div style={{ fontSize: 10, color: 'var(--yellow)', padding: '2px 8px 6px' }}>⚠ {err}</div>}
        </div>
      )}

      {/* 频道网格 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {channels.map(c => (
          <button key={c.id} onClick={() => setActive(c)}
            style={{ padding: '8px 6px', borderRadius: 4, cursor: 'pointer', textAlign: 'left',
              background: active?.id === c.id ? 'var(--accent)' : '#0d1330',
              border: `1px solid ${active?.id === c.id ? 'var(--accent)' : 'var(--border)'}`,
              display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="live-dot" style={{ width: 5, height: 5, flexShrink: 0,
              background: c.region === 'cn' ? 'var(--green)' : 'var(--yellow)' }} />
            <span style={{ fontSize: 11, color: active?.id === c.id ? '#fff' : 'var(--fg)' }}>{c.name}</span>
          </button>
        ))}
      </div>
      <div style={{ fontSize: 9.5, color: 'var(--fg-dim)', marginTop: 8, lineHeight: 1.5 }}>
        CGTN 系官方 HLS 流（国内直连）；国际频道视网络环境，YouTube 源需外网。
        频道清单在 LiveTVPanel.tsx 顶部的 LIVE_CHANNELS 里维护。
      </div>
    </div>
  )
}
