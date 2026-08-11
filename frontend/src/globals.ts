// Must use IIFE — otherwise Vite tree-shakes window assignments.
// These are called from Leaflet popup onclick="" raw HTML.

(function() {
  const w = window as any
  w.loadEventItems = function(eventId: string) {
    const el = document.getElementById('evt-items-' + eventId)
    if (!el) return
    el.innerHTML = '<small style="color:#64748b">loading...</small>'
    fetch('/api/events/' + eventId + '/items').then(r => r.json()).then(d => {
      let h = ''
      d.items.slice(0, 5).forEach((i: any) => {
        h += '<div style="font-size:11px">&bull; <a href="' + i.url + '" target="_blank" style="color:#60a5fa">' + (i.title||'').substring(0,60) + '</a></div>'
      })
      if (d.items.length > 5) h += '<div style="color:#64748b;font-size:10px">...' + d.items.length + ' articles</div>'
      el.innerHTML = h
    }).catch(() => { el.innerHTML = '<small style="color:#ef4444">load failed</small>' })
  }

  w.tianshuPopup = function(title: string) {
    const popup = window.open('', '_blank', 'width=800,height=600')
    if (!popup) return
    const query = decodeURIComponent(title)
    popup.document.write('<body style="font-family:sans-serif;padding:20px;background:#0a0e27;color:#c9d1d9"><h2 style="color:#e2c860">Tianshu</h2><p>' + query + '</p><p style="color:#64748b">Connecting...</p>')
    fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: '请搜索: ' + query }) })
      .then(r => r.json()).then(d => {
        popup.document.body.innerHTML = '<div style="max-width:700px;margin:0 auto"><h2 style="color:#e2c860">Tianshu</h2><pre style="white-space:pre-wrap;font-size:14px;line-height:1.6">' + (d.reply||'empty') + '</pre></div>'
      }).catch(() => { popup.document.body.innerHTML = '<p style="color:#ef4444">Connection failed</p>' })
  }
})()
