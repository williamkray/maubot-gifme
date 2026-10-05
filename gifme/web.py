import html
import json
import urllib.parse

# matrix-widget-api UMD build, version-pinned. This browserify UMD exposes `window.mxwidgets`
# as a THUNK function — you must call it (`mxwidgets()`) to get the namespace holding WidgetApi.
# The JS below handles that (and the plain-namespace shape, in case a future build changes).
# For production, consider adding an SRI integrity hash or vendoring the file.
WIDGET_API_SRC = "https://unpkg.com/matrix-widget-api@1.20.0/dist/api.min.js"


def mxc_to_proxy_url(base: str, mxc: str, token: str) -> str:
    """Convert an mxc:// URI to a proxied HTTP URL with a session token."""
    if mxc.startswith("mxc://"):
        server_media = mxc[6:]
        server, _, media_id = server_media.partition("/")
        return f"{base}/media/{server}/{media_id}?t={urllib.parse.quote(token)}"
    return ""


def render_style_css() -> str:
    """Return a complete CSS stylesheet for the gifme gallery."""
    return """\
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  background: #1a1a2e;
  color: #e0e0e0;
  line-height: 1.5;
  min-height: 100dvh;
}

a { color: #7aa2f7; text-decoration: none; }
a:hover { text-decoration: underline; }

/* top bar */
.gifme-topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: #16213e;
  border-bottom: 1px solid #2d3561;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.gifme-topbar form {
  display: flex;
  gap: 6px;
  flex: 1;
  max-width: 640px;
}

.gifme-topbar input[type="text"] {
  flex: 1;
  background: #1a1a2e;
  border: 1px solid #2d3561;
  border-radius: 6px;
  color: #e0e0e0;
  font: inherit;
  font-size: 0.9rem;
  padding: 6px 10px;
  outline: none;
}

.gifme-topbar input[type="text"]:focus {
  border-color: #7aa2f7;
}

.gifme-topbar button[type="submit"] {
  background: #3d5afe;
  border: none;
  border-radius: 6px;
  color: #fff;
  cursor: pointer;
  font: inherit;
  font-size: 0.9rem;
  padding: 6px 14px;
}

.gifme-topbar button[type="submit"]:hover { background: #536dfe; }

/* gallery grid */
.gifme-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  padding: 16px;
}

/* card */
.gifme-card {
  background: #16213e;
  border: 1px solid #2d3561;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.gifme-card img,
.gifme-card video {
  width: 100%;
  height: auto;
  display: block;
  background: #0f3460;
}

/* text entries */
.gifme-quote {
  border-left: 3px solid #7aa2f7;
  color: #c0c0d0;
  font-size: 0.9rem;
  font-style: italic;
  line-height: 1.5;
  margin: 0;
  padding: 10px 12px;
  word-wrap: break-word;
  overflow-wrap: break-word;
}

/* card metadata */
.gifme-card .meta {
  font-size: 0.78rem;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
}

.gifme-card .meta .tags {
  color: #a0aec0;
  word-break: break-word;
}

.gifme-card .meta .sub {
  color: #606880;
  font-size: 0.72rem;
}

/* send button */
.gifme-send {
  background: #3d5afe;
  border: none;
  border-radius: 0 0 9px 9px;
  color: #fff;
  cursor: pointer;
  font: inherit;
  font-size: 0.85rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  padding: 8px 0;
  text-align: center;
  width: 100%;
  transition: background 0.15s;
}

.gifme-send:hover:not(:disabled) { background: #536dfe; }
.gifme-send:disabled { opacity: 0.6; cursor: default; }

/* pager */
.pager {
  align-items: center;
  display: flex;
  font-size: 0.875rem;
  gap: 12px;
  justify-content: center;
  padding: 20px 16px 32px;
}

.pager a {
  background: #16213e;
  border: 1px solid #2d3561;
  border-radius: 6px;
  color: #7aa2f7;
  padding: 6px 14px;
}

.pager a:hover {
  background: #1e2a50;
  text-decoration: none;
}

.pager .page-info {
  color: #606880;
}

/* tabs */
.gifme-tabs {
  display: flex;
  gap: 4px;
}

.gifme-tab {
  background: #1a1a2e;
  border: 1px solid #2d3561;
  border-radius: 6px;
  color: #a0aec0;
  cursor: pointer;
  font: inherit;
  font-size: 0.85rem;
  padding: 6px 12px;
}

.gifme-tab:hover { background: #1e2a50; }
.gifme-tab.active { background: #3d5afe; color: #fff; border-color: #3d5afe; }

/* live-search status line */
#live-status {
  color: #a0aec0;
  font-size: 0.9rem;
  padding: 16px;
  text-align: center;
}
"""


