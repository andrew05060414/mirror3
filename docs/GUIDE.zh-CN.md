# Mirror3 使用教程（详细版）

面向 macOS / Windows / Linux 的镜像管理 CLI。你可以**只改需要的工具**，测速后自动选最快镜像，并支持一键回滚。

---

## 1. 这是什么？

在国内开发时，`npm`、`pip`、`cargo`、`docker` 等经常因为网络慢或不可达而失败。Mirror3 帮你：

| 能力 | 说明 |
|------|------|
| 按工具切换 | 只改 `npm`，不动 `pip` |
| 测速选最快 | 对候选镜像探测延迟与下载，选得分最低的 |
| 一键应用 | 写入各工具的配置文件 |
| 一键回滚 | 应用前自动备份，可 `restore` |
| 健康维护 | `verify` 记录历史，`prune` 禁用长期失败的镜像 |
| 可扩展 | 编辑 `mirrors.catalog.json` 增删镜像站 |

**不会做的事：** 不替你安装 Node/Python/Rust；不修改系统代理（Clash 等需自行配置）。

---

## 2. 环境要求

- **Python 3.8+**（macOS/Linux 通常已有 `python3`）
- **无需** `pip install` 第三方包（标准库即可）
- 需要能访问候选镜像 URL（若开了终端代理，测速结果会受代理影响）

### 2.1 获取项目

```bash
git clone <你的仓库地址> Mirror3
cd Mirror3
```

或直接使用已有目录，例如：

```bash
cd /Users/andrewwang/Code/Mirror3
```

### 2.2 如何运行

| 平台 | 推荐命令 |
|------|----------|
| macOS / Linux | `python3 mirror3.py <子命令>` 或 `./mirror3 <子命令>` |
| Windows | `python mirror3.py <子命令>` 或 `mirror3.bat <子命令>` |

查看全部子命令：

```bash
python3 mirror3.py --help
```

---

## 3. 项目结构（你需要知道的文件）

```
Mirror3/
├── mirror3.py              # 主程序
├── mirrors.catalog.json    # 镜像候选列表（可编辑）
├── mirror3 / mirror3.bat   # 启动脚本
├── README.md               # 快速说明
├── MIRROR_SOURCES.md       # 维护镜像列表时的参考来源
├── AGENTS.md               # 给 AI 助手读的操作手册
├── docs/GUIDE.zh-CN.md     # 本教程
├── templates/              # 定时任务模板
│   ├── macos/com.mirror3.daily.plist
│   └── windows/mirror3-daily.xml
└── .mirror3/               # 运行时数据（自动生成）
    ├── backups/            # apply 前的配置备份
    ├── reports/            # verify 报告
    ├── health.json         # 探测历史（供 prune 使用）
    └── disabled.json       # 被 prune 禁用的镜像名
```

**重要：** `apply` 只会改 catalog 里定义的**用户配置文件路径**（如 `~/.npmrc`），不会删你的项目代码。

---

## 4. 支持的工具一览

运行：

```bash
python3 mirror3.py list-tools
```

当前 catalog 通常包含：

`bun`, `cargo`, `composer`, `docker`, `gem`, `go`, `gradle`, `homebrew`, `maven`, `npm`, `nuget`, `pip`, `pnpm`, `rustup`, `uv`, `yarn`

查看某一工具的所有候选镜像：

```bash
python3 mirror3.py list-mirrors --tool pip
```

若某行带 `(disabled)`，表示已被 `prune` 禁用，`speedtest` / `apply` 会跳过。

---

## 5. 核心概念（必读）

### 5.1 `--tools`：只作用在你指定的工具上

```bash
python3 mirror3.py apply --tools npm,pip,uv
```

不写 `--tools` 时，多数命令会对 **catalog 里全部工具** 执行（`homebrew` 在 Windows 上会自动跳过）。

### 5.2 `--prefer`：强制指定某个镜像名

格式：`工具名=镜像名`，多个用英文逗号分隔。镜像名来自 `list-mirrors` 里的 `name` 字段。

```bash
python3 mirror3.py apply --tools npm,pip --prefer npm=npmmirror,pip=tuna
```

未写 `--prefer` 的工具会在**未禁用**的候选里测速选最快。

### 5.3 `--dry-run`：只预览，不写盘

```bash
python3 mirror3.py apply --tools npm,pip --dry-run
```

适合第一次使用前确认会改哪些路径、选哪个镜像。

### 5.4 备份与回滚

每次 `apply`（非 dry-run）会在 `.mirror3/backups/<时间戳>/` 保存该工具**修改前**的配置内容。

```bash
python3 mirror3.py list-snapshots
python3 mirror3.py restore --tools npm,pip          # 恢复最近一次
python3 mirror3.py restore --tools npm --snapshot 20260515-120000
```

