package main

import (
	"os"
	"path/filepath"
	"strconv"
	"time"
)

// 退出码约定：
//
//	0 = 成功（应用已启动 / 切换完成 / 回滚完成）
//	1 = 安装不完整或配置损坏，需要重新安装
//	2 = 旧布局转换被阻断（应用正在运行），用户需先关闭应用
const (
	exitOK         = 0
	exitReinstall  = 1
	exitAppRunning = 2
)

const (
	waitOldExitTimeout = 60 * time.Second // 旧进程退出等待；超时 taskkill 兜底（用户已确认更新）
	fastHealthTimeout  = 3 * time.Second  // 幂等 apply / 已有实例快速确认
)

// healthTimeout 新版本健康检查超时；ZAOWU_LAUNCHER_HEALTH_TIMEOUT（秒）
// 可覆盖（自动化验证用，默认 30s）。
var healthTimeout = func() time.Duration {
	if s := os.Getenv("ZAOWU_LAUNCHER_HEALTH_TIMEOUT"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			return time.Duration(n) * time.Second
		}
	}
	return 30 * time.Second
}()

func main() {
	root := executableDir()
	args := os.Args[1:]

	if len(args) > 0 && args[0] == "--switch" {
		pid, err := parseSwitchPid(args[1:])
		if err != nil {
			ShowError("更新失败", "启动参数无效：需要 --switch --pid <进程ID>")
			os.Exit(exitReinstall)
		}
		os.Exit(runSwitch(root, pid))
	}
	os.Exit(runNormal(root))
}

func parseSwitchPid(args []string) (int, error) {
	for i := 0; i+1 < len(args); i++ {
		if args[i] == "--pid" {
			return strconv.Atoi(args[i+1])
		}
	}
	return 0, os.ErrInvalid
}

// runNormal 普通启动：读 versions.json → 起当前版本；配置缺失时尝试旧
// 布局 bootstrap；配置损坏弹窗提示重装。
func runNormal(root string) int {
	cfgPath := filepath.Join(root, "versions.json")
	cfg, err := LoadVersions(cfgPath)

	if err == nil && cfg.Current != "" {
		appExe := filepath.Join(root, "versions", cfg.Current, "ZaoWu.exe")
		if !fileExists(appExe) {
			ShowError("安装不完整", "未找到当前版本的程序，请重新安装。")
			return exitReinstall
		}
		ensureSettings(root)
		if _, err := SpawnApp(appExe); err != nil {
			ShowError("启动失败", "无法启动应用："+err.Error())
			return exitReinstall
		}
		return exitOK
	}

	if err == errVersionsMissing {
		// 旧扁平布局检测：同目录存在 ZaoWu.exe 与 _internal → 自动转换。
		if fileExists(filepath.Join(root, "ZaoWu.exe")) && isDir(filepath.Join(root, "_internal")) {
			// 前置守卫：旧应用正在运行时不转换（移动运行中的 exe 在现代
			// Windows 上可能成功，不能依赖移动失败探测），避免双实例端口冲突。
			if anyZaoWuRunning() {
				ShowError(
					"无法自动迁移",
					"请先关闭正在运行的 ZaoWu，然后重新双击启动器。",
				)
				return exitAppRunning
			}
			if berr := Bootstrap(root); berr != nil {
				ShowError(
					"无法自动迁移",
					"请先关闭正在运行的 ZaoWu，然后重新双击启动器。",
				)
				return exitAppRunning
			}
			ensureSettings(root)
			appExe := filepath.Join(root, "versions", "v0", "ZaoWu.exe")
			if _, err := SpawnApp(appExe); err != nil {
				ShowError("启动失败", "无法启动应用："+err.Error())
				return exitReinstall
			}
			return exitOK
		}
		ShowError("安装不完整", "未找到版本配置，请重新安装。")
		return exitReinstall
	}

	ShowError("安装不完整", "版本配置损坏，请重新安装。")
	return exitReinstall
}

