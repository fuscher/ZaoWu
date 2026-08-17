"""组装发布产物：版本包（zip + version.json）+ 应用本体（版本化布局 + 启动器）。

参考布局（D:\\Sandbox\\v0.2.0）：
  版本包/version.json + ZaoWu-{ver}-win64.zip（zip 扁平含 ZaoWu.exe + _internal/）
  应用本体/versions/v{ver}/ZaoWu.exe + _internal  + versions.json + ZaoWuLauncher.exe

用法：
  python assemble_release.py --repo D:\\git\\ZaoWu --dest D:\\Sandbox\\v0.2.1
"""
import argparse
import hashlib
import json
import os
import shutil
import zipfile

GITHUB_TMPL = 'https://github.com/fuscher/ZaoWu/releases/download/v{version}/ZaoWu-{version}-win64.zip'
GITEE_TMPL = 'https://gitee.com/fuscher/ZaoWu/releases/download/v{version}/ZaoWu-{version}-win64.zip'


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def zip_dir_flat(src_dir: str, zip_path: str) -> None:
    """把 ZaoWu.exe + _internal 以扁平结构压入 zip（不含外层目录）。"""
    exe = os.path.join(src_dir, 'ZaoWu.exe')
    internal = os.path.join(src_dir, '_internal')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(exe, 'ZaoWu.exe')
        for root, _dirs, files in os.walk(internal):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, src_dir).replace(os.sep, '/')
                z.write(full, rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True)
    ap.add_argument('--dest', required=True)
    args = ap.parse_args()

    repo = args.repo
    dest = args.dest

    # 版本号单一来源：version.py
    import importlib.util
    spec = importlib.util.spec_from_file_location('version', os.path.join(repo, 'version.py'))
    vmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vmod)
    version = vmod.VERSION
    folder = 'v' + version

    src_app = os.path.join(repo, 'dist', 'ZaoWu')
    launcher = os.path.join(repo, 'tobuild', 'out', 'ZaoWuLauncher.exe')
    for p in (src_app, os.path.join(src_app, 'ZaoWu.exe'), os.path.join(src_app, '_internal'), launcher):
        if not os.path.exists(p):
            raise SystemExit(f'[错误] 缺少构建产物: {p}')

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
    zip_name = f'ZaoWu-{version}-win64.zip'
    zip_path = os.path.join(pkg_dir, zip_name)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    zip_dir_flat(src_app, zip_path)

    size = os.path.getsize(zip_path)
    digest = sha256(zip_path)
    version_json = {
        'version': version,
        'notes': '',
        'assets': {
            'win64': {
                'urls': [
                    GITHUB_TMPL.format(version=version),
                    GITEE_TMPL.format(version=version),
                ],
                'size': size,
                'sha256': digest.lower(),
            },
        },
    }
    with open(os.path.join(pkg_dir, 'version.json'), 'w', encoding='utf-8') as f:
        json.dump(version_json, f, ensure_ascii=False, indent=2)

    print(f'版本: {version}')
    print(f'应用本体: {app_dir}')
    print(f'  versions/{folder}/ZaoWu.exe')
    print(f'  ZaoWuLauncher.exe')
    print(f'  versions.json -> current={folder}')
    print(f'版本包: {pkg_dir}')
    print(f'  {zip_name}  size={size}  sha256={digest.lower()}')
    print(f'  version.json')


if __name__ == '__main__':
    main()
