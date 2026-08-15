// 假应用：供启动器验证矩阵与端到端模拟使用（后者用 python-server 模式
// 把真实后端跑在「假 frozen」语义下）。行为由环境变量控制（启动器
// SpawnApp 不带参数，环境变量自动继承）：
//   FAKE_APP_MODE=serve          监听 ZAOWU_PORT（缺省 5000）提供 /api/health
//   FAKE_APP_MODE=exit           写 FAKE_APP_MARKER 文件后立即退出
//   FAKE_APP_MODE=python-server  以 FAKE_APP_PYTHON 运行 FAKE_APP_SCRIPT 并
//                               阻塞跟随其退出码（模拟真实应用进程）
//   其他/缺省                    静默常驻（模拟无响应的坏应用）
package main

import (
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"time"
)

func main() {
	mode := os.Getenv("FAKE_APP_MODE")
	switch mode {
	case "serve":
		port := os.Getenv("ZAOWU_PORT")
		if port == "" {
			port = "5000"
		}
		http.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		})
		_ = http.ListenAndServe("127.0.0.1:"+port, nil)
	case "exit":
		if m := os.Getenv("FAKE_APP_MARKER"); m != "" {
			_ = os.WriteFile(m, []byte("spawned"), 0644)
		}
		os.Exit(0)
	case "python-server":
		py := os.Getenv("FAKE_APP_PYTHON")
		script := os.Getenv("FAKE_APP_SCRIPT")
		if py == "" || script == "" {
			os.Exit(3)
		}
		// 自定位：把自身 exe 路径与 PID 传给 python（模拟 PyInstaller 应用的
		// sys.executable 语义——无论被谁拉起，子进程都知道自己是哪个版本；
		// PID 供子进程 watchdog 追踪本进程存活——venv 重定向器会使子进程
		// 的直接父进程是 python.exe 而非本进程）。
		exePath, _ := os.Executable()
		if dbg := os.Getenv("FAKE_APP_DEBUG"); dbg != "" {
			os.WriteFile(dbg, []byte("python-server start\n"), 0644)
		}
		cmd := exec.Command(py, script)
		cmd.Env = append(os.Environ(),
			"ZAOWU_SIM_EXE="+exePath,
			"ZAOWU_SIM_PARENT_PID="+strconv.Itoa(os.Getpid()),
		)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		err := cmd.Run()
		if dbg := os.Getenv("FAKE_APP_DEBUG"); dbg != "" {
			f, _ := os.OpenFile(dbg, os.O_APPEND|os.O_WRONLY, 0644)
			if f != nil {
				f.WriteString("python exited err=" + fmt.Sprint(err) + "\n")
				f.Close()
			}
		}
		if err != nil {
			if ee, ok := err.(*exec.ExitError); ok {
				os.Exit(ee.ExitCode())
			}
			os.Exit(4)
		}
		os.Exit(0)
	default:
		for { // 静默常驻（无响应的坏应用）；不能用 select{} —— 空 select 触发死锁退出
			time.Sleep(time.Hour)
		}
	}
}
