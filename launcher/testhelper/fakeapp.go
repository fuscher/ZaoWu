// 假应用：供启动器验证矩阵使用（P5 端到端模拟也复用）。
// 行为由环境变量控制（启动器 SpawnApp 不带参数，环境变量自动继承）：
//   FAKE_APP_MODE=serve  监听 ZAOWU_PORT（缺省 5000）提供 /api/health
//   FAKE_APP_MODE=exit   写 FAKE_APP_MARKER 文件后立即退出
//   其他/缺省            静默常驻（模拟无响应的坏应用）
package main

import (
	"net/http"
	"os"
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
	default:
		for { // 静默常驻（无响应的坏应用）；不能用 select{} —— 空 select 触发死锁退出
			time.Sleep(time.Hour)
		}
	}
}
