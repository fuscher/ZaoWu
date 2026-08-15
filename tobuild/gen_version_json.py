"""生成 version.json（更新检查清单）。

用法：
  python gen_version_json.py --version 1.2.0 --size 59000000 --sha256 <hex> [--notes 文案] [--out dist/version.json]

双源 Release 附件 URL 随版本号插值；sha256 与体积由 build.bat 实测传入。
"""

import argparse
import json
import os

_GITHUB_TMPL = 'https://github.com/fuscher/ZaoWu/releases/download/v{version}/ZaoWu-{version}-win64.zip'
_GITEE_TMPL = 'https://gitee.com/fuscher/ZaoWu/releases/download/v{version}/ZaoWu-{version}-win64.zip'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', required=True)
    ap.add_argument('--size', required=True, type=int)
    ap.add_argument('--sha256', required=True)
    ap.add_argument('--notes', default='')
    ap.add_argument('--out', default=os.path.join('dist', 'version.json'))
    args = ap.parse_args()

    payload = {
        'version': args.version,
        'notes': args.notes,
        'assets': {
            'win64': {
                'urls': [
                    _GITHUB_TMPL.format(version=args.version),
                    _GITEE_TMPL.format(version=args.version),
                ],
                'size': args.size,
                'sha256': args.sha256.lower(),
            },
        },
    }
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'version.json written: {args.out}')


if __name__ == '__main__':
    main()