// runSwitch 切换模式：等旧进程退出 → 翻转配置 → 起新版本 → 健康检查 →
// 失败自动回滚拉起旧版。last_result 记录 "ok" / "rolled_back"。
func runSwitch(root string, oldPid int) int {
	cfgPath := filepath.Join(root, "versions.json")
	cfg, err := LoadVersions(cfgPath)
	if err != nil || cfg.Current == "" {
		ShowError("更新失败", "版本配置不可用。")
		return exitReinstall
	}

	// 旧进程退出（apply 已触发应用受控退出；此处等待 + 超时强杀兜底）。
	if !WaitProcessExit(oldPid, waitOldExitTimeout) {
		KillProcessIfMatches(oldPid)
	}

	port := ResolvePort()

	if deref(cfg.Pending) != "" && deref(cfg.Pending) != cfg.Current {
		oldCurrent := cfg.Current
		cfg.LastGood = &oldCurrent
		cfg.Current = *cfg.Pending
		cfg.Pending = nil
		if err := SaveVersionsAtomic(cfgPath, cfg); err != nil {
			ShowError("更新失败", "版本配置写入失败。")
			return exitReinstall
		}
	}

	return ensureRunning(root, cfg, cfgPath, port)
}

// ensureRunning 保证当前配置的版本在跑：快速确认已有健康实例（幂等 apply），
// 否则启动新实例并以「健康检查通过 且 新 PID 存活」双条件验收——
// 第二实例占端口时新实例绑定失败即死亡，仅 healthOK 会误判成功。
func ensureRunning(root string, cfg *VersionsConfig, cfgPath, port string) int {
	appExe := filepath.Join(root, "versions", cfg.Current, "ZaoWu.exe")
	if !fileExists(appExe) {
		return rollback(root, cfg, cfgPath)
	}

	// 幂等 apply：上一轮启动器已完成切换且实例健康。
	if WaitHealthy(port, fastHealthTimeout) {
		return recordResult(cfgPath, cfg, "ok")
	}

	pid2, err := SpawnApp(appExe)
	if err != nil {
		return rollback(root, cfg, cfgPath)
	}

	deadline := time.Now().Add(healthTimeout)
	for time.Now().Before(deadline) {
		if !processExists(pid2) {
			// 新实例死亡（绑定失败被抢占端口等）→ 回滚，防健康检查假阳性。
			return rollback(root, cfg, cfgPath)
		}
		if healthOnce(port) {
			return recordResult(cfgPath, cfg, "ok")
		}
		time.Sleep(300 * time.Millisecond)
	}

	// 健康检查超时：定向终止新实例后回滚。
	KillProcessIfMatches(pid2)
	return rollback(root, cfg, cfgPath)
}

// recordResult 写入 last_result 并退出。
func recordResult(cfgPath string, cfg *VersionsConfig, result string) int {
	cfg.LastResult = &result
	if err := SaveVersionsAtomic(cfgPath, cfg); err != nil {
		ShowError("更新完成", "新版本已启动，但状态写入失败。")
		return exitReinstall
	}
	return exitOK
}

// rollback 翻回上一已知好版本并自动拉起，last_result="rolled_back"。
func rollback(root string, cfg *VersionsConfig, cfgPath string) int {
	prev := deref(cfg.LastGood)
	if prev == "" || prev == cfg.Current {
		ShowError("更新失败", "新版本启动失败，且无可用旧版本回滚。")
		return exitReinstall
	}

	cfg.Current = prev
	cfg.LastGood = nil
	if err := SaveVersionsAtomic(cfgPath, cfg); err != nil {
		ShowError("更新失败", "回滚配置写入失败。")
		return exitReinstall
	}

	appExe := filepath.Join(root, "versions", prev, "ZaoWu.exe")
	if _, err := SpawnApp(appExe); err != nil {
		ShowError("更新失败", "旧版本自动拉起失败，请手动打开启动器。")
		return exitReinstall
	}
	return recordResult(cfgPath, cfg, "rolled_back")
}
