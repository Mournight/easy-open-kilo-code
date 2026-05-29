# Easy-Open-Kilo-Code

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-windows%20%7C%20macos%20%7C%20linux-lightgrey.svg)](https://github.com/easy-open-kilo-code)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

一个为 **OpenCode** 和 **Kilo Code** 打造的跨平台、高分屏（DPI）适配的图形化配置编辑器。支持一键切换品牌，自动更新实际读写路径，完美支持 MCP 服务器、上下文压缩、提供者模型、API 密钥与提示词文件的精细管理。

---

## ✨ 核心特性

- **🏷️ 双品牌原生支持**：左上角首创“品牌融入标题”设计，支持在 **OpenCode** 与 **Kilo Code** 之间一键下拉切换。
- **🔄 路径与配置无缝重载**：切换品牌时，软件会自动、即时地更新所有 UI 路径、底层配置文件（`opencode.jsonc` ↔ `kilo.jsonc`）、密钥库（`auth.json`）和提示词（`AGENTS.md`），并自动加载对应配置。
- **📊 缓冲区单位统一**：不仅上下文和最大输出，现在将“上下文压缩缓冲区”单位也全面统一为更易读的 **K (千字节/千 Token)**，保持界面参数展示的一致性。
- **🌐 强大的 MCP 服务管理**：可视化管理 MCP (Model Context Protocol) 服务的类型（local/remote）、连接参数、启用状态，并提供 JSON 配置文件的精准导入与双击编辑功能。
- **🧠 完美的上下文压缩**：直观配置自动压缩（Auto Compaction）、清理旧输出（Prune Old Output）以及压缩缓冲阀值（Reserved Token Buffer）。
- **🧪 模型测速与连通性测试**：内嵌单模型可用性测试及流式输出（Stream）测速组件，帮助开发人员快速验证 API 连通性。
- **🖥️ 极佳的跨平台 DPI 适配**：基于 `customtkinter` 研发，在 Windows、macOS 和 Linux 上均可完美缩放，支持暗黑与明亮模式的系统自动跟随。

---

## 📂 品牌配置路径对照表

在切换品牌时，编辑器会自动读写以下对应的本地物理路径：

| 维度 / 品牌 | OpenCode | Kilo Code |
| :--- | :--- | :--- |
| **主配置文件** | `~/.config/opencode/opencode.jsonc` | `~/.config/kilo/kilo.jsonc` |
| **API 密钥库** | `~/.local/share/opencode/auth.json` | `~/.local/share/kilo/auth.json` |
| **提示词文件** | `~/.config/opencode/AGENTS.md` | `~/.config/kilo/AGENTS.md` |
| **$schema 规范**| `https://opencode.ai/config.json` | `https://app.kilo.ai/config.json` |

---

## 🚀 快速开始

### 1. 安装依赖

该项目依赖 `customtkinter` 提供精美的图形界面，以及 `requests` 进行模型探测和测速：

```bash
pip install customtkinter requests
```

### 2. 运行应用

在项目根目录下直接使用 Python 启动：

```bash
python easy-open-kilo-code.pyw
```
*(注：`.pyw` 后缀在 Windows 环境下双击运行将隐藏命令行窗口)*

---

## 🛠️ 功能模块详解

### 1. Provider 管理
- 支持管理 OpenAI-Compatible 的服务提供者。
- 支持探查（Probe）服务端支持的所有模型并进行批量选择导入。
- 支持配置模型的上下文大小（K）、最大输出、图像输入支持、思考参数（reasoningEffort 等）及强度的多变体（variants）配置。

### 2. MCP 与上下文
- 一键导入或添加各种 Local/Remote 类型的 MCP 节点。
- 配置上下文压缩功能。缓冲区参数直接输入数字（例如 `20` 即表示 `20K`），保存时会自动乘以 1000 写入配置文件，读取时也会自动逆向还原。

### 3. 全局提示词 (AGENTS.md)
- 集成了轻量级文本编辑器，支持对对应品牌的提示词定义文件（`AGENTS.md`）进行可视化的快速查阅、编辑、重新加载与保存。

---

## 🤝 参与贡献

我们欢迎并感谢所有的 Issues 和 Pull Requests！
1. Fork 本仓库。
2. 创建您的特性分支 (`git checkout -b feature/AmazingFeature`)。
3. 提交您的修改 (`git commit -m 'Add some AmazingFeature'`)。
4. 推送到该分支 (`git push origin feature/AmazingFeature`)。
5. 开启一个 Pull Request。

---

## 📄 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