def render_card_html(view: dict, widget: bool) -> str:
    """Render one gallery card as an HTML string."""
    msgtype = view["msgtype"]
    media_url = view["media_url"]
    mxc = view["mxc"]
    mime = view["mime"]
    w = view["w"]
    h = view["h"]
    size = view["size"]
    filename = view["filename"]
    body = view["body"]
    formatted_body = view["formatted_body"]
    sender = view["sender"]
    tags = view["tags"]
    source = view["source"]

    # media block
    if msgtype == "image":
        media_html = (
            f'<img loading="lazy"'
            f' src="{html.escape(media_url)}"'
            f' alt="{html.escape(filename)}">'
        )
    elif msgtype == "video":
        media_html = (
            f'<video controls preload="metadata"'
            f' src="{html.escape(media_url)}"></video>'
        )
    else:
        # text: render the escaped plain-text body. We deliberately do NOT insert the
        # stored formatted_body as raw HTML — it is attacker-controlled (any room member
        # can save a quote) and the viewer's session token is in the URL, so raw HTML
        # would be a stored-XSS / token-exfiltration vector. Rich formatting is dropped
        # on purpose for safety. `formatted_body` is intentionally unused here.
        media_html = f'<blockquote class="gifme-quote">{html.escape(body)}</blockquote>'

    # meta block
    sub_parts = [p for p in (html.escape(source), html.escape(sender)) if p]
    sub_html = (
        f'<div class="sub">{" · ".join(sub_parts)}</div>'
        if sub_parts else ""
    )
    meta_html = (
        f'<div class="meta">'
        f'<div class="tags">{html.escape(tags)}</div>'
        f'{sub_html}'
        f'</div>'
    )

    # optional send button
    button_html = ""
    if widget:
        btn_body = html.escape(filename or body)
        button_html = (
            f'<button class="gifme-send"'
            f' data-msgtype="{html.escape(msgtype)}"'
            f' data-mxc="{html.escape(mxc)}"'
            f' data-mime="{html.escape(mime)}"'
            f' data-w="{html.escape(str(w or ""))}"'
            f' data-h="{html.escape(str(h or ""))}"'
            f' data-size="{html.escape(str(size or ""))}"'
            f' data-body="{btn_body}"'
            f'>Send to room</button>'
        )

    return (
        f'<div class="gifme-card">'
        f'{media_html}'
        f'{meta_html}'
        f'{button_html}'
        f'</div>'
    )


