import os
import sys
import ctypes
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

user32 = ctypes.windll.user32
SCREEN_W = user32.GetSystemMetrics(0)
SCREEN_H = user32.GetSystemMetrics(1)
W_X = (SCREEN_W - W_WIDTH) // 2
W_Y = (SCREEN_H - W_HEIGHT) // 2


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
            webview.FOLDER_DIALOG,
            allow_multiple=False,
        )
        if result and len(result) > 0:
            return result[0]
        return None


if __name__ == '__main__':
    # PyWebView must own the main thread so its Windows message pump works.
    # The asyncio server runs in a *daemon* thread — on Windows this means
    # signal handlers are not available, so we configure Hypercorn to skip them.

    server_thread = threading.Thread(target=run_server, args=(PORT,), daemon=True)
    server_thread.start()

    window = webview.create_window(
        'ZaoWu',
        f'http://127.0.0.1:{PORT}',
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
    webview.start()
    os._exit(0)