### 5.5 verify / prune / disabled

| 命令 | 作用 |
|------|------|
| `verify` | 探测镜像，写报告到 `.mirror3/reports/`，并追加 `health.json` |
| `prune` | 若某镜像最近 **N 次** verify 全部失败，写入 `disabled.json`（不删 catalog） |
| `list-disabled` | 查看当前禁用列表 |

`prune --streak 3` 需要至少跑过 3 次 `verify` 且该镜像连续失败，才会禁用。

---

## 6. 命令参考（完整）

### 6.1 `list-tools`

列出 catalog 中所有工具。

```bash
python3 mirror3.py list-tools
```

---

### 6.2 `list-mirrors --tool <name>`

```bash
python3 mirror3.py list-mirrors --tool cargo
```

---

### 6.3 `status [--tools ...]`

查看本机配置文件里**当前**使用的镜像 URL。

```bash
python3 mirror3.py status
python3 mirror3.py status --tools npm,pip,go,docker
```

---

### 6.4 `speedtest [--tools ...] [--timeout 4] [--top 3]`

对候选镜像测速并打印排名（不修改配置）。

```bash
python3 mirror3.py speedtest --tools npm,pip --top 3 --timeout 4
```

---

### 6.5 `apply [--tools ...] [--prefer ...] [--timeout 4] [--dry-run]`

测速（或按 prefer）后写入配置。

```bash
# 推荐：先 dry-run
python3 mirror3.py apply --tools npm,pip,uv --dry-run

# 确认后再真正应用
python3 mirror3.py apply --tools npm,pip,uv
```

**应用后可能需要：**

- `docker`：重启 Docker Desktop
- `homebrew` / `rustup`：重新打开终端或 `source ~/.zshrc`
- 新开一个终端再跑 `npm install` / `pip install` 验证

---

### 6.6 `restore [--tools ...] [--snapshot ID] [--dry-run]`

```bash
python3 mirror3.py restore --tools npm
python3 mirror3.py restore --tools npm,pip --snapshot 20260515-154424
```

---

### 6.7 `list-snapshots`

```bash
python3 mirror3.py list-snapshots
```

---

### 6.8 `verify [--tools ...] [--markdown] [--timeout 4]`

```bash
python3 mirror3.py verify --markdown
python3 mirror3.py verify --tools npm,docker --timeout 5
```

选项：

- `--markdown`：额外生成 `.md` 报告
- `--no-update-health`：只出报告，不写 `health.json`
- `--all-mirrors`：连已 disabled 的也一起测

---

### 6.9 `prune [--streak 3] [--dry-run] [--clear] [--enable ...]`

```bash
python3 mirror3.py prune --streak 3 --dry-run
python3 mirror3.py prune --streak 3
python3 mirror3.py list-disabled
python3 mirror3.py prune --enable npm=npmjs
python3 mirror3.py prune --clear
```

---

### 6.10 `refresh --source-url <URL>`

从远程拉取新的 `mirrors.catalog.json`（团队可托管一份 JSON）。

```bash
python3 mirror3.py refresh --source-url "https://example.com/mirrors.catalog.json"
```

---

### 6.11 `schedule [--tools ...] [--source-url ...]`

打印 cron / Task Scheduler 示例命令（不自动安装定时任务）。

```bash
python3 mirror3.py schedule
```

建议日常链路：`verify` → `prune` → `apply`。

---

### 6.12 `doctor [--tools ...]`

尝试调用本机已安装的 `npm` / `go` / `cargo` 等命令做快速检查（可选）。

```bash
python3 mirror3.py doctor --tools npm,go,cargo
```

---

### 6.13 `list-disabled`

```bash
python3 mirror3.py list-disabled
```

---

## 7. 推荐工作流

### 7.1 第一次使用（5 分钟）

```bash
cd /path/to/Mirror3

python3 mirror3.py list-tools
python3 mirror3.py status --tools npm,pip,uv
python3 mirror3.py speedtest --tools npm,pip --top 2
python3 mirror3.py apply --tools npm,pip --dry-run
python3 mirror3.py apply --tools npm,pip
```

然后在新终端验证：

```bash
npm config get registry
python3 -m pip config list
```

不满意则：

```bash
python3 mirror3.py restore --tools npm,pip
```

---

### 7.2 国内日常开发（前端 + Python + Rust）

```bash
python3 mirror3.py apply --tools npm,pnpm,yarn,bun,pip,uv,go,cargo,rustup
```

---

### 7.3 定期自动维护（进阶）

每天一次（示例）：

