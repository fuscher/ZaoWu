#!/bin/bash
# P1 启动器验证矩阵（自动化；弹窗场景用 ZAOWU_LAUNCHER_NOGUI=1 走 stderr）
# 注意：
#   - 传给 Windows 进程的环境变量与 python 内联脚本的路径必须经 cygpath -w 转换
#   - 子进程镜像名是 ZaoWu.exe，清理一律 taskkill //IM ZaoWu.exe //F
#   - 启动器退出后子进程写入 marker 有延迟，检查前轮询等待
set -u
LAUNCHER="/d/git/ZaoWu/tobuild/out/ZaoWuLauncher.exe"
FAKEAPP="/d/git/ZaoWu/tobuild/out/fakeapp.exe"
PY="/d/git/ZaoWu/.venv/Scripts/python.exe"
WORK=$(mktemp -d)
PASS=0; FAIL=0

taskkill //IM ZaoWu.exe //F >/dev/null 2>&1

check() { # check <描述> <真值条件：0=通过>
  if [ "$2" = "0" ]; then PASS=$((PASS+1)); echo "  PASS: $1"
  else FAIL=$((FAIL+1)); echo "  FAIL: $1"; fi
}

wait_file() { # wait_file <path> <秒>：等待文件出现
  local i=0
  while [ $i -lt $2 ] && [ ! -f "$1" ]; do sleep 0.2; i=$((i+1)); done
  [ -f "$1" ]
}

# ── 场景 1+8：普通启动（合法配置，路径含空格/中文/&）──
D1="$WORK/ZaoWu 测试 &dir"
mkdir -p "$D1/versions/v1.1.0"
cp "$FAKEAPP" "$D1/versions/v1.1.0/ZaoWu.exe"
cat > "$D1/versions.json" << 'EOF'
{"schema":1,"current":"v1.1.0","last_good":null,"pending":null,"last_result":null}
EOF
cp "$LAUNCHER" "$D1/"
MARK1=$(cygpath -w "$D1/marker.txt")
FAKE_APP_MODE=exit FAKE_APP_MARKER="$MARK1" "$D1/ZaoWuLauncher.exe"
RC1=$?
wait_file "$D1/marker.txt" 15
[ $RC1 = 0 ] && [ -f "$D1/marker.txt" ] && [ -f "$D1/settings.json" ]
check "普通启动（特殊路径）：exit=0 + 子进程被拉起（marker）+ settings.json 物化" "$?"

# ── 场景 2：配置损坏 → 弹窗退出码 1 ──
D2=$(mktemp -d); cp "$LAUNCHER" "$D2/"
echo '{broken' > "$D2/versions.json"
OUT2=$(ZAOWU_LAUNCHER_NOGUI=1 "$D2/ZaoWuLauncher.exe" 2>&1); RC2=$?
[ $RC2 = 1 ] && echo "$OUT2" | grep -q '损坏'
check "配置损坏 → exit=1 + stderr 提示" "$?"

# ── 场景 3：配置缺失且无旧布局 → exit 1 ──
D3=$(mktemp -d); cp "$LAUNCHER" "$D3/"
OUT3=$(ZAOWU_LAUNCHER_NOGUI=1 "$D3/ZaoWuLauncher.exe" 2>&1); RC3=$?
[ $RC3 = 1 ] && echo "$OUT3" | grep -q '安装不完整'
check "无配置无旧布局 → exit=1 + stderr 提示" "$?"

# ── 场景 4：bootstrap 旧扁平布局 ──
D4=$(mktemp -d); cp "$LAUNCHER" "$D4/"
mkdir -p "$D4/_internal/subdir"
echo "runtime data" > "$D4/data.txt"
cp "$FAKEAPP" "$D4/ZaoWu.exe"
MARK4=$(cygpath -w "$D4/marker.txt")
FAKE_APP_MODE=exit FAKE_APP_MARKER="$MARK4" "$D4/ZaoWuLauncher.exe"
RC4=$?
wait_file "$D4/marker.txt" 15
[ $RC4 = 0 ] && [ -f "$D4/versions/v0/ZaoWu.exe" ] && [ -d "$D4/versions/v0/_internal/subdir" ] \
  && [ -f "$D4/data.txt" ] && [ -f "$D4/marker.txt" ] && [ -f "$D4/settings.json" ]
check "bootstrap：v0 布局转换 + 运行期数据保留 + 应用启动 + settings 物化" "$?"
CUR4=$("$PY" -c "import json;print(json.load(open(r'$(cygpath -w "$D4/versions.json")',encoding='utf-8'))['current'])")
[ "$CUR4" = "v0" ]
check "bootstrap：versions.json current=v0" "$?"

# ── 场景 5：bootstrap 时应用正在运行 → exit 2 无半转换 ──
D5=$(mktemp -d); cp "$LAUNCHER" "$D5/"
mkdir -p "$D5/_internal"
cp "$FAKEAPP" "$D5/ZaoWu.exe"
"$D5/ZaoWu.exe" &
sleep 1
OUT5=$(ZAOWU_LAUNCHER_NOGUI=1 "$D5/ZaoWuLauncher.exe" 2>&1); RC5=$?
taskkill //IM ZaoWu.exe //F >/dev/null 2>&1
[ $RC5 = 2 ] && [ -d "$D5/_internal" ] && [ ! -d "$D5/versions" ] && [ ! -f "$D5/versions.json" ]
check "bootstrap 占用 → exit=2 + 无半转换（_internal 原位、无 versions/、无 versions.json）" "$?"

