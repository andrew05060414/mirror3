# Mirror3

一个跨平台（macOS / Windows / Linux）的镜像管理 CLI，支持：

- 按工具选择镜像（不是全量强制切换）
- 对候选镜像测速，自动选择最快
- 一键 `apply` 切换
- 一键 `restore` 回滚到上次备份
- 可通过 `refresh` 拉取远程最新镜像目录（catalog）
- `verify` 批量探测并写入报告 / 健康历史
- `prune` 按连续失败次数禁用劣质镜像（不删 catalog）

## 支持工具（当前）

- `npm`
- `pnpm`
- `yarn`
- `bun`
- `pip`
- `uv`
- `go`
- `cargo`
- `rustup`
- `gradle`
- `nuget`
- `gem`
- `composer`
- `homebrew`（当前管理 `HOMEBREW_BOTTLE_DOMAIN`）
- `maven`
- `docker`

> 镜像源定义在 `mirrors.catalog.json`，你可以自行增减候选项。

## 文档

| 读者 | 文件 |
|------|------|
| 人类（详细教程） | [docs/GUIDE.zh-CN.md](docs/GUIDE.zh-CN.md) |
| AI 助手（操作手册） | [AGENTS.md](AGENTS.md) |
| 镜像来源维护 | [MIRROR_SOURCES.md](MIRROR_SOURCES.md) |

## 快速开始

```bash
cd /Users/andrewwang/Code/Mirror3
python3 mirror3.py list-tools
```

## 常用命令

### 1) 查看当前配置状态

```bash
python3 mirror3.py status --tools npm,pnpm,pip,uv
```

### 2) 对某些工具测速（自动排名）

```bash
python3 mirror3.py speedtest --tools npm,pip,uv --top 3 --timeout 4
```

Rust/Bun 示例：

```bash
python3 mirror3.py speedtest --tools bun,cargo,rustup --top 2
```

### 3) 自动选最快镜像并应用

```bash
python3 mirror3.py apply --tools npm,pip,uv
```

全工具一键（按测速自动选最快）：

```bash
python3 mirror3.py apply
```

### 4) 指定某工具固定镜像，其余自动最快

```bash
python3 mirror3.py apply --tools npm,pip,uv --prefer npm=npmmirror,pip=tuna
```

### 5) 仅预览，不实际修改

```bash
python3 mirror3.py apply --tools npm,pip --dry-run
```

### 6) 一键回滚（恢复最近一次快照）

```bash
python3 mirror3.py restore --tools npm,pip,uv
```

### 7) 查看历史快照

```bash
python3 mirror3.py list-snapshots
```

### 8) 拉取远程最新镜像目录

```bash
python3 mirror3.py refresh --source-url "https://example.com/mirrors.catalog.json"
```

> `refresh` 用于“定期获取最新 mirror”。你可以托管一份团队维护的 catalog JSON（例如 GitHub Raw URL），然后定时同步。

### 9) 生成定时任务命令（macOS/Windows）

```bash
python3 mirror3.py schedule
```

带远程 catalog 自动刷新：

```bash
python3 mirror3.py schedule --source-url "https://example.com/mirrors.catalog.json"
```

模板文件：

- `templates/macos/com.mirror3.daily.plist`
- `templates/windows/mirror3-daily.xml`

### 10) 健康检查 + 自动禁用劣质镜像

探测全部候选并更新健康历史（默认写入 `.mirror3/health.json`）：

```bash
python3 mirror3.py verify --markdown
```

连续 3 次 `verify` 都失败的镜像会被标记禁用（写入 `.mirror3/disabled.json`，不修改 catalog）：

```bash
python3 mirror3.py prune --streak 3
```

查看 / 恢复禁用项：

```bash
python3 mirror3.py list-disabled
python3 mirror3.py prune --enable npm=npmjs
python3 mirror3.py prune --clear
```

推荐日常链路：

```bash
python3 mirror3.py verify --markdown && python3 mirror3.py prune --streak 3 && python3 mirror3.py apply --tools npm,pip,uv
```

报告输出目录：`.mirror3/reports/verify-<timestamp>.json`（以及可选 `.md`）。

## 设计说明

- 所有修改前都会自动备份到 `.mirror3/backups/<timestamp>/`
- `restore` 默认使用 `LATEST` 快照
- `--tools` 允许你只作用在需要的工具上
- 采用纯 Python 标准库实现，无第三方依赖
- 你的系统若设置了代理（如 Clash），测速结果会受当前代理策略影响
- 对于 `cargo`（`sparse+https://...`）和 `go`（`...,direct`）已做测速兼容处理
- `speedtest` / `apply` 会跳过 `prune` 禁用的镜像；`list-mirrors` 会标注 `(disabled)`
- 镜像来源维护参考：`MIRROR_SOURCES.md`
