import os
import sys
import time
import ctypes
import urllib.request
import threading
import webview
from server_quart import run_server

# ── Suppress pycrdt cross-thread Subscription drop noise ────────────────
# pycrdt's Rust-backed Subscription finalizer posts a RuntimeError through
# sys.unraisablehook when a Subscription is dropped on a thread different
# from its origin.  On Windows daemon threads, this happens at process exit
# after all application logic has completed.  The message is completely
# harmless — we suppress it here so it doesn't clutter stderr.
_original_unraisablehook = sys.unraisablehook

def _quiet_pycrdt_subscription(args):
    msg = str(args.exc_value) if args.exc_value else ''
    if 'Subscription' in msg and 'unsendable' in msg:
        return  # silently swallow
    _original_unraisablehook(args)

sys.unraisablehook = _quiet_pycrdt_subscription

PORT = 5000
W_WIDTH = 1000
W_HEIGHT = 680
_SERVER_URL = f'http://127.0.0.1:{PORT}'

user32 = ctypes.windll.user32
SCREEN_W = user32.GetSystemMetrics(0)
SCREEN_H = user32.GetSystemMetrics(1)
W_X = (SCREEN_W - W_WIDTH) // 2
W_Y = (SCREEN_H - W_HEIGHT) // 2

# ── Splash / error page (inline HTML, no external files needed) ─────────

_SPLASH_HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    background: #0d1117; color: #c9d1d9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    -webkit-app-region: drag; user-select: none;
  }
  .logo { font-size: 32px; margin-bottom: 24px; }
  .spinner {
    width: 28px; height: 28px; margin-bottom: 16px;
    border: 3px solid rgba(255,255,255,0.1);
    border-top-color: #58a6ff; border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .msg { font-size: 13px; color: #8b949e; }
</style>
</head>
<body>
  <div class="logo">⚡</div>
  <div class="spinner"></div>
  <div class="msg">正在启动服务…</div>
</body>
</html>'''

_ERROR_HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    background: #0d1117; color: #c9d1d9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    -webkit-app-region: drag; user-select: none;
  }
  .icon { font-size: 48px; margin-bottom: 16px; }
  h1 { font-size: 18px; font-weight: 600; margin-bottom: 8px; color: #f0f6fc; }
  p { font-size: 13px; color: #8b949e; margin-bottom: 20px; text-align: center; line-height: 1.5; }
  button {
    padding: 8px 24px; border: 1px solid #30363d; border-radius: 6px;
    background: #21262d; color: #c9d1d9; font-size: 13px;
    cursor: pointer; -webkit-app-region: no-drag; transition: background 0.15s;
  }
  button:hover { background: #30363d; }
</style>
</head>
<body>
  <div class="icon">🔌</div>
  <h1>服务连接中断</h1>
  <p>ZaoWu 后台服务似乎已停止运行。<br>请尝试重新启动应用。</p>
  <button onclick="location.reload()">重新连接</button>
</body>
</html>'''


# ── Helpers ─────────────────────────────────────────────────────────────

def _wait_for_server(port: int, timeout: float = 30.0) -> bool:
    """Poll the health endpoint until the server responds or timeout."""
    url = f'http://127.0.0.1:{port}/api/health'
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


class Api:
    def minimize(self):
        webview.windows[0].minimize()

    def maximize(self):
        webview.windows[0].maximize()

    def restore(self):
        webview.windows[0].restore()

    def move(self, x, y):
        webview.windows[0].move(x, y)

    def shutdown(self):
        os._exit(0)

    def select_folder(self):
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.FOLDER,
            allow_multiple=False,
        )
        if result and len(result) > 0:
            return result[0]
        return None


def _on_loaded(window):
    """Called after each page finishes loading. Injects error detection."""
    # Check if the loaded page is a Chromium error page (net::ERR_*).
    # Error pages have no real content — detect by checking for the
    # absence of the ZaoWu app's root element.
    js = r'''
    (function() {
      // If the page is a real ZaoWu app page, it will have #app
      if (document.getElementById('app')) return 'ok';
      // Chromium error pages have a specific structure
      if (document.body && document.body.innerText.includes('ERR_')) return 'error';
      if (document.body && document.body.innerText.includes('refused')) return 'error';
      return 'unknown';
    })();
    '''
    try:
        result = window.evaluate_js(js)
        if result == 'error':
            window.load_html(_ERROR_HTML)
    except Exception:
        pass


if __name__ == '__main__':
    # PyWebView must own the main thread so its Windows message pump works.
    # The asyncio server runs in a *daemon* thread — on Windows this means
    # signal handlers are not available, so we configure Hypercorn to skip them.

    server_thread = threading.Thread(target=run_server, args=(PORT,), daemon=True)
    server_thread.start()

    # Show a splash screen while the server starts up, then switch to the app.
    window = webview.create_window(
        'ZaoWu',
        html=_SPLASH_HTML,
        width=W_WIDTH,
        height=W_HEIGHT,
        x=W_X,
        y=W_Y,
        min_size=(760, 500),
        resizable=True,
        frameless=True,
        easy_drag=False,
        shadow=True,
        js_api=Api(),
    )

    def _on_shown():
        """Switch from splash to the real app once the server is ready."""
        if _wait_for_server(PORT, timeout=30):
            window.load_url(_SERVER_URL)
        else:
            window.load_html(_ERROR_HTML)

    window.events.shown += _on_shown
    window.events.loaded += lambda: _on_loaded(window)

    webview.start()
    os._exit(0)
