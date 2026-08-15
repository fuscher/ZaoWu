package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// imageToken 用于 tasklist 输出匹配：进程等待与强杀都校验镜像名，
// 防止 60s 等待窗口内 PID 被复用后误杀无关进程。
const imageToken = "ZaoWu.exe"

// processExistsWithImage 查询 tasklist，返回该 PID 是否存在且镜像名包含
// imageToken。tasklist 失败（含 PID 不存在）一律视为已退出。
func processExistsWithImage(pid int, imageToken string) bool {
	out, err := exec.Command(
		"tasklist", "/FI", "PID eq "+strconv.Itoa(pid), "/FO", "CSV", "/NH",
	).Output()
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(out), "\n") {
		if strings.Contains(strings.ToLower(line), strings.ToLower(imageToken)) {
			return true
		}
	}
	return false
}

// processExists 判断 PID 是否仍是 ZaoWu 进程。
func processExists(pid int) bool {
	return processExistsWithImage(pid, imageToken)
}

// WaitProcessExit 轮询等待进程退出，超时返回 false。
func WaitProcessExit(pid int, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !processExists(pid) {
			return true
		}
		time.Sleep(500 * time.Millisecond)
	}
	return !processExists(pid)
}

// KillProcessIfMatches 仅当 PID 当前仍是 ZaoWu 进程时才强杀（PID 复用
// 防误杀）。进程已不存在视为成功。
func KillProcessIfMatches(pid int) bool {
	if !processExists(pid) {
		return true
	}
	return exec.Command("taskkill", "/PID", strconv.Itoa(pid), "/F").Run() == nil
}

// SpawnApp 启动指定 exe（工作目录设为 exe 所在目录），返回新进程 PID。
func SpawnApp(exe string) (int, error) {
	cmd := exec.Command(exe)
	cmd.Dir = filepath.Dir(exe)
	if err := cmd.Start(); err != nil {
		return 0, err
	}
	return cmd.Process.Pid, nil
}

// anyZaoWuRunning 判断是否有 ZaoWu.exe 进程在运行（精确匹配镜像名，
// 不含 ZaoWuLauncher.exe）。bootstrap 前置守卫用——现代 Windows 允许
// 重命名运行中的 exe（仅阻止覆写），不能依赖「移动失败」探测运行实例。
func anyZaoWuRunning() bool {
	out, err := exec.Command("tasklist", "/FO", "CSV", "/NH").Output()
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(out), "\n") {
		fields := strings.Split(line, `","`)
		if len(fields) > 0 && strings.Trim(fields[0], `"`) == imageToken {
			return true
		}
	}
	return false
}

// fileExists / isDir 辅助判断。
func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

// executableDir 返回启动器自身所在目录（部署根）。
func executableDir() string {
	exe, err := os.Executable()
	if err != nil {
		return "."
	}
	return filepath.Dir(exe)
}

// ensureSettings 物化 settings.json（首装钉根：防止应用侧 marker 上溯
// 越过部署根）。内容为 {}，应用首启会用默认值覆盖。
func ensureSettings(root string) {
	p := filepath.Join(root, "settings.json")
	if _, err := os.Stat(p); os.IsNotExist(err) {
		_ = os.WriteFile(p, []byte("{}"), 0644)
	}
}
