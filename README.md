# Easy-Open-Kilo-Code

一个为 **OpenCode** 和 **KiloCode** 打造的跨平台图形化配置编辑器。单文件，极致轻量。

支持一键切换品牌，自动更新实际读写路径，完美支持高级模型参数、MCP 服务器、上下文压缩、全局提示词文件的精细管理。

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install customtkinter requests platformdirs
```

### 2. 运行应用

```bash
python easy-open-kilo-code.pyw
```

*(注：`.pyw` 后缀在 Windows 环境下双击运行将隐藏命令行窗口)*

---

## ✨ 核心特性

### 🏷️ 双品牌支持
- 左上角品牌下拉框融入标题设计，一键切换 OpenCode / KiloCode
- 切换时自动更新所有读写路径（配置文件、密钥库、提示词文件）
- 支持一键同步配置到另一个品牌（精准合并，保留目标品牌特有字段）

### 💾 智能保存
- **自动保存**：开启后，所有配置变更自动保存（1 秒轮询检测）
- **同步修改**：开启后，所有变更同时写入两个品牌
- 程序设置（品牌选择、开关状态）自动持久化，下次启动自动恢复

### 🔑 密钥管理
- 自动读取各品牌的 auth.json 密钥
- API Key 默认隐藏，支持点击"显示"按钮查看明文

---

## 🛠️ 功能模块详解

### 1. Provider 管理
- 支持创建、删除、重命名 Provider
- 自动探测服务端支持的模型列表
- 连通性测试和流式输出测速
- 支持 OpenAI 标准协议和 Responses 专有协议
- 每个模型支持配置：
  - 上下文大小（K）、最大输出
  - 图像输入支持
  - 推理字段名（reasoningEffort / thinking）
  - 5 个推理强度变体（xhigh / high / medium / low / none）

### 2. MCP 与上下文
- 一键导入 MCP 配置，支持多种格式：
  - OpenCode / KiloCode 标准格式（command 为数组）
  - Cursor / Windsurf 格式（command 为字符串 + args 数组）
  - 自动推断类型（local / remote）
  - 自动补全 enabled 字段
- 支持批量导入、手动添加、启用/禁用切换
- 上下文压缩配置：
  - 自动压缩开关
  - 清理旧输出开关
  - 缓冲区大小（单位：K）

### 3. 全局提示词 (AGENTS.md)
- 集成轻量级文本编辑器
- 支持查看、编辑、重新加载、保存
- 修复了 CTkTextbox 粘贴重复问题

---

## 📂 配置路径对照

| 项目 | OpenCode | KiloCode |
| :--- | :--- | :--- |
| 主配置文件 | `~/.config/opencode/opencode.jsonc` | `~/.config/kilo/kilo.jsonc` |
| API 密钥库 | `~/.local/share/opencode/auth.json` | `~/.local/share/kilo/auth.json` |
| 提示词文件 | `~/.config/opencode/AGENTS.md` | `~/.config/kilo/AGENTS.md` |
| 程序设置 | `%LOCALAPPDATA%/easy-open-kilo-code/app-settings.json` | 同左 |

---

## ⚠️ 配置生效说明

- **OpenCode**：重启 OpenCode 或在 TUI 中输入 `/reload`
- **KiloCode**：在 VS Code 中按 `Ctrl+Shift+P`，输入 `Reload Window` 执行 `Developer: Reload Window`

---

## 📄 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
