package main

import (
	"io"
	"log"
	"os"
	"path/filepath"
)

// runtimeDataFiles / runtimeDataDirs 为旧扁平布局写入 _internal 内的运行期数据
// （早期 BASE_DIR = dirname(dirname(abspath(__file__))) 在 PyInstaller 单文件夹
// 中解析到 _internal，providers.json 等实际落在 _internal 内）。首启迁移时需
// 搬运到部署根，否则升级后配置（含 API Key）静默丢失。清单与 zaowu_paths.py
// 的 markers 对齐（versions.json 由启动器自建，不在其列）。
var runtimeDataFiles = []string{
	"settings.json",
	"conversations.json",
	"projects.json",
	"providers.json",
	"chat_config.json",
}

var runtimeDataDirs = []string{"data", "logs"}

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
	// 迁移旧 _internal 内的运行期数据到部署根（必须在 rename _internal 之前，
	// 否则迁移源随目录一起被移走）。best-effort：失败不阻断主转换。
	migrateLegacyRuntimeData(root)
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

// migrateLegacyRuntimeData 将旧扁平布局 _internal 内的运行期数据复制到部署根。
// 目标已存在则跳过（幂等：不覆盖部署根既有数据）；复制失败仅记日志不阻断。
func migrateLegacyRuntimeData(root string) {
	internal := filepath.Join(root, "_internal")
	for _, name := range runtimeDataFiles {
		src := filepath.Join(internal, name)
		dst := filepath.Join(root, name)
		if _, err := os.Stat(src); err != nil {
			continue // 源不存在，无需迁移
		}
		if _, err := os.Stat(dst); err == nil {
			continue // 部署根已有，不覆盖
		}
		if err := copyFile(src, dst); err != nil {
			msg := "迁移 %s 失败: %v"
			if name == "providers.json" {
				msg = "警告: 迁移 %s 失败: %v（可从 versions/v0/_internal/%s 手动恢复）"
				log.Printf(msg, name, err, name)
			} else {
				log.Printf(msg, name, err)
			}
		}
	}
	for _, name := range runtimeDataDirs {
		src := filepath.Join(internal, name)
		dst := filepath.Join(root, name)
		if fi, err := os.Stat(src); err != nil || !fi.IsDir() {
			continue
		}
		if _, err := os.Stat(dst); err == nil {
			continue
		}
		if err := copyDir(src, dst); err != nil {
			log.Printf("迁移目录 %s 失败: %v", name, err)
		}
	}
}

// copyFile 复制单个文件并落盘（Sync），避免断电丢失迁移数据。
func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	return out.Sync()
}

// copyDir 递归复制目录（保留目录结构，文件复制复用 copyFile）。
func copyDir(src, dst string) error {
	return filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if info.IsDir() {
			return os.MkdirAll(target, info.Mode())
		}
		return copyFile(path, target)
	})
}
