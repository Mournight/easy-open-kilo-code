# Easy-Open-Kilo-Code

一个为 **OpenCode** 和 **KiloCode** 打造的跨平台图形化配置编辑器。单文件，极致轻量。
支持一键切换，自动更新实际读写路径，完美支持高级模型参数，如推理字段名与强度、最大上下文、最大单次输出、是否支持图像，MCP 服务器、上下文压缩、与全局提示词文件的精细管理。

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
- 自带简易且实用的连通性测试和测速功能。
- 支持开头所提到的所有高级模型管理功能。
- 目前支持OpenAI通用协议和OpenAI Responses专有协议

### 2. MCP 与上下文
- 一键导入或添加各种 Local/Remote 类型的 MCP 节点，支持批量导入，支持从windsurf和antigravity等IDE直接复制粘贴。
- 配置上下文压缩功能。缓冲区参数直接输入数字（例如 `20` 即表示 `20K`），保存时会自动乘以 1000 写入配置文件，读取时也会自动逆向还原。

### 3. 全局提示词 (AGENTS.md)
- 集成了轻量级文本编辑器，支持对对应品牌的提示词定义文件（`AGENTS.md`）进行可视化的快速查阅、编辑、重新加载与保存。

---

## 📄 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
