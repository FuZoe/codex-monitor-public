<p align="center">
  <a href="README.md">English</a> | <strong>中文</strong>
</p>

# Codex Monitor

在手机上实时监控 Codex CLI 的工作状态和额度用量。

桌面端运行一个轻量 HTTP 服务，解析 `~/.codex/sessions/` 下的 JSONL 会话日志，
将事件映射为状态（思考 → 写代码 → 完成 → 空闲 → 休眠），
手机端通过同局域网轮询接口，用 Clawd 动画角色实时展示当前状态。

## 项目结构

```
desktop/           HTTP 状态 API + JSONL 实时监控服务
android/           原生 Android 全屏客户端
scripts/           Windows PowerShell 辅助脚本
dist/              本地 APK 构建产物（不纳入 Git）
.github/workflows/ GitHub Actions 自动构建 & Release
```

## 快速开始

### 1. 启动桌面端服务

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-codex-monitor-server.ps1
```

服务监听：

- **TCP `8767`** — HTTP API（`/api/status`）及 Web 监控页面
- **UDP `45777`** — Android 自动发现广播

> 如果 Windows 防火墙提示，请允许 Python 访问专用网络。

### 2. 安装 Android 客户端

#### 方式一：从 GitHub Releases 下载

前往 [Releases](https://github.com/FuZoe/codex_monitor/releases) 页面，
下载最新的 `codex-monitor-android.apk` 安装。

#### 方式二：本地构建后安装

```
dist/codex-monitor-android.apk
```

运行下方构建脚本后，使用 `adb install` 或直接传到手机安装。

### 3. 连接

确保手机和运行服务的电脑处于**同一 Wi-Fi 网络**。
打开 App 后会自动发送发现广播，找到桌面服务后每 2.5 秒轮询状态。

## 实时状态监控（v2.0）

桌面端内置 `CodexSessionMonitor`，持续监控 `~/.codex/sessions/` 目录下的
JSONL rollout 文件，将 Codex 事件实时映射为以下状态：

| 动画状态 | 含义 | 触发事件示例 |
|---------|------|------------|
| thinking | 思考中 | `task_started`, `response.created` |
| typing / working | 写代码中 | `agent_message`, `patch_apply_end` |
| building | 构建中 | `function_call` |
| juggling | 多任务 | 多个会话同时活跃 |
| sweeping | 整理中 | `context_compacted` |
| happy | 刚完成 | `task_complete`, `response.completed` |
| error | 出错 | `error` |
| idle | 空闲 | 30 秒无新事件 |
| sleeping | 休眠 | 5 分钟无新事件 |

手机端收到的 API 响应包含：

- `animation` — 对应的 Clawd 角色 GIF 动画名称
- `statusLabel` — 中文状态短语
- `headline` / `detail` — 状态描述
- `freshness` — 距上次更新的人类可读时间
- `quotaSource` — 额度数据来源（`live-jsonl` / `manual` / `stale`）

## 额度显示

额度数据优先从 JSONL 中的 `token_count` 事件实时提取（标记为 `quotaSource: "live-jsonl"`）。
如果没有实时数据，则回退到 `desktop/codex-status.json` 中的手动值（标记为 `quotaSource: "manual"`）。

Codex 使用双窗口额度模型：

- **`five_hour`**：滚动 5 小时用量窗口
- **`weekly`**：每周用量窗口

手动更新额度：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-codex-status.ps1 `
  -Status working -Title 工作中 -Task "正在处理任务" `
  -FiveHourUsed 30 -FiveHourLimit 100 -WeeklyUsed 120 -WeeklyLimit 500
```

也可以直接传入剩余百分比：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-codex-status.ps1 `
  -Status working -Title 工作中 -Task "正在处理任务" `
  -FiveHourRemainingPercent 42 -WeeklyRemainingPercent 84
```

## 构建 APK

本项目直接使用 Android SDK 编译，不依赖 Gradle：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-codex-mobile-apk.ps1
```

构建产物输出到 `dist/codex-monitor-android.apk`。APK 属于 Release/本地构建产物，不纳入源码仓库版本控制。

## 第三方素材

手机端的 Clawd 角色动画 GIF（`android/assets/clawd/gif/`）来自
[clawd-on-desk](https://github.com/rullerzhou-afk/clawd-on-desk) 项目，使用 MIT 许可证。

JSONL 事件到状态的映射逻辑参考了 `clawd-on-desk` 中的 `codex.js` 和 `codex-log-monitor.js`。

详见 [NOTICE.md](NOTICE.md)。

## 免责声明

本项目**不是** OpenAI 或 Codex 的官方产品，是一个用于在局域网内监控本地 Codex CLI 会话的个人工具。
