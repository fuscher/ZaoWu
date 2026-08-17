"""组装发布产物：版本包（zip + version.json）+ 应用本体（版本化布局 + 启动器）。

两个子命令：
  full      完整组装：应用本体（versions/v{ver} + 启动器 + versions.json）+ 版本包（zip + version.json）
  package   仅打包：把给定目录打为版本包 zip + version.json（含排除与自检）

用法：
  python assemble_release.py full --repo D:\\git\\ZaoWu --dest D:\\Sandbox\\v0.2.1
  python assemble_release.py package --src D:\\Sandbox\\v0.2.1 --out D:\\git\\ZaoWu\\dist --version 0.2.1

参考布局（D:\\Sandbox\\v0.2.0）：
  版本包/version.json + ZaoWu-{ver}-win64.zip（zip 扁平含 ZaoWu.exe + _internal/）
  应用本体/versions/v{ver}/ZaoWu.exe + _internal  + versions.json + ZaoWuLauncher.exe

发布卫生（与 routes/update.py 的 _validate_zip 对齐，作为客户端校验前的第一道防线）：
  - 条目数 / 解压总大小（zip 炸弹防护）
  - 路径穿越（.. / 绝对路径 / 盘符）
  - 排除 __pycache__ 缓存目录（避免把开发机运行时缓存塞进包）
  - 排除运行期状态文件（.skill_state.json / .plugin_state.json，由应用运行期生成）
  - 打包后自检：上述任一违规即拒绝发布
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import zipfile

GITHUB_TMPL = 'https://github.com/fuscher/ZaoWu/releases/download/v{version}/ZaoWu-{version}-win64.zip'
GITEE_TMPL = 'https://gitee.com/fuscher/ZaoWu/releases/download/v{version}/ZaoWu-{version}-win64.zip'

# 发布卫生：不进包的目录名 / 文件名
EXCLUDED_DIRS = {'__pycache__'}
EXCLUDED_FILENAMES = {'.skill_state.json', '.plugin_state.json'}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _iter_internal_files(src_dir: str):
    """遍历 _internal 下的可发布文件，排除 __pycache__ 与状态文件。"""
    internal = os.path.join(src_dir, '_internal')
    for root, dirs, files in os.walk(internal):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in files:
            if name in EXCLUDED_FILENAMES:
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, src_dir).replace(os.sep, '/')
            yield full, rel


def zip_dir_flat(src_dir: str, zip_path: str) -> None:
    """把 ZaoWu.exe + _internal 以扁平结构压入 zip（不含外层目录）。"""
    exe = os.path.join(src_dir, 'ZaoWu.exe')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(exe, 'ZaoWu.exe')
        for full, rel in _iter_internal_files(src_dir):
            z.write(full, rel)


def validate_package(zip_path: str, src_dir: str) -> None:
    """发布包自检：模拟客户端解压防护的关键规则，防止发布一个下载必败的包。

    检查（与 routes/update.py 的 _validate_zip 对齐）：
    - 条目数 / 解压总大小（zip 炸弹防护）
    - 路径穿越（.. / 绝对路径 / 盘符）
    - 不得夹带状态文件（.skill_state.json / .plugin_state.json）
    - 不得夹带 __pycache__ 缓存目录
    - _internal/plugins/ 下出现的目录必须 ⊆ 源 _internal/plugins/ 的目录清单
      （plugins 根下的散文件如 PLUGIN_DEV_GUIDE.md 放行）
    """
    _MAX_ENTRIES = 20000
    _MAX_TOTAL_SIZE = 1 << 30  # 1GB
    problems = set()
    src_plugins = os.path.join(src_dir, '_internal', 'plugins')
    known_dirs = set()
    if os.path.isdir(src_plugins):
        known_dirs = {e.name for e in os.scandir(src_plugins) if e.is_dir()}

    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if len(infos) > _MAX_ENTRIES:
            problems.add(f'条目数过多: {len(infos)}')
        if sum(i.file_size for i in infos) > _MAX_TOTAL_SIZE:
            problems.add('解压总大小超过 1GB')

        for info in infos:
            name = info.filename.replace('\\', '/')
            segments = name.split('/')
            if name.startswith('/') or (len(name) > 1 and name[1] == ':') or '..' in segments:
                problems.add(f'路径穿越: {name}')
            lower = name.lower()
            if '.skill_state.json' in lower or '.plugin_state.json' in lower:
                problems.add(f'夹带状态文件: {name}')
            if '__pycache__' in segments:
                problems.add(f'夹带缓存目录: {name}')
            if len(segments) >= 3 and segments[0] == '_internal' and segments[1] == 'plugins':
                if len(segments) == 3:
                    continue
                plugin_dir = segments[2]
                if plugin_dir not in known_dirs:
                    problems.add(f'未预知插件目录: {plugin_dir!r}')

    if problems:
        raise SystemExit('[错误] 发布包自检未通过，禁止发布：\n  ' + '\n  '.join(sorted(problems)))


def build_version_json(version: str, size: int, sha256_hex: str, notes: str = '') -> dict:
    """生成更新检查清单 version.json（与 gen_version_json.py 原逻辑一致）。"""
    return {
        'version': version,
        'notes': notes,
        'assets': {
            'win64': {
                'urls': [
                    GITHUB_TMPL.format(version=version),
                    GITEE_TMPL.format(version=version),
                ],
                'size': size,
                'sha256': sha256_hex.lower(),
            },
        },
    }


def _read_version(repo: str) -> str:
    """版本号单一来源：version.py（编译期常量，与运行时一致）。"""
    spec = importlib.util.spec_from_file_location('_zaowu_version', os.path.join(repo, 'version.py'))
    vmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vmod)
    return vmod.VERSION


def _require_exists(path: str) -> None:
    if not os.path.exists(path):
        raise SystemExit(f'[错误] 缺少构建产物: {path}')


def cmd_full(args):
    repo, dest = args.repo, args.dest
    version = _read_version(repo)
    folder = 'v' + version

    src_app = os.path.join(repo, 'dist', 'ZaoWu')
    launcher = os.path.join(repo, 'tobuild', 'out', 'ZaoWuLauncher.exe')
    for p in (src_app, os.path.join(src_app, 'ZaoWu.exe'), os.path.join(src_app, '_internal'), launcher):
        _require_exists(p)

    pkg_dir = os.path.join(dest, '版本包')
    app_dir = os.path.join(dest, '应用本体')
    ver_dir = os.path.join(app_dir, 'versions', folder)

    # ---- 应用本体 ----
    os.makedirs(ver_dir, exist_ok=True)
    if os.path.exists(os.path.join(ver_dir, '_internal')):
        shutil.rmtree(os.path.join(ver_dir, '_internal'))
    shutil.copytree(os.path.join(src_app, '_internal'), os.path.join(ver_dir, '_internal'))
    shutil.copy2(os.path.join(src_app, 'ZaoWu.exe'), os.path.join(ver_dir, 'ZaoWu.exe'))
    shutil.copy2(launcher, os.path.join(app_dir, 'ZaoWuLauncher.exe'))

    versions_json = {
        'schema': 1,
        'current': folder,
        'last_good': None,
        'pending': None,
        'last_result': None,
    }
    with open(os.path.join(app_dir, 'versions.json'), 'w', encoding='utf-8') as f:
        json.dump(versions_json, f, ensure_ascii=False, indent=2)

    # ---- 版本包 ----
    os.makedirs(pkg_dir, exist_ok=True)
    zip_path = os.path.join(pkg_dir, f'ZaoWu-{version}-win64.zip')
    _build_package(src_app, zip_path, os.path.join(pkg_dir, 'version.json'), version)

    print(f'版本: {version}')
    print(f'应用本体: {app_dir}')
    print(f'  versions/{folder}/ZaoWu.exe')
    print(f'  ZaoWuLauncher.exe')
    print(f'  versions.json -> current={folder}')
    print(f'版本包: {pkg_dir}')
    print(f'  {os.path.basename(zip_path)}')
    print(f'  version.json')


def cmd_package(args):
    src, out_dir, version = args.src, args.out, args.version
    _require_exists(os.path.join(src, 'ZaoWu.exe'))
    _require_exists(os.path.join(src, '_internal'))

    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f'ZaoWu-{version}-win64.zip')
    _build_package(src, zip_path, os.path.join(out_dir, 'version.json'), version)
    print(f'版本包: {out_dir}')
    print(f'  {os.path.basename(zip_path)}')
    print(f'  version.json')


def _build_package(src_dir: str, zip_path: str, version_json_path: str, version: str) -> None:
    """打版本包 zip + version.json（打包 → 自检 → 度量 → 生成清单）。"""
    if os.path.exists(zip_path):
        os.remove(zip_path)
    zip_dir_flat(src_dir, zip_path)
    validate_package(zip_path, src_dir)

    size = os.path.getsize(zip_path)
    digest = sha256(zip_path).lower()
    with open(version_json_path, 'w', encoding='utf-8') as f:
        json.dump(build_version_json(version, size, digest), f, ensure_ascii=False, indent=2)
    print(f'{os.path.basename(zip_path)}  size={size}  sha256={digest}')


def main():
    ap = argparse.ArgumentParser(description='组装发布产物（应用本体 + 版本包）')
    sub = ap.add_subparsers(dest='command', required=True)

    p_full = sub.add_parser('full', help='完整组装：应用本体 + 版本包')
    p_full.add_argument('--repo', required=True)
    p_full.add_argument('--dest', required=True)
    p_full.set_defaults(func=cmd_full)

    p_pkg = sub.add_parser('package', help='仅打包：版本包 zip + version.json（含排除与自检）')
    p_pkg.add_argument('--src', required=True, help='含 ZaoWu.exe 与 _internal 的目录')
    p_pkg.add_argument('--out', required=True, help='zip 与 version.json 输出目录')
    p_pkg.add_argument('--version', required=True, help='版本号，如 0.2.1')
    p_pkg.set_defaults(func=cmd_package)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