# ── 场景 6：切换成功（健康检查通过）──
D6=$(mktemp -d); cp "$LAUNCHER" "$D6/"
mkdir -p "$D6/versions/v1.1.0" "$D6/versions/v1.2.0"
cp "$FAKEAPP" "$D6/versions/v1.1.0/ZaoWu.exe"
cp "$FAKEAPP" "$D6/versions/v1.2.0/ZaoWu.exe"
cat > "$D6/versions.json" << 'EOF'
{"schema":1,"current":"v1.1.0","last_good":null,"pending":"v1.2.0","last_result":null}
EOF
FAKE_APP_MODE=serve ZAOWU_PORT=5610 ZAOWU_LAUNCHER_NOGUI=1 "$D6/ZaoWuLauncher.exe" --switch --pid 99999999
RC6=$?
STATE6=$("$PY" -c "
import json
c=json.load(open(r'$(cygpath -w "$D6/versions.json")',encoding='utf-8'))
print(c['current'], c['last_good'], c['pending'], c['last_result'])")
taskkill //IM ZaoWu.exe //F >/dev/null 2>&1
[ $RC6 = 0 ] && [ "$STATE6" = 'v1.2.0 v1.1.0 None ok' ]
check "切换成功 exit=0 + 配置翻转（current=v1.2.0,last_good=v1.1.0,pending=null）+ last_result=ok" "$?"

# ── 场景 7：切换失败（健康检查超时）自动回滚 ──
D7=$(mktemp -d); cp "$LAUNCHER" "$D7/"
mkdir -p "$D7/versions/v1.1.0" "$D7/versions/v1.2.0"
cp "$FAKEAPP" "$D7/versions/v1.1.0/ZaoWu.exe"
cp "$FAKEAPP" "$D7/versions/v1.2.0/ZaoWu.exe"
cat > "$D7/versions.json" << 'EOF'
{"schema":1,"current":"v1.1.0","last_good":null,"pending":"v1.2.0","last_result":null}
EOF
# 新版本静默常驻（无健康端点）→ 2s 超时 → 定向终止 → 回滚拉起旧版（exit 模式写 marker）
MARK7=$(cygpath -w "$D7/rolled_back_marker.txt")
FAKE_APP_MODE=exit FAKE_APP_MARKER="$MARK7" \
ZAOWU_LAUNCHER_HEALTH_TIMEOUT=2 ZAOWU_LAUNCHER_NOGUI=1 \
"$D7/ZaoWuLauncher.exe" --switch --pid 99999999
RC7=$?
STATE7=$("$PY" -c "
import json
c=json.load(open(r'$(cygpath -w "$D7/versions.json")',encoding='utf-8'))
print(c['current'], c['last_good'], c['last_result'])")
# 先等回滚拉起的子进程写完 marker，再清理残留（taskkill 会把新子进程一并杀掉）
wait_file "$D7/rolled_back_marker.txt" 15
taskkill //IM ZaoWu.exe //F >/dev/null 2>&1
[ $RC7 = 0 ] && [ "$STATE7" = 'v1.1.0 None rolled_back' ] && [ -f "$D7/rolled_back_marker.txt" ]
check "切换失败 → exit=0 + 翻回旧版（current=v1.1.0,last_good=null）+ rolled_back + 旧版被拉起" "$?"

# ── 场景 9：更新期间第二实例占端口 → 回滚（翻转后、拉起前检测）──
D9=$(mktemp -d); cp "$LAUNCHER" "$D9/"
mkdir -p "$D9/versions/v1.1.0" "$D9/versions/v1.2.0"
cp "$FAKEAPP" "$D9/versions/v1.1.0/ZaoWu.exe"
cp "$FAKEAPP" "$D9/versions/v1.2.0/ZaoWu.exe"
cat > "$D9/versions.json" << 'EOF'
{"schema":1,"current":"v1.1.0","last_good":null,"pending":"v1.2.0","last_result":null}
EOF
# 第二实例：serve 模式常驻占端口（模拟用户更新期间又开了一个旧实例）
FAKE_APP_MODE=serve ZAOWU_PORT=5612 "$D9/versions/v1.1.0/ZaoWu.exe" &
sleep 1
MARK9=$(cygpath -w "$D9/rolled_back_marker.txt")
FAKE_APP_MODE=exit FAKE_APP_MARKER="$MARK9" ZAOWU_PORT=5612 \
ZAOWU_LAUNCHER_HEALTH_TIMEOUT=2 ZAOWU_LAUNCHER_NOGUI=1 \
"$D9/ZaoWuLauncher.exe" --switch --pid 99999999
RC9=$?
# 先等回滚拉起的子进程写完 marker，再清理残留
wait_file "$D9/rolled_back_marker.txt" 15
taskkill //IM ZaoWu.exe //F >/dev/null 2>&1
STATE9=$("$PY" -c "
import json
c=json.load(open(r'$(cygpath -w "$D9/versions.json")',encoding='utf-8'))
print(c['current'], c['last_good'], c['last_result'])")
[ $RC9 = 0 ] && [ "$STATE9" = 'v1.1.0 None rolled_back' ] && [ -f "$D9/rolled_back_marker.txt" ]
check "第二实例占端口 → 回滚（current=v1.1.0 + rolled_back + 旧版拉起）" "$?"

echo
echo "P1 矩阵结果: PASS=$PASS FAIL=$FAIL (工作目录 $WORK)"
[ $FAIL = 0 ]
