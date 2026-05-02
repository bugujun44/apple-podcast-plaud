# apple-podcast-plaud

> Apple Podcasts → Plaud → 文字。自动检测已下载的播客剧集，上传到 Plaud 转写，返回逐字稿给任意 AI 编程助手。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange)](#)
[![PyPI](https://img.shields.io/pypi/v/apple-podcast-plaud)](https://pypi.org/project/apple-podcast-plaud/)

[English](README.md) | **中文**

## 它做什么

你在 Mac 上用 Apple Podcasts 下载了一期播客，然后对你的 AI 编程助手（Claude Code、Cursor、Cline 等）说"帮我转写这期播客"。它会：

1. 从 Apple Podcasts 的 SQLite 数据库中找到已下载的 `m4a` 文件
2. 自动上传到你的 [Plaud](https://www.plaud.ai) 账户（需要 Pro 订阅，使用你已有的转写额度，本工具本身免费）
3. 等待 Plaud 完成转写 + AI 摘要
4. 将逐字稿 Markdown、AI 摘要 Markdown 和元数据 JSON 写入本地目录
5. 输出 JSON 信封到 stdout —— 你的 AI 助手接收后决定下一步（写文章、导入知识库、搜索……）

**规划中：** 未来版本将支持英文播客直接使用 Apple 原生 TTML 转录（免费、即时，不消耗 Plaud 额度）。

## 为什么做这个

- Apple Podcasts 不为中文（及其他非英语）播客生成原生转录。Plaud Pro 的中文 ASR 效果好，还有 AI 摘要。
- 现有的 Plaud 逆向工具（TypeScript / Python）无法与 Apple Podcasts 工作流无缝集成。
- 本工具把两者打通，且**不绑定任何特定 AI 助手**：它只生产转录文件并告诉你路径，下游由你决定。

## 当前状态

**Alpha 阶段。** API 可能变动。详见 [CHANGELOG.md](CHANGELOG.md)。

## 安装

```bash
pip install apple-podcast-plaud
```

本地开发（推荐）：

```bash
git clone https://github.com/bugujun44/apple-podcast-plaud
cd apple-podcast-plaud
./scripts/dev-install.sh
source .venv/bin/activate
apb --version
```

## 快速开始

### 1. 一次性认证 —— 二选一

#### 方式 A：邮箱 + 密码登录

```bash
apb auth login                   # 交互式输入邮箱和密码
```

如果你的 Plaud 账号是 Google/Apple 登录注册的（没设过密码），这个方式不行，请用方式 B。

#### 方式 B：从浏览器粘贴 Token

适用于所有账号类型。

1. 登录 <https://web.plaud.ai>
2. 打开开发者工具 → **Console**
3. 运行：
   ```js
   copy(localStorage.getItem('tokenstr'))
   ```
4. 保存 Token：
   ```bash
   apb auth set-token             # 粘贴后按 Ctrl-D
   ```

#### 验证

```bash
apb auth status
# region: apac
# expires: 2027-02-19 (in 299 days)
# server check: ok
```

Token 有效期约 10 个月，过期后用同样方式重新获取。

### 2. 使用（通过 MCP Server，用自然语言操作）

下面这行命令的作用是把本工具注册为 Claude Code 的插件，注册后 Claude 就知道怎么帮你转写播客了。只需要运行一次：

```bash
claude mcp add --scope user --transport stdio podcast-transcribe -- uvx apple-podcast-plaud mcp
```

重启 Claude Code 后，直接对话即可：

- "列出我最近下载的播客"
- "帮我转写那期关于逆商的播客"
- "查看我的 Plaud 登录状态"

首次使用如果还没登录，Claude 会引导你在对话中完成认证，不需要离开对话窗口。

## 输出格式（JSON 信封）

```json
{
  "status": "ok",
  "podcast": "高情商沟通话术：自在表达，想说就说",
  "episode": "320 逆商：我们该如何应对坏事件？",
  "language": "zh",
  "duration_sec": 1815,
  "segment_count": 48,
  "out_dir": "/Users/.../Documents/podcasts/2026-04-26-逆商",
  "files": {
    "transcript_md": ".../transcript.md",
    "summary_md": ".../summary.md",
    "raw_json": ".../transcript.raw.json",
    "metadata_json": ".../metadata.json"
  },
  "source": "plaud",
  "plaud_recording_id": "e4eb71b...",
  "elapsed_sec": 187
}
```

## 架构

```
src/apple_podcast_plaud/
├── plaud/      # 通用 Plaud API 客户端（多区域路由、认证、录音、转写）
├── bridge/     # Apple Podcasts ↔ Plaud 桥接（SQLite 查询、语言检测、
│               # 输出格式化、CLI）
└── mcp/        # MCP Server（Claude Code 集成，plaud/ 和 bridge/ 的薄包装）
```

## 致谢

本项目独立实现，但 API 接口和请求格式参考了以下优秀的逆向工程项目：

- [`arbuzmell/plaud-api`](https://github.com/arbuzmell/plaud-api) — MIT 协议，Python Plaud 客户端
- [`sergivalverde/plaud-toolkit`](https://github.com/sergivalverde/plaud-toolkit) — MIT 协议，TypeScript Plaud 客户端

Apple Podcasts SQLite/TTML 结构参考：

- [`mattdanielmurphy/apple-podcast-transcript-extractor`](https://github.com/mattdanielmurphy/apple-podcast-transcript-extractor)
- [`cvonste2/apple-podcast-transcript-tool`](https://github.com/cvonste2/apple-podcast-transcript-tool)
- [`dado3212/apple-podcast-transcripts`](https://github.com/dado3212/apple-podcast-transcripts)

所有商标归其各自所有者所有。本项目与 Plaud Inc. 或 Apple Inc. 无关。此处使用的 Plaud API 是从公开网页应用逆向而来，可能随时变更。

## 许可证

MIT。详见 [LICENSE](LICENSE)。
