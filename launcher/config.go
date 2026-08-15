package main

import (
	"encoding/json"
	"errors"
	"os"
)

// VersionsConfig 对应部署根 versions.json。未知字段忽略、缺失字段按零值
// 处理（schema 向后兼容）。
//
// 写入职责分离（硬性约束，与应用侧 services/versions_config.py 注释互相
// 绑定，任何一方变更不得破坏对方既有格式）：
//   - 启动器只写 current / last_good / last_result，并把 pending 置回 null；
//   - 应用只写 pending，并读 last_result。
type VersionsConfig struct {
	Schema     int     `json:"schema"`
	Current    string  `json:"current"`
	LastGood   *string `json:"last_good"`
	Pending    *string `json:"pending"`
	LastResult *string `json:"last_result"`
}

// errVersionsMissing 表示 versions.json 不存在（普通启动路径触发
// 旧布局 bootstrap 检测的前提条件之一）。
var errVersionsMissing = errors.New("versions.json missing")

// LoadVersions 读取版本配置。文件缺失返回 errVersionsMissing；
// JSON 非法返回解析错误；其余 IO 错误原样返回。
func LoadVersions(path string) (*VersionsConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, errVersionsMissing
		}
		return nil, err
	}
	var cfg VersionsConfig
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}

// SaveVersionsAtomic 写 versions.json.tmp 后原子替换，任何时刻文件内容完整。
func SaveVersionsAtomic(path string, cfg *VersionsConfig) error {
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func strPtr(s string) *string { return &s }

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}