```bash
python3 mirror3.py verify --markdown \
  && python3 mirror3.py prune --streak 3 \
  && python3 mirror3.py apply --tools npm,pnpm,yarn,pip,uv,go,cargo,docker
```

macOS 可参考 `templates/macos/com.mirror3.daily.plist`；Windows 参考 `templates/windows/mirror3-daily.xml`（需改路径为你的用户名）。

用 `schedule` 子命令生成带完整路径的 cron 一行命令。

---

### 7.4 只想测速、暂时不改配置

```bash
python3 mirror3.py speedtest --tools npm,pip,cargo --top 5
```

---

## 8. 自定义镜像列表

编辑 `mirrors.catalog.json` 中对应工具的 `mirrors` 数组：

```json
{
  "name": "my-mirror",
  "url": "https://example.com/simple"
}
```

每个工具还可配置：

- `config_path`：macos / linux / windows 下的配置文件路径
- `test_path`：测速时请求的路径后缀
- `format`：写入配置的格式（如 `line_kv`、`ini_global`、`toml_uv` 等）

维护新镜像站时，可参考 `MIRROR_SOURCES.md` 中的公开来源（MirrorZ、TUNA、USTC、各云厂商文档等）。

修改 catalog 后无需重启，下次命令自动读取。

---

## 9. 各工具实际会改哪些文件？

| 工具 | 典型配置文件（macOS） |
|------|------------------------|
| npm / pnpm / yarn | `~/.npmrc` |
| bun | `~/.bunfig.toml` |
| pip | `~/.config/pip/pip.conf` |
| uv | `~/.config/uv/uv.toml` |
| go | `~/Library/Application Support/go/env` |
| cargo | `~/.cargo/config.toml` |
| rustup | `~/.zshrc`（追加环境变量） |
| homebrew | `~/.zshrc`（`HOMEBREW_BOTTLE_DOMAIN`） |
| maven | `~/.m2/settings.xml` |
| gradle | `~/.gradle/init.gradle` |
| nuget | `~/.nuget/NuGet/NuGet.Config` |
| gem | `~/.gemrc` |
| composer | `~/.config/composer/config.json` |
| docker | `~/.docker/daemon.json` |

Windows 路径见 catalog 里 `windows` 字段（如 `%USERPROFILE%\.npmrc`）。

**注意：** `npm`、`pnpm`、`yarn` 共用 `~/.npmrc` 的 `registry=` 行；对三者分别 `apply` 会覆盖同一键，通常三者用同一镜像即可。

---

## 10. 常见问题

### Q1：`speedtest` 全部 FAIL？

- 检查网络 / 代理（`echo $https_proxy`）
- 增大超时：`--timeout 8`
- 对 docker：部分镜像返回 401 仍可能可用，verify 已做特殊处理

### Q2：`apply` 后安装仍然很慢？

- 确认 `status` 里 URL 已变
- 部分工具还有缓存（npm cache、pip cache），与镜像无关
- `go` 需确认 `go env GOPROXY`；`rustup` 需新终端

### Q3：`prune` 说没有匹配项？

- 先多次运行 `verify` 积累 `health.json`
- 用 `--dry-run` 看会禁用谁：`prune --streak 3 --dry-run`

### Q4：想恢复官方源？

```bash
python3 mirror3.py restore --tools npm,pip
# 或 apply 时 prefer 官方镜像名，例如：
python3 mirror3.py apply --tools npm --prefer npm=npmjs
```

### Q5：误禁用了某个镜像？

```bash
python3 mirror3.py prune --enable pip=pypi
```

### Q6：公司内网只想用自建源？

在 `mirrors.catalog.json` 里只保留你们内网 URL，或 `apply --prefer` 固定名称。

---

## 11. 安全与隐私

- 备份保存在本机 `.mirror3/backups/`，不上传
- `verify` 仅对镜像 URL 发 HTTP GET，不上传你的项目代码
- 不要将含内网地址的 catalog 提交到公开仓库（若含敏感信息）

---

## 12. 获取帮助

- 快速命令：`README.md`
- AI 辅助使用：根目录 `AGENTS.md`（可发给 Cursor / Claude 等）
- 镜像来源调研：`MIRROR_SOURCES.md`

---

## 13. 命令速查表

| 意图 | 命令 |
|------|------|
| 我能管哪些工具？ | `list-tools` |
| 现在用的什么源？ | `status` |
| 谁最快？ | `speedtest --tools ...` |
| 切换镜像 | `apply --tools ...` |
| 先别看改什么 | `apply --dry-run` |
| 改坏了 | `restore --tools ...` |
| 健康检查 | `verify --markdown` |
| 去掉烂镜像 | `prune --streak 3` |
| 看谁被禁了 | `list-disabled` |
| 定时任务示例 | `schedule` |
