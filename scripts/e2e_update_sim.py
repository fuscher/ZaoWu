"""端到端更新流程全自动模拟（§10.2 自动化部分）。

场景（全部在含空格/中文/& 的临时目录中执行，stdlib only）：
1. 更新成功全流程：双源检查取较大者 → 下载（真实回退/解压防护）→
   apply → 启动器切换 → 新版本健康 → 用户数据/插件/技能状态完整保留 →
   last_good 保留 → last_result 一次性消费 → 更早版本清理进回收站
2. 回滚：新版本为坏 exe → 健康检查超时 → 翻回旧版自动拉起 → rolled_back
3. 旧布局 bootstrap：扁平部署 → 启动器自动转换 v0 → 首启完成数据迁出
4. 非默认端口（ZAOWU_PORT env）变体跑通场景 1

真机专属项（真实双源网络、任务栏固定、SmartScreen、真实发布流程）不在此列。
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(REPO, 'tobuild', 'out', 'ZaoWuLauncher.exe')
FAKEAPP = os.path.join(REPO, 'tobuild', 'out', 'fakeapp.exe')
BROKENAPP = os.path.join(REPO, 'tobuild', 'out', 'brokenapp.exe')
PYTHON = sys.executable
SIM_SERVER = os.path.join(REPO, 'scripts', 'e2e_sim_server.py')

SKILL_INIT_TMPL = '''
from services.skill_registry import SkillDefinition


def zaowu_register_skills():
    return [SkillDefinition(name=%r, description=%r, system_prompt='')]
'''

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  PASS: {name}')
    else:
        FAIL += 1
        print(f'  FAIL: {name}')


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def wait_health(port, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def api(port, path, method='GET', timeout=15):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


def taskkill_all():
    subprocess.run(['taskkill', '/IM', 'ZaoWu.exe', '/F'],
                   capture_output=True, text=True)
    time.sleep(1)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def zip_dir(src_dir, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for base in ['ZaoWu.exe', '_internal']:
            p = os.path.join(src_dir, base)
            if os.path.isdir(p):
                for root, dirs, files in os.walk(p):
                    for f in files:
                        full = os.path.join(root, f)
                        zf.write(full, os.path.relpath(full, src_dir).replace('\\', '/'))
            elif os.path.isfile(p):
                zf.write(p, base)


class SourceServer(threading.Thread):
    """本地 HTTP 更新源：目录内提供 version.json 与 zip。"""

    def __init__(self, root_dir):
        super().__init__(daemon=True)
        self.root_dir = root_dir
        self.port = free_port()
        self._httpd = None

    def run(self):
        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
            *a, directory=self.root_dir, **kw)
        self._httpd = http.server.HTTPServer(('127.0.0.1', self.port), handler)
        self._httpd.serve_forever()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}'


def serve_package(server, version, zip_src_dir):
    """把 zip_src_dir 打包成发布 zip 并写出该源的 version.json，返回资产元数据。"""
    zip_name = f'ZaoWu-{version}-win64.zip'
    zip_path = os.path.join(server.root_dir, zip_name)
    zip_dir(zip_src_dir, zip_path)
    assets = {'urls': [f'{server.url}/{zip_name}'],
              'size': os.path.getsize(zip_path),
              'sha256': sha256_file(zip_path)}
    write_json(os.path.join(server.root_dir, 'version.json'),
               {'version': version, 'notes': '更新说明', 'assets': {'win64': assets}})
    return assets


def build_version_dir(workdir, version, with_legacy_userdata=False):
    """构造一个版本目录：fakeapp 作为 ZaoWu.exe + _internal 资源树。"""
    vdir = os.path.join(workdir, 'versions', version)
    internal = os.path.join(vdir, '_internal')
    os.makedirs(os.path.join(internal, 'ZaoWu', 'dist'), exist_ok=True)
    os.makedirs(os.path.join(internal, 'plugins'), exist_ok=True)
    os.makedirs(os.path.join(internal, 'agent_modules', 'skills'), exist_ok=True)
    with open(os.path.join(internal, 'version_marker.txt'), 'w', encoding='utf-8') as f:
        f.write(version)

    builtin = os.path.join(internal, 'agent_modules', 'skills', 'sim_builtin')
    os.makedirs(builtin)
    write_json(os.path.join(builtin, 'manifest.json'), {'name': 'sim_builtin', 'type': 'skill'})
    with open(os.path.join(builtin, '__init__.py'), 'w', encoding='utf-8') as f:
        f.write(SKILL_INIT_TMPL % ('sim_builtin', 'builtin skill'))

    if with_legacy_userdata:
        # 旧版遗留用户数据（迁移源）：插件状态 + 技能状态 + 用户导入技能目录
        write_json(os.path.join(internal, 'plugins', '.plugin_state.json'),
                   {'version': 1, 'plugins': {'sim_plugin': {'enabled': False}}})
        write_json(os.path.join(internal, 'agent_modules', 'skills', '.skill_state.json'),
                   {'version': 1, 'enabled': ['user_skill'], 'disabled': [], 'deleted': []})
        us = os.path.join(internal, 'agent_modules', 'skills', 'user_skill')
        os.makedirs(us)
        write_json(os.path.join(us, 'manifest.json'), {'name': 'user_skill', 'type': 'skill'})
        with open(os.path.join(us, '__init__.py'), 'w', encoding='utf-8') as f:
            f.write(SKILL_INIT_TMPL % ('user_skill', 'user imported skill'))

    shutil.copy(FAKEAPP, os.path.join(vdir, 'ZaoWu.exe'))
    return vdir


def start_app(workdir, version, port, sources, extra_env=None):
    env = os.environ.copy()
    env.update({
        'ZAOWU_SIM_ROOT': workdir,
        'FAKE_APP_MODE': 'python-server',
        'FAKE_APP_PYTHON': PYTHON,
        'FAKE_APP_SCRIPT': SIM_SERVER,
        'ZAOWU_PORT': str(port),
        'ZAOWU_UPDATE_SOURCES': ','.join(sources),
        'ZAOWU_LAUNCHER_NOGUI': '1',
    })
    if extra_env:
        env.update(extra_env)
    exe = os.path.join(workdir, 'versions', version, 'ZaoWu.exe')
    return subprocess.Popen([exe], env=env, cwd=os.path.dirname(exe))


def init_workdir():
    workdir = tempfile.mkdtemp(prefix='zaowu 更新 &模拟-')
    write_json(os.path.join(workdir, 'settings.json'), {})
    os.makedirs(os.path.join(workdir, 'data'))
    with open(os.path.join(workdir, 'data', 'seed.txt'), 'w', encoding='utf-8') as f:
        f.write('user data seed')
    shutil.copy(LAUNCHER, os.path.join(workdir, 'ZaoWuLauncher.exe'))
    return workdir


def last_boot_line(workdir):
    path = os.path.join(workdir, 'logs', 'sim_boot.log')
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        lines = f.read().strip().splitlines()
    return lines[-1] if lines else None


def wait_state_ready(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st, state = api(port, '/api/update/status')
        if state.get('state') == 'ready':
            return True
        if state.get('state') == 'idle' and state.get('error'):
            print(f'    [下载失败] {state.get("error")}')
            return False
        time.sleep(0.5)
    return False


def scenario_update(workdir, port, launcher_timeout_env=None):
    print(f'--- 场景1：更新成功全流程 (port={port}) ---')
    build_version_dir(workdir, 'v1.1.0', with_legacy_userdata=True)
    build_version_dir(workdir, 'v1.2.0')
    build_version_dir(workdir, 'v1.0.0')  # 更早版本（清理对象）
    write_json(os.path.join(workdir, 'versions.json'),
               {'schema': 1, 'current': 'v1.1.0', 'last_good': None,
                'pending': None, 'last_result': None})

    src_a = SourceServer(os.path.join(workdir, 'src_a'))
    src_b = SourceServer(os.path.join(workdir, 'src_b'))
    os.makedirs(src_a.root_dir)
    os.makedirs(src_b.root_dir)
    src_a.start()
    src_b.start()
    try:
        serve_package(src_a, '1.2.0', os.path.join(workdir, 'versions', 'v1.2.0'))
        # 源 B 报旧版本（验证「双源取较大者」）
        write_json(os.path.join(src_b.root_dir, 'version.json'),
                   {'version': '1.1.0', 'notes': '', 'assets': {}})
        sources = [f'{src_a.url}/version.json', f'{src_b.url}/version.json']

        app = start_app(workdir, 'v1.1.0', port, sources, launcher_timeout_env)
        assert wait_health(port), 'v1.1.0 启动失败'

        # 首启即完成数据迁出（source=current=v1.1.0）
        check('首启迁移：插件状态落部署根', os.path.isfile(os.path.join(workdir, '.plugin_state.json')))
        check('首启迁移：技能状态落部署根', os.path.isfile(os.path.join(workdir, 'skills', '.skill_state.json')))
        check('首启迁移：用户导入技能目录迁出', os.path.isdir(os.path.join(workdir, 'skills', 'user_skill')))
        check('首启迁移：内置技能未被复制', not os.path.isdir(os.path.join(workdir, 'skills', 'sim_builtin')))
        check('首启迁移：标记已写', os.path.isfile(os.path.join(workdir, '.userdata_migrated')))

        st, skills = api(port, '/api/agent/skills')
        names = {s['name'] for s in skills.get('skills', [])}
        check('技能注册：内置 + 迁移用户技能均在', {'sim_builtin', 'user_skill'} <= names)

        st, info = api(port, '/api/update/check')
        check('双源检查：取较大版本 1.2.0', info.get('hasUpdate') is True and info.get('latest') == '1.2.0')

        st, _ = api(port, '/api/update/download')
        check('下载完成（进度轮询至 ready）', wait_state_ready(port))

        st, res = api(port, '/api/update/apply', method='POST', timeout=30)
        check('apply 响应送达', res.get('ok') is True)
        app.wait(timeout=20)

        assert wait_health(port, 60), '新版本启动失败（启动器切换后）'
        cfg = read_json(os.path.join(workdir, 'versions.json'))
        check('切换：current=v1.2.0 + last_good=v1.1.0 + pending=null',
              cfg.get('current') == 'v1.2.0' and cfg.get('last_good') == 'v1.1.0' and cfg.get('pending') is None)
        check('切换：last_result=ok', cfg.get('last_result') == 'ok')
        boot = last_boot_line(workdir) or ''
        check('新版本在跑（资源根指向 v1.2.0）',
              'versions' + os.sep + 'v1.2.0' + os.sep + '_internal' in boot)
        check('zip 解压正确（版本标记 1.2.0）',
              open(os.path.join(workdir, 'versions', 'v1.2.0', '_internal', 'version_marker.txt'),
                   encoding='utf-8').read() == '1.2.0')

        check('运行期数据保留', open(os.path.join(workdir, 'data', 'seed.txt'), encoding='utf-8').read() == 'user data seed')
        check('插件状态保留', read_json(os.path.join(workdir, '.plugin_state.json'))['plugins'] == {'sim_plugin': {'enabled': False}})
        st, skills = api(port, '/api/agent/skills')
        names = {s['name'] for s in skills.get('skills', [])}
        check('技能状态与内容保留', {'sim_builtin', 'user_skill'} <= names)

        st, res = api(port, '/api/update/check?consume_only=1')
        check('last_result 一次性消费=ok', res.get('lastResult') == 'ok')
        st, res = api(port, '/api/update/check?consume_only=1')
        check('last_result 消费后再取=null', res.get('lastResult') is None)

        # consume 'ok' 触发后台清理：更早版本进回收站，last_good 保留
        deadline = time.time() + 20
        while time.time() < deadline and os.path.isdir(os.path.join(workdir, 'versions', 'v1.0.0')):
            time.sleep(0.5)
        check('清理：更早版本已删除', not os.path.isdir(os.path.join(workdir, 'versions', 'v1.0.0')))
        check('清理：last_good 保留', os.path.isdir(os.path.join(workdir, 'versions', 'v1.1.0')))
    finally:
        src_a.stop()
        src_b.stop()
        taskkill_all()


def scenario_rollback(workdir, port):
    print(f'--- 场景2：回滚（新版本坏 exe，健康检查超时）(port={port}) ---')
    build_version_dir(workdir, 'v1.1.0')
    build_version_dir(workdir, 'v1.2.0')
    write_json(os.path.join(workdir, 'versions.json'),
               {'schema': 1, 'current': 'v1.1.0', 'last_good': None,
                'pending': None, 'last_result': None})

    src = SourceServer(os.path.join(workdir, 'src'))
    os.makedirs(src.root_dir)
    src.start()
    try:
        serve_package(src, '1.2.0', os.path.join(workdir, 'versions', 'v1.2.0'))
        sources = [f'{src.url}/version.json']

        extra_env = {'ZAOWU_LAUNCHER_HEALTH_TIMEOUT': '3'}
        app = start_app(workdir, 'v1.1.0', port, sources, extra_env)
        assert wait_health(port), 'v1.1.0 启动失败'

        st, _ = api(port, '/api/update/download')
        check('回滚场景：下载至 ready', wait_state_ready(port))

        # 下载完成后把新版本换成坏 exe（无响应的 brokenapp）再 apply
        shutil.copy(BROKENAPP, os.path.join(workdir, 'versions', 'v1.2.0', 'ZaoWu.exe'))

        st, res = api(port, '/api/update/apply', method='POST', timeout=30)
        check('回滚场景 apply 响应送达', res.get('ok') is True)
        app.wait(timeout=20)

        assert wait_health(port, 60), '回滚后旧版本未拉起'
        cfg = read_json(os.path.join(workdir, 'versions.json'))
        check('回滚：current=v1.1.0 + last_good=null',
              cfg.get('current') == 'v1.1.0' and cfg.get('last_good') is None)
        check('回滚：last_result=rolled_back', cfg.get('last_result') == 'rolled_back')
        boot = last_boot_line(workdir) or ''
        check('旧版本自动拉起（资源根回到 v1.1.0）',
              'versions' + os.sep + 'v1.1.0' + os.sep + '_internal' in boot)
        st, res = api(port, '/api/update/check?consume_only=1')
        check('回滚提示一次性消费', res.get('lastResult') == 'rolled_back')
        st, res = api(port, '/api/update/check?consume_only=1')
        check('回滚提示消费后再取=null', res.get('lastResult') is None)
    finally:
        src.stop()
        taskkill_all()


def scenario_bootstrap(workdir, port, sources):
    print(f'--- 场景3：旧布局 bootstrap（首启迁移）(port={port}) ---')
    # 旧扁平部署：exe + _internal（含遗留用户数据）+ 运行期数据，无 versions.json
    build_version_dir(workdir, 'v1.1.0', with_legacy_userdata=True)  # 借其 _internal
    shutil.copytree(os.path.join(workdir, 'versions', 'v1.1.0', '_internal'),
                    os.path.join(workdir, '_internal'))
    shutil.rmtree(os.path.join(workdir, 'versions'))
    shutil.copy(FAKEAPP, os.path.join(workdir, 'ZaoWu.exe'))
    with open(os.path.join(workdir, 'data', 'seed.txt'), 'w', encoding='utf-8') as f:
        f.write('legacy user data')

    env = os.environ.copy()
    env.update({
        'ZAOWU_SIM_ROOT': workdir,
        'FAKE_APP_MODE': 'python-server',
        'FAKE_APP_PYTHON': PYTHON,
        'FAKE_APP_SCRIPT': SIM_SERVER,
        'ZAOWU_PORT': str(port),
        'ZAOWU_UPDATE_SOURCES': ','.join(sources),
        'ZAOWU_LAUNCHER_NOGUI': '1',
    })
    proc = subprocess.run([os.path.join(workdir, 'ZaoWuLauncher.exe')], env=env, timeout=60)
    check('bootstrap：启动器 exit=0', proc.returncode == 0)
    check('bootstrap：v0 布局转换', os.path.isfile(os.path.join(workdir, 'versions', 'v0', 'ZaoWu.exe')))
    cfg = read_json(os.path.join(workdir, 'versions.json'))
    check('bootstrap：versions.json current=v0', cfg.get('current') == 'v0')
    check('bootstrap：运行期数据原样保留',
          open(os.path.join(workdir, 'data', 'seed.txt'), encoding='utf-8').read() == 'legacy user data')

    assert wait_health(port, 30), 'bootstrap 后 v0 应用未启动'
    check('bootstrap 首启：用户数据迁出（skills/user_skill）',
          os.path.isdir(os.path.join(workdir, 'skills', 'user_skill')))
    st, skills = api(port, '/api/agent/skills')
    names = {s['name'] for s in skills.get('skills', [])}
    check('bootstrap 首启：导入技能已注册', 'user_skill' in names)
    taskkill_all()


def main():
    for exe in [LAUNCHER, FAKEAPP, BROKENAPP]:
        if not os.path.isfile(exe):
            print(f'缺少构建产物: {exe}（先构建启动器与假应用）')
            return 1
    taskkill_all()

    # 场景 1：更新成功（默认端口路径，port 经 ZAOWU_PORT env 生效）
    scenario_update(init_workdir(), free_port())

    # 场景 2：回滚
    scenario_rollback(init_workdir(), free_port())

    # 场景 3：bootstrap
    scenario_bootstrap(init_workdir(), free_port(), [])

    # 场景 4：非默认端口变体（另一随机端口再跑一遍全流程）
    scenario_update(init_workdir(), free_port())

    taskkill_all()
    print(f'\n端到端模拟结果: PASS={PASS} FAIL={FAIL}')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
