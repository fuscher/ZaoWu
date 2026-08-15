package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSaveAndLoadRoundtrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "versions.json")

	cfg := &VersionsConfig{
		Schema:     1,
		Current:    "v1.2.0",
		LastGood:   strPtr("v1.1.0"),
		Pending:    nil,
		LastResult: strPtr("ok"),
	}
	if err := SaveVersionsAtomic(path, cfg); err != nil {
		t.Fatalf("save: %v", err)
	}
	if _, err := os.Stat(path + ".tmp"); !os.IsNotExist(err) {
		t.Fatalf("tmp file left behind: %v", err)
	}

	loaded, err := LoadVersions(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if loaded.Schema != 1 || loaded.Current != "v1.2.0" ||
		deref(loaded.LastGood) != "v1.1.0" ||
		loaded.Pending != nil || deref(loaded.LastResult) != "ok" {
		t.Fatalf("roundtrip mismatch: %+v", loaded)
	}
}

func TestSaveOverwritesExisting(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "versions.json")
	if err := SaveVersionsAtomic(path, &VersionsConfig{Current: "v1"}); err != nil {
		t.Fatalf("save1: %v", err)
	}
	// 目标已存在时同样原子替换（Windows MoveFileEx REPLACE_EXISTING）
	if err := SaveVersionsAtomic(path, &VersionsConfig{Current: "v2"}); err != nil {
		t.Fatalf("save2: %v", err)
	}
	loaded, _ := LoadVersions(path)
	if loaded.Current != "v2" {
		t.Fatalf("expected v2, got %q", loaded.Current)
	}
}

func TestLoadMissingReturnsErrVersionsMissing(t *testing.T) {
	_, err := LoadVersions(filepath.Join(t.TempDir(), "versions.json"))
	if err != errVersionsMissing {
		t.Fatalf("expected errVersionsMissing, got %v", err)
	}
}

func TestLoadCorruptReturnsError(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "versions.json")
	if err := os.WriteFile(path, []byte("{broken"), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadVersions(path); err == nil {
		t.Fatal("expected error for corrupt json")
	}
}

func TestLoadIgnoresUnknownFields(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "versions.json")
	// schema 升级后旧启动器忽略未知字段、缺失字段按零值处理
	data := `{"schema": 2, "current": "v1.2.0", "extra_field": 123}`
	if err := os.WriteFile(path, []byte(data), 0644); err != nil {
		t.Fatal(err)
	}
	cfg, err := LoadVersions(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if cfg.Current != "v1.2.0" || cfg.LastGood != nil || cfg.Pending != nil {
		t.Fatalf("tolerance mismatch: %+v", cfg)
	}
}
