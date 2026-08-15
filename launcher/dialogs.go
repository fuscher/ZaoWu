package main

import (
	"os"
	"syscall"
	"unsafe"
)

// ShowError 弹出系统错误对话框。启动器以 -H windowsgui 构建（无控制台），
// 错误必须走弹窗呈现。设置 ZAOWU_LAUNCHER_NOGUI=1 时改为输出 stderr
// （自动化验证用，避免模态弹窗阻塞）。
func ShowError(title, msg string) {
	if os.Getenv("ZAOWU_LAUNCHER_NOGUI") == "1" {
		_, _ = os.Stderr.WriteString("[" + title + "] " + msg + "\n")
		return
	}
	user32 := syscall.NewLazyDLL("user32.dll")
	proc := user32.NewProc("MessageBoxW")
	proc.Call(
		0,
		uintptr(unsafe.Pointer(syscall.StringToUTF16Ptr(msg))),
		uintptr(unsafe.Pointer(syscall.StringToUTF16Ptr(title))),
		0x10, // MB_ICONERROR
	)
}
