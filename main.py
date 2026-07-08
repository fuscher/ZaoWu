import os
import ctypes
import threading
import webview
from server import run_server

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


def start_server():
    run_server(port=PORT)


if __name__ == '__main__':
    server_thread = threading.Thread(target=start_server, daemon=True)
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
