// 坏应用：静默常驻、无视环境变量（模拟新版本启动后无响应的场景，
// 用于端到端回滚验证——被启动器拉起的「新版本」必须是坏 exe）。
package main

import "time"

func main() {
	for {
		time.Sleep(time.Hour)
	}
}