def render_gallery_html(
    *,
    base: str,
    token: str,
    q: str,
    page: int,
    total_pages: int,
    cards_html: str,
    widget: bool,
    widget_id: str = "",
    parent_url: str = "",
    live_providers: list = None,
) -> str:
    """Return a complete HTML5 gallery document."""

    # stylesheet link
    base_esc = html.escape(base)
    stylesheet = f'<link rel="stylesheet" href="{base_esc}/style.css">'

    # search form. In widget mode we must carry widgetId + parentUrl through every
    # navigation (form submit, pager links) so the reloaded page's WidgetApi keeps the
    # client-assigned widgetId — otherwise send_event times out on a widgetId mismatch.
    q_esc = html.escape(q)
    token_esc = html.escape(token)
    hidden_inputs = ""
    if widget:
        hidden_inputs += '<input type="hidden" name="widget" value="1">'
        if widget_id:
            hidden_inputs += f'<input type="hidden" name="widgetId" value="{html.escape(widget_id)}">'
        if parent_url:
            hidden_inputs += f'<input type="hidden" name="parentUrl" value="{html.escape(parent_url)}">'
    form_html = (
        f'<form action="{base_esc}/" method="get">'
        f'<input type="text" name="q" value="{q_esc}" placeholder="search tags…">'
        f'<input type="hidden" name="t" value="{token_esc}">'
        f'{hidden_inputs}'
        f'<button type="submit">Search</button>'
        f'</form>'
    )
    # live-search tabs (widget mode only, for providers with a proxy + api key)
    tabs_html = ""
    if widget and live_providers:
        labels = {"giphy": "Giphy", "klipy": "Klipy"}
        buttons = ['<button type="button" class="gifme-tab active" data-tab="archive">Archive</button>']
        for p in live_providers:
            buttons.append(
                f'<button type="button" class="gifme-tab" data-tab="{html.escape(p)}">'
                f'{html.escape(labels.get(p, p.title()))}</button>'
            )
        tabs_html = f'<div class="gifme-tabs">{"".join(buttons)}</div>'
    topbar_html = f'<div class="gifme-topbar">{tabs_html}{form_html}</div>'

    # pager
    def page_url(target_page: int) -> str:
        params: dict[str, str] = {"t": token}
        if q:
            params["q"] = q
        if target_page != 1:
            params["page"] = str(target_page)
        if widget:
            params["widget"] = "1"
            if widget_id:
                params["widgetId"] = widget_id
            if parent_url:
                params["parentUrl"] = parent_url
        return f"{base}/?" + urllib.parse.urlencode(params)

    pager_parts: list[str] = []
    if page > 1:
        pager_parts.append(f'<a href="{html.escape(page_url(page - 1))}">← prev</a>')
    pager_parts.append(f'<span class="page-info">page {page} of {total_pages}</span>')
    if page < total_pages:
        pager_parts.append(f'<a href="{html.escape(page_url(page + 1))}">next →</a>')
    pager_html = f'<div class="pager">{"".join(pager_parts)}</div>'

    # widget script block
    if widget:
        widget_js = """\
(function(){
  if (window.parent === window) {
    document.querySelectorAll('.gifme-send').forEach(function(b){ b.style.display='none'; });
    return;
  }
  var q = new URLSearchParams(window.location.search);
  var widgetId = q.get('widgetId') || 'gifme';
  var parentUrl = q.get('parentUrl');
  var base = (typeof GIFME_BASE !== 'undefined') ? GIFME_BASE : '';
  var token = (typeof GIFME_TOKEN !== 'undefined') ? GIFME_TOKEN : (q.get('t') || '');
  var origin = '*';
  try { if (parentUrl) origin = new URL(parentUrl).origin; } catch (e) {}
  var NS = mxwidgets; if (typeof NS === 'function' && !NS.WidgetApi) NS = NS();
  var api = new NS.WidgetApi(widgetId, origin);
  // MSC2762 scopes m.room.message send capability by msgtype, so request each
  // msgtype we actually send (m.room.message alone is rejected as "events of this type").
  api.requestCapabilityToSendMessage('m.image');
  api.requestCapabilityToSendMessage('m.video');
  api.requestCapabilityToSendMessage('m.notice');
  api.start();

  function wireSend(btn){
    btn.addEventListener('click', function(){
      var content;
      if (btn.dataset.msgtype === 'text') {
        content = { msgtype: 'm.notice', body: btn.dataset.body || '' };
      } else {
        var info = {};
        if (btn.dataset.mime) info.mimetype = btn.dataset.mime;
        if (btn.dataset.w) info.w = parseInt(btn.dataset.w, 10);
        if (btn.dataset.h) info.h = parseInt(btn.dataset.h, 10);
        if (btn.dataset.size) info.size = parseInt(btn.dataset.size, 10);
        content = {
          msgtype: btn.dataset.msgtype === 'video' ? 'm.video' : 'm.image',
          body: btn.dataset.body || 'gif',
          url: btn.dataset.mxc,
          info: info
        };
      }
      var original = btn.textContent;
      btn.disabled = true; btn.textContent = 'Sending…';
      api.sendRoomEvent('m.room.message', content).then(function(){
        btn.textContent = 'Sent ✓';
        setTimeout(function(){ btn.disabled = false; btn.textContent = original; }, 2000);
      }).catch(function(e){
        console.error('gifme send failed', e);
        btn.textContent = 'Failed'; btn.disabled = false;
      });
    });
  }
  document.querySelectorAll('.gifme-send').forEach(wireSend);

  // ---- tabs + live search ----
  var tabs = document.querySelectorAll('.gifme-tab');
  if (tabs.length) {
    var archiveView = document.getElementById('archive-view');
    var liveView = document.getElementById('live-view');
    var liveGrid = document.getElementById('live-grid');
    var liveStatus = document.getElementById('live-status');
    var form = document.querySelector('.gifme-topbar form');
    var input = form ? form.querySelector('input[name="q"]') : null;
    var active = 'archive';
    var liveSeq = 0;

    function renderLiveCard(g){
      var card = document.createElement('div');
      card.className = 'gifme-card';
      var img = document.createElement('img');
      img.loading = 'lazy';
      img.src = g.preview;
      img.alt = g.filename || 'gif';
      card.appendChild(img);
      var btn = document.createElement('button');
      btn.className = 'gifme-send';
      btn.type = 'button';
      btn.textContent = 'Send to room';
      btn.dataset.msgtype = g.msgtype || 'image';
      btn.dataset.mxc = g.mxc || '';
      btn.dataset.mime = g.mime || '';
      btn.dataset.w = g.w || '';
      btn.dataset.h = g.h || '';
      btn.dataset.size = g.size || '';
      btn.dataset.body = g.filename || 'gif';
      card.appendChild(btn);
      wireSend(btn);
      return card;
    }

    function liveSearch(provider, query){
      if (!query) { liveGrid.innerHTML = ''; liveStatus.textContent = 'Type a search above and hit Search.'; return; }
      var seq = ++liveSeq;
      liveStatus.textContent = 'Searching…';
      liveGrid.innerHTML = '';
      fetch(base + '/search/' + provider + '?q=' + encodeURIComponent(query) + '&t=' + encodeURIComponent(token))
        .then(function(r){ if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function(d){
          if (seq !== liveSeq) return;
          var res = (d && d.results) || [];
          if (!res.length) { liveStatus.textContent = 'No results.'; return; }
          liveStatus.textContent = '';
          var frag = document.createDocumentFragment();
          res.forEach(function(g){ frag.appendChild(renderLiveCard(g)); });
          liveGrid.appendChild(frag);
        })
        .catch(function(e){
          if (seq !== liveSeq) return;
          console.error('gifme live search failed', e);
          liveStatus.textContent = 'Search failed.';
        });
    }

    function setActive(tab){
      active = tab;
      tabs.forEach(function(t){ t.classList.toggle('active', t.dataset.tab === tab); });
      if (tab === 'archive') {
        if (archiveView) archiveView.style.display = '';
        if (liveView) liveView.style.display = 'none';
      } else {
        if (archiveView) archiveView.style.display = 'none';
        if (liveView) liveView.style.display = '';
        liveSearch(tab, input ? input.value.trim() : '');
      }
    }

    tabs.forEach(function(t){ t.addEventListener('click', function(){ setActive(t.dataset.tab); }); });

    if (form) {
      form.addEventListener('submit', function(e){
        if (active !== 'archive') { e.preventDefault(); liveSearch(active, input ? input.value.trim() : ''); }
      });
    }
  }
})();"""
        widget_api_src_esc = html.escape(WIDGET_API_SRC)
        widget_cfg = f"var GIFME_BASE={json.dumps(base)};var GIFME_TOKEN={json.dumps(token)};"
        script_block = (
            f'<script src="{widget_api_src_esc}"></script>\n'
            f'<script>{widget_cfg}\n{widget_js}</script>'
        )
    else:
        script_block = ""

    archive_html = (
        f'<div id="archive-view">\n'
        f'<div class="gifme-grid">{cards_html}</div>\n'
        f'{pager_html}\n'
        f'</div>'
    )
    if widget and live_providers:
        live_html = (
            '<div id="live-view" style="display:none">\n'
            '<div id="live-status"></div>\n'
            '<div class="gifme-grid" id="live-grid"></div>\n'
            '</div>'
        )
    else:
        live_html = ""

    return (
        f'<!DOCTYPE html>\n'
        f'<html lang="en">\n'
        f'<head>\n'
        f'<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>gifme archive</title>\n'
        f'{stylesheet}\n'
        f'</head>\n'
        f'<body>\n'
        f'{topbar_html}\n'
        f'{archive_html}\n'
        f'{live_html}\n'
        f'{script_block}'
        f'</body>\n'
        f'</html>'
    )


