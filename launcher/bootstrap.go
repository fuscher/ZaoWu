package main

import (
	"os"
	"path/filepath"
)

// Bootstrap 将旧扁平布局（ZaoWu.exe + _internal/ 与启动器同目录）转换为
// 版本化布局：移入 versions/v0/，写 versions.json，运行期数据原样保留。
//
// 调用方须先做「应用未在运行」检查（anyZaoWuRunning）——现代 Windows 允许
// 重命名运行中的 exe，不能依赖移动失败探测。此处移动顺序先 _internal 后
// exe；exe 移动失败（文件被占用等）时回滚第一步，保证无半转换状态。
func Bootstrap(root string) error {
	exe := filepath.Join(root, "ZaoWu.exe")
	internal := filepath.Join(root, "_internal")
	versionsDir := filepath.Join(root, "versions")
	v0 := filepath.Join(versionsDir, "v0")

	if err := os.MkdirAll(v0, 0755); err != nil {
		return err
	}
	if err := os.Rename(internal, filepath.Join(v0, "_internal")); err != nil {
		return err
	}
	if err := os.Rename(exe, filepath.Join(v0, "ZaoWu.exe")); err != nil {
		_ = os.Rename(filepath.Join(v0, "_internal"), internal)
		return err
	}

	cfg := &VersionsConfig{
		Schema:   1,
		Current:  "v0",
		LastGood: nil,
		Pending:  nil,
	}
	return SaveVersionsAtomic(filepath.Join(root, "versions.json"), cfg)
}
