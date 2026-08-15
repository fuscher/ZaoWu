"""模拟 frozen 应用入口：复现 PyInstaller bootloader 语义后启动真实后端。

由 fakeapp（python-server 模式）拉起的子进程；父进程被杀时经 watchdog
同步退出，模拟「应用进程」整体消亡。绑定失败时进程存活（daemon 线程
已死），与真实应用展示错误页的形态一致。
"""

import os
import subprocess
import sys
import threading
import time

# 仓库根入 sys.path（子进程 cwd 是版本目录，无法靠相对导入找到后端包）
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

root = os.environ['ZAOWU_SIM_ROOT']
# 自定位：exe 路径由拉起方（fakeapp）注入，版本号从自身路径推导——
# 无论被启动器还是模拟驱动器拉起，进程都知道自己是哪个版本。
exe = os.environ['ZAOWU_SIM_EXE']
version = os.path.basename(os.path.dirname(exe))


def watchdog(parent_pid):
    debug_log = os.environ.get('ZAOWU_SIM_WATCHDOG_LOG')
    while True:
        time.sleep(1)
        out = subprocess.run(
            ['tasklist', '/FI', f'PID eq {parent_pid}', '/FO', 'CSV', '/NH'],
            capture_output=True,
            text=True,
        ).stdout
        if debug_log:
            with open(debug_log, 'a', encoding='utf-8') as f:
                f.write(f"parent={parent_pid} out={out!r} contains={'ZaoWu.exe' in out}\n")
        if 'ZaoWu.exe' not in out:
            os._exit(0)


# 追踪 fakeapp（应用进程）而非直接父进程：venv 重定向器会使直接父进程是
# python.exe；fakeapp 被启动器定向终止时，此处随之同步退出。
_parent_pid = int(os.environ.get('ZAOWU_SIM_PARENT_PID') or os.getppid())
threading.Thread(target=watchdog, args=(_parent_pid,), daemon=True).start()

# PyInstaller bootloader 语义：frozen 标志 + executable 指向版本目录内的 exe。
# 必须先于任何 zaowu_paths / server_quart 导入。
sys.frozen = True  # type: ignore[attr-defined]
sys.executable = exe

import server_quart  # noqa: E402

# 启动面包屑：供端到端断言「当前跑的是哪个版本」（记录资源根）
os.makedirs(os.path.join(root, 'logs'), exist_ok=True)
with open(os.path.join(root, 'logs', 'sim_boot.log'), 'a', encoding='utf-8') as f:
    f.write(server_quart.DIST_DIR + '\n')

server_quart.run_server()

# 启动错误（如端口绑定失败）：像真实应用一样进程存活
while True:
    time.sleep(3600)