def render_bootstrap_html(*, base: str) -> str:
    """Return a minimal HTML document for the /widget route that performs the OpenID handshake."""
    base_js = json.dumps(base)  # JSON-encode so any quotes in base are safe in JS string context
    widget_api_src_esc = html.escape(WIDGET_API_SRC)

    bootstrap_js = f"""\
(function(){{
  var BASE = {base_js};
  var q = new URLSearchParams(window.location.search);
  var widgetId = q.get('widgetId') || 'gifme';
  var roomId = q.get('roomId') || q.get('matrix_room_id') || '';
  function fail(m){{ document.getElementById('status').textContent = m; }}
  if (window.parent === window) {{ fail('Open this page inside a Matrix client as a widget.'); return; }}
  var parentUrl = q.get('parentUrl');
  var origin = '*';
  try {{ if (parentUrl) origin = new URL(parentUrl).origin; }} catch (e) {{}}
  var NS = mxwidgets; if (typeof NS === 'function' && !NS.WidgetApi) NS = NS();
  var api = new NS.WidgetApi(widgetId, origin);
  api.start();
  api.requestOpenIDConnectToken().then(function(tok){{
    return fetch(BASE + '/widget/auth', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        openid_token: tok.access_token,
        matrix_server_name: tok.matrix_server_name,
        room_id: roomId
      }})
    }});
  }}).then(function(r){{ return r.json(); }}).then(function(d){{
    if (d && d.token) {{
      var url = BASE + '/?t=' + encodeURIComponent(d.token) + '&widget=1';
      if (roomId) url += '&roomId=' + encodeURIComponent(roomId);
      // Preserve the client-assigned widgetId and parentUrl across the redirect so the
      // gallery page's WidgetApi uses the SAME widgetId the client knows (otherwise the
      // postMessage handshake/capabilities/send all time out on a widgetId mismatch).
      if (widgetId) url += '&widgetId=' + encodeURIComponent(widgetId);
      if (parentUrl) url += '&parentUrl=' + encodeURIComponent(parentUrl);
      window.location.replace(url);
    }} else {{
      fail('Authentication failed: ' + ((d && d.error) || 'unknown error'));
    }}
  }}).catch(function(e){{ fail('Could not authenticate with Matrix: ' + e); }});
}})();"""

    return (
        f'<!DOCTYPE html>\n'
        f'<html lang="en">\n'
        f'<head>\n'
        f'<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>gifme</title>\n'
        f'<style>\n'
        f'body {{\n'
        f'  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;\n'
        f'  background: #1a1a2e;\n'
        f'  color: #e0e0e0;\n'
        f'  display: flex;\n'
        f'  align-items: center;\n'
        f'  justify-content: center;\n'
        f'  min-height: 100dvh;\n'
        f'  margin: 0;\n'
        f'}}\n'
        f'#status {{\n'
        f'  font-size: 1rem;\n'
        f'  color: #a0aec0;\n'
        f'  text-align: center;\n'
        f'  padding: 24px;\n'
        f'}}\n'
        f'</style>\n'
        f'</head>\n'
        f'<body>\n'
        f'<div id="status">Authenticating with Matrix…</div>\n'
        f'<script src="{widget_api_src_esc}"></script>\n'
        f'<script>{bootstrap_js}</script>\n'
        f'</body>\n'
        f'</html>'
    )


