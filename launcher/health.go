package main

import (
	"net/http"
	"os"
	"time"
)

// ResolvePort 返回后端端口：ZAOWU_PORT 环境变量优先，缺省 5000
// （与应用侧 zaowu_paths.get_server_port() 一致；环境变量自动继承到子进程）。
func ResolvePort() string {
	if p := os.Getenv("ZAOWU_PORT"); p != "" {
		return p
	}
	return "5000"
}

var healthClient = &http.Client{Timeout: 2 * time.Second}

// healthOnce 单次健康检查请求。
func healthOnce(port string) bool {
	resp, err := healthClient.Get("http://127.0.0.1:" + port + "/api/health")
	if err != nil {
		return false
	}
	resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// WaitHealthy 轮询健康检查直到成功或超时（间隔 150ms，对齐应用侧
// main.py 的 _wait_for_server）。
func WaitHealthy(port string, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if healthOnce(port) {
			return true
		}
		time.Sleep(150 * time.Millisecond)
	}
	return healthOnce(port)
}
