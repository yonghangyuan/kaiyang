import { useEffect, useRef, useState } from 'react'

// 直播频道（对标 WM LiveNewsPanel, 2026-09-03 修订）
//
// 第一版用 CGTN 官方 HLS——主清单可达但二级域名 live.cgtn.com DNS 不通, 播不了。
// 实测本机网络环境真正稳定的路径是 B 站直播转播房(央视新闻/CGTN 官方及授权转播,
// h5 嵌入端点 6KB 轻量页, 浏览器端有用户 cookie 即可播)。
//
// 频道类型: bilibili(iframe h5 嵌入, 国内必达) / hls(m3u8 直连, 视网络) /
// youtube(嵌入, 需外网)。清单在 LIVE_CHANNELS 维护。

interface LiveChannel {
  id: string
  name: string
  type: 'bilibili' | 'hls' | 'youtube'
  room?: string        // bilibili 房间号
  hlsUrl?: string      // HLS 清单
  youtubeId?: string
  region: 'cn' | 'world'
  live?: boolean       // 搜索时实测的开播状态(展示参考)
}

export const LIVE_CHANNELS: LiveChannel[] = [
  // ── 中国 (B站转播房, 实测 live=1) ──
  { id: 'cctv13', name: '央视新闻频道', type: 'bilibili', room: '8178490', region: 'cn' },
  { id: 'cctv-news-2', name: '总台新闻(二路)', type: 'bilibili', room: '21623527', region: 'cn' },
  { id: 'cctv-news-3', name: '总台新闻(三路)', type: 'bilibili', room: '22142427', region: 'cn' },
  // ── CGTN 官方 HLS(主清单可达, 二级域名视网络——不通时换B站路) ──
  { id: 'cgtn', name: 'CGTN 英语', type: 'hls', region: 'cn', hlsUrl: 'https://news.cgtn.com/resource/live/english/cgtn-news.m3u8' },
  { id: 'cgtn-es', name: 'CGTN 西语', type: 'hls', region: 'cn', hlsUrl: 'https://news.cgtn.com/resource/live/espanol/cgtn-e.m3u8' },
  // ── 国际 (YouTube 嵌入, 需外网) ──
  { id: 'aljazeera', name: 'Al Jazeera', type: 'youtube', youtubeId: 'gCNeDWCI0vo', region: 'world' },
  { id: 'dw', name: 'DW News', type: 'youtube', youtubeId: 'LuKwFajn37U', region: 'world' },
  { id: 'france24', name: 'France 24', type: 'youtube', youtubeId: 'u9foWyMSETk', region: 'world' },
]

export default function LiveTVPanel() {
  const [active, setActive] = useState<LiveChannel | null>(null)
  const [filter, setFilter] = useState<'all' | 'cn' | 'world'>('all')
  const [err, setErr] = useState('')
  const videoRef = useRef<HTMLVideoElement>(null)

  const channels = LIVE_CHANNELS.filter(c => filter === 'all' || c.region === filter)

  // HLS 播放 (仅 hls 类型走 hls.js; bilibili/youtube 是 iframe 不需要)
  useEffect(() => {
    if (active?.type !== 'hls' || !videoRef.current) return
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
          if (data.fatal) setErr(`流中断: ${data.details || '网络不可达——此流的二级域名可能被阻断, 换 B 站频道'}`)
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

  const typeColor: Record<string, string> = {
    bilibili: 'var(--green)', hls: '#38bdf8', youtube: '#ef4444',
  }
  const typeLabel: Record<string, string> = {
    bilibili: 'B站', hls: 'HLS', youtube: 'YT',
  }

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
          {active.type === 'hls' && (
            <video ref={videoRef} controls autoPlay muted playsInline
              style={{ width: '100%', aspectRatio: '16/9', display: 'block' }} />
          )}
          {active.type === 'bilibili' && active.room && (
            <iframe
              src={`https://live.bilibili.com/h5/${active.room}`}
              style={{ width: '100%', aspectRatio: '16/9', display: 'block', border: 'none' }}
              allow="autoplay; fullscreen; encrypted-media" />
          )}
          {active.type === 'youtube' && active.youtubeId && (
            <iframe
              src={`https://www.youtube.com/embed/${active.youtubeId}?autoplay=1&mute=1`}
              style={{ width: '100%', aspectRatio: '16/9', display: 'block', border: 'none' }}
              allow="autoplay; encrypted-media" />
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', background: 'var(--bg-card)' }}>
            <span className="live-dot" style={{ width: 6, height: 6 }} />
            <span style={{ fontSize: 11, flex: 1 }}>{active.name}</span>
            <span style={{ fontSize: 9, color: typeColor[active.type], border: `1px solid ${typeColor[active.type]}`, borderRadius: 3, padding: '0 4px' }}>{typeLabel[active.type]}</span>
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
            <span style={{ fontSize: 11, flex: 1, color: active?.id === c.id ? '#fff' : 'var(--fg)' }}>{c.name}</span>
            <span style={{ fontSize: 8.5, color: typeColor[c.type], opacity: 0.8 }}>{typeLabel[c.type]}</span>
          </button>
        ))}
      </div>
      <div style={{ fontSize: 9.5, color: 'var(--fg-dim)', marginTop: 8, lineHeight: 1.5 }}>
        B站路=国内必达（央视新闻频道转播）；HLS=CGTN官方流（二级域名视网络）；
        YT=需外网。换台即换 iframe，多路同开可比较叙事差异。
      </div>
    </div>
  )
}