def render_message_html(*, title: str, message: str) -> str:
    """Return a minimal complete HTML page for errors (401, expired session, etc.)."""
    title_esc = html.escape(title)
    message_esc = html.escape(message)
    return (
        f'<!DOCTYPE html>\n'
        f'<html lang="en">\n'
        f'<head>\n'
        f'<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{title_esc}</title>\n'
        f'<style>\n'
        f'body {{\n'
        f'  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;\n'
        f'  background: #1a1a2e;\n'
        f'  color: #e0e0e0;\n'
        f'  display: flex;\n'
        f'  align-items: center;\n'
        f'  justify-content: center;\n'
        f'  min-height: 100dvh;\n'
        f'  margin: 0;\n'
        f'}}\n'
        f'.gifme-msg {{\n'
        f'  text-align: center;\n'
        f'  padding: 32px;\n'
        f'}}\n'
        f'.gifme-msg h1 {{\n'
        f'  font-size: 1.4rem;\n'
        f'  margin-bottom: 12px;\n'
        f'  color: #e0e0e0;\n'
        f'}}\n'
        f'.gifme-msg p {{\n'
        f'  color: #a0aec0;\n'
        f'  font-size: 0.95rem;\n'
        f'}}\n'
        f'</style>\n'
        f'</head>\n'
        f'<body>\n'
        f'<div class="gifme-msg">\n'
        f'<h1>{title_esc}</h1>\n'
        f'<p>{message_esc}</p>\n'
        f'</div>\n'
        f'</body>\n'
        f'</html>'
    )
