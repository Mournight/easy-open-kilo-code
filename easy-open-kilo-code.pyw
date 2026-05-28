#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenCode 配置编辑器
跨平台、高分屏适配的配置管理工具
"""

import json
import os
import sys
import platform
import threading
import time
import requests
from pathlib import Path
from typing import Optional, Dict, List, Any

import customtkinter as ctk
from tkinter import messagebox, filedialog

# 常量定义
APP_NAME = "OpenCode 配置编辑器"
APP_VERSION = "1.0.0"
WINDOW_SIZE = "1200x800"

# 字体配置
FONT_FAMILY = "宋体"
FONT_SIZE_NORMAL = 14
FONT_SIZE_LARGE = 16
FONT_SIZE_TITLE = 20
FONT_SIZE_SMALL = 12

def parse_jsonc(content: str) -> Dict:
    """解析 JSONC 内容（支持注释和尾随逗号）"""
    import re
    
    # 移除多行注释
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    
    # 移除单行注释
    lines = content.split('\n')
    cleaned_lines = []
    for line in lines:
        # 跳过纯注释行
        stripped = line.strip()
        if stripped.startswith('//'):
            continue
        # 移除行内注释
        if '//' in line:
            in_string = False
            escape_next = False
            for i, char in enumerate(line):
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"':
                    in_string = not in_string
                if not in_string and line[i:i+2] == '//':
                    line = line[:i]
                    break
        cleaned_lines.append(line)
    
    cleaned_content = '\n'.join(cleaned_lines)
    
    # 移除尾随逗号
    cleaned_content = re.sub(r',\s*([}\]])', r'\1', cleaned_content)
    
    return json.loads(cleaned_content)

# OpenCode 配置路径
def get_opencode_config_dir() -> Path:
    """获取 OpenCode 全局配置目录"""
    # 所有系统都使用 ~/.config/opencode
    return Path.home() / ".config" / "opencode"

def get_opencode_config_path() -> Path:
    """获取 OpenCode 全局配置文件路径（支持 .json 和 .jsonc）"""
    config_dir = get_opencode_config_dir()
    
    # 优先查找 opencode.jsonc，然后 opencode.json
    jsonc_path = config_dir / "opencode.jsonc"
    json_path = config_dir / "opencode.json"
    
    if jsonc_path.exists():
        return jsonc_path
    elif json_path.exists():
        return json_path
    else:
        # 默认使用 .jsonc
        return jsonc_path

def get_agents_md_path() -> Path:
    """获取全局 AGENTS.md 路径"""
    return get_opencode_config_dir() / "AGENTS.md"

def get_auth_json_path() -> Path:
    """获取 auth.json 路径"""
    # 支持 OPENCODE_AUTH_PATH 环境变量
    auth_path = os.environ.get("OPENCODE_AUTH_PATH")
    if auth_path:
        return Path(auth_path)
    
    # 默认路径
    system = platform.system()
    if system == "Windows":
        return Path.home() / ".local" / "share" / "opencode" / "auth.json"
    else:
        return Path.home() / ".local" / "share" / "opencode" / "auth.json"

def load_auth_json() -> Dict:
    """加载 auth.json"""
    auth_path = get_auth_json_path()
    if auth_path.exists():
        try:
            with open(auth_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_auth_json(auth_data: Dict):
    """保存 auth.json"""
    auth_path = get_auth_json_path()
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    with open(auth_path, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2, ensure_ascii=False)

def clean_base_url(url: str) -> str:
    """清洗 base URL，移除多余的斜杠"""
    url = url.rstrip("/")
    return url

def ensure_v1_in_url(url: str) -> str:
    """确保 URL 标准化为 /v1 端点
    
    处理逻辑：
    1. 移除末尾斜杠
    2. 如果以 /v1 结尾，保留
    3. 如果以 /v1/xxx 结尾，截取到 /v1
    4. 如果没有 /v1，补全
    """
    url = url.rstrip("/")
    
    # 检查是否包含 /v1
    if "/v1" in url:
        # 找到 /v1 的位置，截取到那里
        idx = url.index("/v1")
        url = url[:idx + 3]  # 保留 /v1
    else:
        # 没有 /v1，补全
        url = url + "/v1"
    
    return url

def probe_models(base_url: str, api_key: str) -> List[Dict[str, Any]]:
    """探测可用模型"""
    base = ensure_v1_in_url(base_url)
    models_url = f"{base}/models"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(models_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        models = []
        if "data" in data:
            for model in data["data"]:
                models.append({
                    "id": model.get("id", ""),
                    "name": model.get("id", ""),
                    "owned_by": model.get("owned_by", ""),
                })
        return models
    except Exception as e:
        raise Exception(f"模型探测失败: {str(e)}")


class ModelSelectorDialog(ctk.CTkToplevel):
    """模型选择对话框"""
    
    def __init__(self, parent, models: List[Dict], existing_ids: set):
        super().__init__(parent)
        self.title("选择模型")
        self.geometry("500x600")
        self.transient(parent)
        self.grab_set()
        
        self.models = models
        self.existing_ids = existing_ids
        self.selected_models = []
        self.checkbox_widgets = []  # (checkbox_widget, var, model_id)
        self.last_clicked_index = -1
        self.shift_pressed = False
        
        # 绑定 Shift 键检测
        self.bind("<KeyPress-Shift_L>", lambda e: self._set_shift(True))
        self.bind("<KeyRelease-Shift_L>", lambda e: self._set_shift(False))
        self.bind("<KeyPress-Shift_R>", lambda e: self._set_shift(True))
        self.bind("<KeyRelease-Shift_R>", lambda e: self._set_shift(False))
        
        # 居中显示 - 等待窗口完全初始化
        self.update_idletasks()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        x = parent_x + (parent_w - 500) // 2
        y = parent_y + (parent_h - 600) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets()
    
    def _set_shift(self, pressed: bool):
        """设置 Shift 键状态"""
        self.shift_pressed = pressed
    
    def _create_widgets(self):
        """创建界面组件"""
        # 标题栏
        title_frame = ctk.CTkFrame(self)
        title_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(
            title_frame, text=f"发现 {len(self.models)} 个模型",
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(side="left", padx=10)
        
        # 全选/取消按钮
        btn_frame = ctk.CTkFrame(title_frame)
        btn_frame.pack(side="right", padx=5)
        
        ctk.CTkButton(
            btn_frame, text="全选", command=self._select_all, width=60,
            font=(FONT_FAMILY, FONT_SIZE_SMALL)
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            btn_frame, text="取消全选", command=self._deselect_all, width=80,
            font=(FONT_FAMILY, FONT_SIZE_SMALL)
        ).pack(side="left", padx=2)
        
        # 搜索过滤框
        filter_frame = ctk.CTkFrame(self)
        filter_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(
            filter_frame, text="过滤:", font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(side="left", padx=5)
        
        self.filter_entry = ctk.CTkEntry(
            filter_frame, placeholder_text="输入关键字过滤模型...",
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.filter_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.filter_entry.bind("<KeyRelease>", self._on_filter_change)
        
        # 模型列表
        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self._build_model_list("")
        
        # 底部按钮
        bottom_frame = ctk.CTkFrame(self)
        bottom_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(
            bottom_frame, text="提示: 点击选择，按住 Shift 批量选择",
            font=(FONT_FAMILY, FONT_SIZE_SMALL), text_color="gray"
        ).pack(side="left", padx=10)
        
        ctk.CTkButton(
            bottom_frame, text="取消", command=self._cancel, width=80,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(side="right", padx=5)
        
        ctk.CTkButton(
            bottom_frame, text="确定", command=self._confirm, width=80,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL),
            fg_color="green", hover_color="darkgreen"
        ).pack(side="right", padx=5)
    
    def _build_model_list(self, filter_text: str):
        """构建模型列表（支持过滤）"""
        # 清空现有
        for widget in self.list_frame.winfo_children():
            widget.destroy()
        self.checkbox_widgets.clear()
        
        filter_lower = filter_text.lower()
        
        for i, model in enumerate(self.models):
            model_id = model["id"]
            
            # 过滤 - 在所有字段中搜索
            if filter_lower:
                # 构建搜索文本（包含所有字段）
                searchable = f"{model_id} {model.get('owned_by', '')}".lower()
                if filter_lower not in searchable:
                    continue
            
            is_existing = model_id in self.existing_ids
            
            var = ctk.BooleanVar(value=False)
            
            text = model_id
            if model.get("owned_by"):
                text += f"  ({model['owned_by']})"
            if is_existing:
                text += "  [已存在]"
            
            cb = ctk.CTkCheckBox(
                self.list_frame,
                text=text,
                variable=var,
                font=(FONT_FAMILY, FONT_SIZE_NORMAL),
                state="disabled" if is_existing else "normal",
                command=lambda idx=i: self._on_checkbox_click(idx)
            )
            cb.pack(anchor="w", pady=3, padx=5)
            
            if not is_existing:
                self.checkbox_widgets.append((cb, var, model_id, i))
    
    def _on_filter_change(self, event=None):
        """过滤框内容变化"""
        filter_text = self.filter_entry.get().strip()
        self._build_model_list(filter_text)
    
    def _on_checkbox_click(self, clicked_index: int):
        """复选框点击处理（支持 Shift 多选）"""
        if self.shift_pressed and self.last_clicked_index >= 0:
            # Shift 批量选择
            start = min(self.last_clicked_index, clicked_index)
            end = max(self.last_clicked_index, clicked_index)
            
            for cb, var, model_id, idx in self.checkbox_widgets:
                if start <= idx <= end:
                    var.set(True)
        
        self.last_clicked_index = clicked_index
    
    def _select_all(self):
        """全选"""
        for _, var, _, _ in self.checkbox_widgets:
            var.set(True)
    
    def _deselect_all(self):
        """取消全选"""
        for _, var, _, _ in self.checkbox_widgets:
            var.set(False)
    
    def _confirm(self):
        """确认选择"""
        self.selected_models = [model_id for _, var, model_id, _ in self.checkbox_widgets if var.get()]
        self.destroy()
    
    def _cancel(self):
        """取消"""
        self.selected_models = []
        self.destroy()


class JsonImportDialog(ctk.CTkToplevel):
    """JSON 导入对话框"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.title("导入 MCP 配置")
        self.geometry("600x500")
        self.transient(parent)
        self.grab_set()
        
        self.result = None
        
        # 居中显示
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - 600) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - 500) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets()
    
    def _create_widgets(self):
        """创建界面组件"""
        # 说明标签
        ctk.CTkLabel(
            self, 
            text="请粘贴 OpenCode 标准 MCP JSON 配置（支持 mcpServers/mcp 包装）",
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(padx=20, pady=(15, 5))
        
        # 文本框
        self.textbox = ctk.CTkTextbox(self, font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.textbox.pack(fill="both", expand=True, padx=20, pady=10)
        
        # 示例
        example = '''{
  "mcp": {
    "context7": {
      "type": "remote",
      "url": "https://mcp.context7.com/mcp",
      "enabled": true
    },
    "exa": {
      "type": "remote",
      "url": "https://mcp.exa.ai/mcp",
      "enabled": true
    }
  }
}'''
        self.textbox.insert("1.0", example)
        
        # 按钮
        btn_frame = ctk.CTkFrame(self)
        btn_frame.pack(fill="x", padx=20, pady=15)
        
        ctk.CTkButton(
            btn_frame, text="取消", command=self._cancel, width=80,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(side="right", padx=5)
        
        ctk.CTkButton(
            btn_frame, text="导入", command=self._confirm, width=80,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL),
            fg_color="green", hover_color="darkgreen"
        ).pack(side="right", padx=5)
    
    def _confirm(self):
        """确认导入"""
        json_str = self.textbox.get("1.0", "end-1c").strip()
        
        if not json_str:
            messagebox.showerror("错误", "请输入 JSON 配置")
            return
        
        try:
            # 尝试自动补齐最外层大括号
            # 检查是否缺少最外层 {}
            if not json_str.startswith('{'):
                json_str = '{' + json_str + '}'
            
            data = json.loads(json_str)
            self.result = data
            self.destroy()
        except json.JSONDecodeError as e:
            messagebox.showerror("错误", f"JSON 解析失败: {str(e)}")
    
    def _cancel(self):
        """取消"""
        self.result = None
        self.destroy()


class McpEditDialog(ctk.CTkToplevel):
    """MCP 编辑对话框"""
    
    def __init__(self, parent, title: str, mcp_type: str = "remote", name: str = "", config: Dict = None):
        super().__init__(parent)
        self.title(title)
        self.geometry("500x400")
        self.transient(parent)
        self.grab_set()
        
        self.result = None
        self.mcp_type = mcp_type
        
        # 居中显示
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - 400) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets(name, config or {})
    
    def _create_widgets(self, name: str, config: Dict):
        """创建界面组件"""
        # 名称
        row = ctk.CTkFrame(self)
        row.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(row, text="名称:", width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        self.name_entry = ctk.CTkEntry(row, font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.name_entry.pack(side="left", fill="x", expand=True, padx=5)
        if name:
            self.name_entry.insert(0, name)
        
        # 类型选择
        row = ctk.CTkFrame(self)
        row.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(row, text="类型:", width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        self.type_var = ctk.StringVar(value=self.mcp_type)
        ctk.CTkOptionMenu(
            row, values=["remote", "local"], variable=self.type_var,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL),
            command=self._on_type_change
        ).pack(side="left", padx=5)
        
        # URL (remote)
        self.url_frame = ctk.CTkFrame(self)
        self.url_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(self.url_frame, text="URL:", width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        self.url_entry = ctk.CTkEntry(self.url_frame, placeholder_text="https://mcp.example.com/mcp", font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.url_entry.pack(side="left", fill="x", expand=True, padx=5)
        if "url" in config:
            self.url_entry.insert(0, config["url"])
        
        # Command (local)
        self.cmd_frame = ctk.CTkFrame(self)
        self.cmd_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(self.cmd_frame, text="命令:", width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        self.cmd_entry = ctk.CTkEntry(self.cmd_frame, placeholder_text="npx -y @modelcontextprotocol/server-everything", font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=5)
        if "command" in config:
            cmd = config["command"]
            self.cmd_entry.insert(0, " ".join(cmd) if isinstance(cmd, list) else str(cmd))
        
        # Headers (remote)
        self.headers_frame = ctk.CTkFrame(self)
        self.headers_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(self.headers_frame, text="Headers:", width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        self.headers_entry = ctk.CTkEntry(self.headers_frame, placeholder_text='{"Authorization": "Bearer xxx"}', font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.headers_entry.pack(side="left", fill="x", expand=True, padx=5)
        if "headers" in config:
            self.headers_entry.insert(0, json.dumps(config["headers"]))
        
        # Environment (local)
        self.env_frame = ctk.CTkFrame(self)
        self.env_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(self.env_frame, text="环境变量:", width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        self.env_entry = ctk.CTkEntry(self.env_frame, placeholder_text='{"KEY": "value"}', font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.env_entry.pack(side="left", fill="x", expand=True, padx=5)
        if "environment" in config:
            self.env_entry.insert(0, json.dumps(config["environment"]))
        
        # Timeout
        row = ctk.CTkFrame(self)
        row.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(row, text="超时(ms):", width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        self.timeout_entry = ctk.CTkEntry(row, placeholder_text="5000", font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.timeout_entry.pack(side="left", padx=5)
        if "timeout" in config:
            self.timeout_entry.insert(0, str(config["timeout"]))
        
        # Enabled
        self.enabled_var = ctk.BooleanVar(value=config.get("enabled", True))
        ctk.CTkCheckBox(
            self, text="启用", variable=self.enabled_var,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(anchor="w", padx=25, pady=5)
        
        # 按钮
        btn_frame = ctk.CTkFrame(self)
        btn_frame.pack(fill="x", padx=20, pady=15)
        
        ctk.CTkButton(
            btn_frame, text="取消", command=self._cancel, width=80,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(side="right", padx=5)
        
        ctk.CTkButton(
            btn_frame, text="确定", command=self._confirm, width=80,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL),
            fg_color="green", hover_color="darkgreen"
        ).pack(side="right", padx=5)
        
        # 根据类型显示/隐藏
        self._on_type_change(self.mcp_type)
    
    def _on_type_change(self, mcp_type: str):
        """类型变化时更新界面"""
        if mcp_type == "remote":
            self.url_frame.pack(fill="x", padx=20, pady=5)
            self.headers_frame.pack(fill="x", padx=20, pady=5)
            self.cmd_frame.pack_forget()
            self.env_frame.pack_forget()
        else:
            self.url_frame.pack_forget()
            self.headers_frame.pack_forget()
            self.cmd_frame.pack(fill="x", padx=20, pady=5)
            self.env_frame.pack(fill="x", padx=20, pady=5)
    
    def _confirm(self):
        """确认"""
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showerror("错误", "请输入名称")
            return
        
        mcp_type = self.type_var.get()
        config = {
            "type": mcp_type,
            "enabled": self.enabled_var.get()
        }
        
        if mcp_type == "remote":
            url = self.url_entry.get().strip()
            if not url:
                messagebox.showerror("错误", "请输入 URL")
                return
            config["url"] = url
            
            headers_str = self.headers_entry.get().strip()
            if headers_str:
                try:
                    config["headers"] = json.loads(headers_str)
                except:
                    messagebox.showerror("错误", "Headers 格式错误，应为 JSON")
                    return
        else:
            cmd = self.cmd_entry.get().strip()
            if not cmd:
                messagebox.showerror("错误", "请输入命令")
                return
            config["command"] = cmd.split()
            
            env_str = self.env_entry.get().strip()
            if env_str:
                try:
                    config["environment"] = json.loads(env_str)
                except:
                    messagebox.showerror("错误", "环境变量格式错误，应为 JSON")
                    return
        
        timeout_str = self.timeout_entry.get().strip()
        if timeout_str:
            try:
                config["timeout"] = int(timeout_str)
            except:
                messagebox.showerror("错误", "超时应为数字")
                return
        
        self.result = {"name": name, "config": config}
        self.destroy()
    
    def _cancel(self):
        """取消"""
        self.result = None
        self.destroy()


class ProviderFrame(ctk.CTkFrame):
    """Provider 配置框架"""
    
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.providers = {}
        self._create_widgets()
    
    def _create_widgets(self):
        """创建界面组件"""
        # 左右分栏
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 左侧 - Provider 列表
        left_frame = ctk.CTkFrame(main_frame, width=250)
        left_frame.pack(side="left", fill="y", padx=5, pady=5)
        left_frame.pack_propagate(False)
        
        self.provider_list = ctk.CTkScrollableFrame(left_frame)
        self.provider_list.pack(fill="both", expand=True, padx=5, pady=5)
        
        # 右侧 - Provider 详情
        right_frame = ctk.CTkFrame(main_frame)
        right_frame.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        
        # 详情内容
        detail_frame = ctk.CTkFrame(right_frame)
        detail_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 名称
        row = ctk.CTkFrame(detail_frame)
        row.pack(fill="x", pady=5)
        ctk.CTkLabel(row, text="名称:", width=120, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left", padx=5)
        self.name_entry = ctk.CTkEntry(row, placeholder_text="my-provider", font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.name_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        # 协议类型
        row = ctk.CTkFrame(detail_frame)
        row.pack(fill="x", pady=5)
        ctk.CTkLabel(row, text="协议:", width=120, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left", padx=5)
        self.protocol_var = ctk.StringVar(value="openai_standard")
        self.protocol_menu = ctk.CTkOptionMenu(
            row,
            values=["openai_standard", "openai_response"],
            variable=self.protocol_var,
            width=200,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.protocol_menu.pack(side="left", padx=5)
        # 监听协议变化
        self.protocol_var.trace_add("write", self._on_protocol_change)
        
        # Base URL
        row = ctk.CTkFrame(detail_frame)
        row.pack(fill="x", pady=5)
        ctk.CTkLabel(row, text="Base URL:", width=120, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left", padx=5)
        self.url_entry = ctk.CTkEntry(row, placeholder_text="https://api.example.com", font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.url_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        # API Key
        row = ctk.CTkFrame(detail_frame)
        row.pack(fill="x", pady=5)
        ctk.CTkLabel(row, text="API Key:", width=120, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left", padx=5)
        self.api_key_entry = ctk.CTkEntry(row, placeholder_text="sk-...", show="*", font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.api_key_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        # 模型配置区域标题和操作按钮
        model_header = ctk.CTkFrame(detail_frame)
        model_header.pack(fill="x", pady=(15, 5))
        
        ctk.CTkLabel(model_header, text="模型列表", font=(FONT_FAMILY, FONT_SIZE_LARGE, "bold")).pack(side="left", padx=5)
        
        # 探测状态标签
        self.probe_status_label = ctk.CTkLabel(
            model_header, text="", font=(FONT_FAMILY, FONT_SIZE_SMALL), text_color="gray"
        )
        self.probe_status_label.pack(side="left", padx=10)
        
        # Provider 操作按钮
        self.remove_provider_btn = ctk.CTkButton(
            model_header, text="删除 Provider", command=self._remove_provider, width=120,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL), fg_color="red", hover_color="darkred"
        )
        self.remove_provider_btn.pack(side="right", padx=5)
        
        self.add_provider_btn = ctk.CTkButton(
            model_header, text="新建 Provider", command=self._add_provider, width=120,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.add_provider_btn.pack(side="right", padx=5)
        
        self.add_model_btn = ctk.CTkButton(
            model_header, text="手动添加", command=self._add_model_manual, width=100,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.add_model_btn.pack(side="right", padx=5)
        
        self.probe_btn = ctk.CTkButton(
            model_header, text="选择模型", command=self._select_models, width=100,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.probe_btn.pack(side="right", padx=5)
        
        # 模型列表 - 可滚动区域
        self.model_frame = ctk.CTkScrollableFrame(detail_frame, height=300)
        self.model_frame.pack(fill="both", expand=True, pady=5)
        
        # 当前选中的 provider
        self.current_provider = None
        self.model_entries = []
    
    def _select_models(self):
        """选择模型（探测并弹出选择对话框）"""
        url = self.url_entry.get().strip()
        api_key = self.api_key_entry.get().strip()
        
        if not url:
            self.app.show_status("请输入 Base URL", "error")
            return
        
        if not api_key:
            self.app.show_status("请输入 API Key", "error")
            return
        
        # 确保有 provider
        if not self.current_provider:
            self._sync_current_provider()
        
        self.probe_status_label.configure(text="正在探测...", text_color="orange")
        self.probe_btn.configure(state="disabled")
        
        def probe_thread():
            try:
                models = probe_models(url, api_key)
                self.after(0, lambda: self._show_model_selector(models))
            except Exception as e:
                self.after(0, lambda: self._on_probe_error(str(e)))
        
        threading.Thread(target=probe_thread, daemon=True).start()
    
    def _on_probe_error(self, error):
        """探测失败回调"""
        self.probe_btn.configure(state="normal")
        self.probe_status_label.configure(text="探测失败", text_color="red")
        self.app.show_status(f"探测失败: {error}", "error")
    
    def _show_model_selector(self, models):
        """显示模型选择对话框"""
        self.probe_btn.configure(state="normal")
        self.probe_status_label.configure(text=f"发现 {len(models)} 个模型", text_color="green")
        
        # 获取已存在的模型ID
        existing_ids = set()
        if self.current_provider and self.current_provider in self.providers:
            existing_ids = set(self.providers[self.current_provider].get("models", {}).keys())
        
        dialog = ModelSelectorDialog(self, models, existing_ids)
        self.wait_window(dialog)
        
        if dialog.selected_models:
            # 添加选中的模型到 provider
            if self.current_provider and self.current_provider in self.providers:
                provider = self.providers[self.current_provider]
                for model_id in dialog.selected_models:
                    if model_id not in provider.get("models", {}):
                        provider.setdefault("models", {})[model_id] = {
                            "name": model_id,
                            "limit": {
                                "context": 200000,
                                "output": 32000
                            },
                            "modalities": {
                                "input": ["text"],
                                "output": ["text"]
                            }
                        }
                self._refresh_model_list()
                self.app.show_status(f"已添加 {len(dialog.selected_models)} 个模型", "success")
    
    def _sync_current_provider(self):
        """同步当前 provider（如果编辑框有内容）"""
        name = self.name_entry.get().strip()
        if name:
            self.current_provider = name
            if name not in self.providers:
                # 根据协议类型选择 npm 包
                protocol = self.protocol_var.get()
                if protocol == "openai_response":
                    npm_package = "@ai-sdk/openai"
                else:
                    npm_package = "@ai-sdk/openai-compatible"
                
                self.providers[name] = {
                    "npm": npm_package,
                    "name": name,
                    "options": {"baseURL": ""},
                    "models": {}
                }
                self._refresh_provider_list()
    
    def _on_protocol_change(self, *args):
        """协议变化时更新 npm 字段"""
        if not self.current_provider or self.current_provider not in self.providers:
            return
        
        protocol = self.protocol_var.get()
        if protocol == "openai_response":
            npm_package = "@ai-sdk/openai"
        else:
            npm_package = "@ai-sdk/openai-compatible"
        
        self.providers[self.current_provider]["npm"] = npm_package
    
    def _add_provider(self):
        """添加新 Provider（根据编辑框内容命名）"""
        current_name = self.name_entry.get().strip()
        
        if current_name and current_name not in self.providers:
            # 如果编辑框有内容且该名称不存在，使用它
            name = current_name
        else:
            # 否则生成新名称
            base_name = "new-provider"
            counter = 0
            name = base_name
            while name in self.providers:
                counter += 1
                name = f"{base_name}-{counter}"
        
        # 根据协议类型选择 npm 包
        protocol = self.protocol_var.get()
        if protocol == "openai_response":
            npm_package = "@ai-sdk/openai"
        else:
            npm_package = "@ai-sdk/openai-compatible"
        
        self.providers[name] = {
            "npm": npm_package,
            "name": name,
            "options": {"baseURL": ""},
            "models": {}
        }
        self._select_provider(name)  # 这会自动刷新列表
    
    def _remove_provider(self):
        """删除当前 Provider"""
        if self.current_provider and self.current_provider in self.providers:
            if messagebox.askyesno("确认", f"确定要删除 Provider '{self.current_provider}' 吗？"):
                del self.providers[self.current_provider]
                self.current_provider = None
                self._refresh_provider_list()
                self._clear_details()
    
    def _select_provider(self, name: str):
        """选择 Provider"""
        self.current_provider = name
        if name in self.providers:
            provider = self.providers[name]
            self.name_entry.delete(0, "end")
            self.name_entry.insert(0, name)
            
            options = provider.get("options", {})
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, options.get("baseURL", ""))
            
            self.api_key_entry.delete(0, "end")
            self.api_key_entry.insert(0, options.get("apiKey", ""))
            
            # 根据 npm 字段设置协议
            npm = provider.get("npm", "@ai-sdk/openai-compatible")
            if npm == "@ai-sdk/openai":
                self.protocol_var.set("openai_response")
            else:
                self.protocol_var.set("openai_standard")
            
            self.probe_status_label.configure(text="")
            self._refresh_model_list()
            self._refresh_provider_list()  # 更新高亮
    
    def _refresh_provider_list(self):
        """刷新 Provider 列表"""
        for widget in self.provider_list.winfo_children():
            widget.destroy()
        
        for name in self.providers:
            btn = ctk.CTkButton(
                self.provider_list,
                text=name,
                command=lambda n=name: self._select_provider(n),
                anchor="w",
                font=(FONT_FAMILY, FONT_SIZE_NORMAL)
            )
            
            # 选中的用主题蓝色，未选中的用默认灰色
            if name == self.current_provider:
                btn.configure(fg_color="#3B8ED0", hover_color="#1F6AA5")
            else:
                btn.configure(fg_color="gray60", hover_color="gray70")
            
            btn.pack(fill="x", pady=3)
    
    def _refresh_model_list(self):
        """刷新模型列表"""
        for widget in self.model_frame.winfo_children():
            widget.destroy()
        self.model_entries.clear()
        
        if not self.current_provider or self.current_provider not in self.providers:
            return
        
        provider = self.providers[self.current_provider]
        models = provider.get("models", {})
        
        for model_id, model_config in models.items():
            self._create_model_entry(model_id, model_config)
    
    def _create_model_entry(self, model_id: str, model_config: Dict):
        """创建模型配置条目"""
        frame = ctk.CTkFrame(self.model_frame)
        frame.pack(fill="x", pady=5)
        
        # 第一行：模型ID、测试、测速、删除
        row1 = ctk.CTkFrame(frame)
        row1.pack(fill="x", padx=5, pady=3)
        
        ctk.CTkLabel(row1, text="模型ID:", width=70, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        id_label = ctk.CTkLabel(row1, text=model_id, font=(FONT_FAMILY, FONT_SIZE_NORMAL), anchor="w")
        id_label.pack(side="left", fill="x", expand=True, padx=5)
        
        # 删除按钮
        del_btn = ctk.CTkButton(
            row1, text="删除", width=60, fg_color="red", hover_color="darkred",
            command=lambda: self._remove_model(model_id),
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        del_btn.pack(side="right", padx=3)
        
        # 测速按钮（黄色）
        speed_btn = ctk.CTkButton(
            row1, text="测速", width=60,
            command=lambda: self._test_speed(model_id, speed_btn),
            font=(FONT_FAMILY, FONT_SIZE_NORMAL),
            fg_color="#D4A017", hover_color="#B8860B"
        )
        speed_btn.pack(side="right", padx=3)
        
        # 测试按钮（绿色）
        test_btn = ctk.CTkButton(
            row1, text="测试", width=60,
            command=lambda: self._test_model(model_id, test_btn),
            font=(FONT_FAMILY, FONT_SIZE_NORMAL),
            fg_color="#2E8B57", hover_color="#228B22"
        )
        test_btn.pack(side="right", padx=3)
        
        # 第二行：上下文、最大输出、支持图像
        row2 = ctk.CTkFrame(frame)
        row2.pack(fill="x", padx=5, pady=3)
        
        ctk.CTkLabel(row2, text="上下文:", width=70, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        
        # 从 limit.context 读取
        limit = model_config.get("limit", {})
        ctx_value = limit.get("context", 200000)
        ctx_display = str(ctx_value // 1000) if ctx_value >= 1000 else str(ctx_value)
        
        ctx_entry = ctk.CTkEntry(row2, width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL), justify="center")
        ctx_entry.pack(side="left", padx=5)
        ctx_entry.insert(0, ctx_display)
        
        ctk.CTkLabel(row2, text="K", font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"), text_color="#FFD700").pack(side="left")
        
        ctk.CTkLabel(row2, text="最大输出:", width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left", padx=(15, 0))
        
        output_value = limit.get("output", 32000)
        output_display = str(output_value // 1000) if output_value >= 1000 else str(output_value)
        
        output_entry = ctk.CTkEntry(row2, width=60, font=(FONT_FAMILY, FONT_SIZE_NORMAL), justify="center")
        output_entry.pack(side="left", padx=5)
        output_entry.insert(0, output_display)
        
        ctk.CTkLabel(row2, text="K", font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"), text_color="#FFD700").pack(side="left")
        
        # 从 modalities 读取图像支持
        modalities = model_config.get("modalities", {})
        input_modalities = modalities.get("input", [])
        supports_images = "image" in input_modalities
        
        img_var = ctk.BooleanVar(value=supports_images)
        img_cb = ctk.CTkCheckBox(row2, text="支持图像", variable=img_var, font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        img_cb.pack(side="left", padx=15)
        
        # 第三行：思考字段名 + 变体强度
        row3 = ctk.CTkFrame(frame)
        row3.pack(fill="x", padx=5, pady=3)
        
        # 自动检测思考字段名
        thinking_field = "reasoningEffort"
        
        # 尝试从 options 读取
        options = model_config.get("options", {})
        if "reasoningEffort" in options:
            thinking_field = "reasoningEffort"
        elif "thinking" in options:
            thinking_field = "thinking"
        # 尝试从 variants 读取
        elif "variants" in model_config:
            variants = model_config["variants"]
            for variant in variants.values():
                if "reasoningEffort" in variant:
                    thinking_field = "reasoningEffort"
                    break
                elif "thinking" in variant:
                    thinking_field = "thinking"
                    break
        
        ctk.CTkLabel(row3, text="思考:", width=50, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left")
        think_field_entry = ctk.CTkEntry(row3, placeholder_text="reasoningEffort", width=130, font=(FONT_FAMILY, FONT_SIZE_NORMAL), justify="center")
        think_field_entry.pack(side="left", padx=3)
        think_field_entry.insert(0, thinking_field)
        
        # 变体容器
        variants_frame = ctk.CTkFrame(row3)
        variants_frame.pack(side="left", fill="x", expand=True, padx=5)
        
        # 收集变体强度列表
        variant_levels = []
        if "variants" in model_config:
            variant_levels = list(model_config["variants"].keys())
        elif "options" in model_config and thinking_field in model_config["options"]:
            # Response 模式，只有一个强度
            variant_levels = [model_config["options"][thinking_field]]
        
        # 如果没有变体，使用默认值
        if not variant_levels:
            variant_levels = ["high"]
        
        # 变体标签和删除按钮
        variant_widgets = []
        for level in variant_levels:
            self._add_variant_tag(variants_frame, level, variant_widgets, thinking_field)
        
        # 添加变体按钮
        add_variant_btn = ctk.CTkButton(
            row3, text="+", width=30,
            command=lambda: self._add_variant_dialog(variants_frame, variant_widgets, thinking_field),
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        add_variant_btn.pack(side="left", padx=3)
        
        self.model_entries.append({
            "frame": frame,
            "id_label": id_label,
            "id_entry": None,
            "ctx_entry": ctx_entry,
            "output_entry": output_entry,
            "img_var": img_var,
            "think_field_entry": think_field_entry,
            "variants_frame": variants_frame,
            "variant_widgets": variant_widgets,
            "original_id": model_id
        })
    
    def _test_model(self, model_id: str, btn: ctk.CTkButton):
        """测试模型连通性"""
        # 直接从 UI 读取配置
        base_url = self.url_entry.get().strip()
        api_key = self.api_key_entry.get().strip()
        
        if not base_url or not api_key:
            self.app.show_status("请先配置 Base URL 和 API Key", "error")
            return
        
        btn.configure(text="测试中...", state="disabled")
        
        def test_thread():
            try:
                url = f"{ensure_v1_in_url(base_url)}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model_id,
                    "messages": [{"role": "user", "content": "此信息仅用于测试最快连通性，以最快的方式回答\"hello\"，不要任何思考"}],
                    "max_tokens": 10
                }
                
                response = requests.post(url, json=payload, headers=headers, timeout=15)
                response.raise_for_status()
                self.after(0, lambda: btn.configure(text="✓", state="normal", fg_color="green"))
            except Exception as e:
                self.after(0, lambda: btn.configure(text="✗", state="normal", fg_color="red"))
                self.after(0, lambda: self.app.show_status(f"测试失败: {str(e)}", "error"))
        
        threading.Thread(target=test_thread, daemon=True).start()
    
    def _test_speed(self, model_id: str, btn: ctk.CTkButton):
        """测试模型输出速度"""
        # 直接从 UI 读取配置
        base_url = self.url_entry.get().strip()
        api_key = self.api_key_entry.get().strip()
        
        if not base_url or not api_key:
            self.app.show_status("请先配置 Base URL 和 API Key", "error")
            return
        
        btn.configure(text="等待中", state="disabled")
        
        def speed_thread():
            try:
                url = f"{ensure_v1_in_url(base_url)}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model_id,
                    "messages": [{"role": "user", "content": "此信息仅用于测试最快输出速度，不要任何思考，以最快的方式回答1000个\"hello\"，以空格分割"}],
                    "max_tokens": 2000,
                    "stream": True
                }
                
                start_time = None
                token_count = 0
                first_token_received = False
                
                response = requests.post(url, json=payload, headers=headers, timeout=15, stream=True)
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        line_str = line.decode('utf-8')
                        if line_str.startswith('data: ') and line_str != 'data: [DONE]':
                            try:
                                data = json.loads(line_str[6:])
                                if 'choices' in data and len(data['choices']) > 0:
                                    delta = data['choices'][0].get('delta', {})
                                    content = delta.get('content', '')
                                    if content:
                                        if not first_token_received:
                                            first_token_received = True
                                            start_time = time.time()
                                            self.after(0, lambda: btn.configure(text="测速中"))
                                        
                                        # 计算hello数量
                                        hello_count = content.lower().count('hello')
                                        token_count += hello_count
                                        
                                        # 检查是否超过5秒
                                        if start_time and time.time() - start_time >= 5:
                                            elapsed = time.time() - start_time
                                            speed = token_count / elapsed
                                            self.after(0, lambda: btn.configure(text=f"{speed:.1f}t/s", state="normal"))
                                            return
                            except json.JSONDecodeError:
                                continue
                
                # 如果流结束但没超过5秒
                if start_time and token_count > 0:
                    elapsed = time.time() - start_time
                    speed = token_count / elapsed
                    self.after(0, lambda: btn.configure(text=f"{speed:.1f}t/s", state="normal"))
                else:
                    self.after(0, lambda: btn.configure(text="测速", state="normal"))
                    
            except Exception as e:
                self.after(0, lambda: btn.configure(text="测速", state="normal"))
                self.after(0, lambda: self.app.show_status(f"测速失败: {str(e)}", "error"))
        
        threading.Thread(target=speed_thread, daemon=True).start()
    
    def _remove_model(self, model_id: str):
        """删除模型"""
        if self.current_provider and self.current_provider in self.providers:
            provider = self.providers[self.current_provider]
            if model_id in provider.get("models", {}):
                del provider["models"][model_id]
                self._refresh_model_list()
    
    def _add_variant_tag(self, parent, level: str, variant_widgets: list, thinking_field: str):
        """添加变体标签"""
        tag_frame = ctk.CTkFrame(parent)
        tag_frame.pack(side="left", padx=2)
        
        label = ctk.CTkLabel(tag_frame, text=level, font=(FONT_FAMILY, FONT_SIZE_SMALL))
        label.pack(side="left", padx=2)
        
        del_btn = ctk.CTkButton(
            tag_frame, text="×", width=20, height=20,
            command=lambda: self._remove_variant_tag(tag_frame, level, variant_widgets, thinking_field),
            font=(FONT_FAMILY, FONT_SIZE_SMALL),
            fg_color="red", hover_color="darkred"
        )
        del_btn.pack(side="left", padx=1)
        
        variant_widgets.append((tag_frame, level))
    
    def _remove_variant_tag(self, tag_frame, level: str, variant_widgets: list, thinking_field: str):
        """删除变体标签"""
        tag_frame.destroy()
        variant_widgets[:] = [(f, l) for f, l in variant_widgets if l != level]
    
    def _add_variant_dialog(self, parent, variant_widgets: list, thinking_field: str):
        """添加变体对话框"""
        # 检查已存在的变体
        existing_levels = [l for _, l in variant_widgets]
        
        # 可选的强度
        all_levels = ["none", "minimal", "low", "medium", "high", "xhigh"]
        available_levels = [l for l in all_levels if l not in existing_levels]
        
        if not available_levels:
            self.app.show_status("所有变体强度已添加", "warning")
            return
        
        # 创建居中对话框
        dialog = ctk.CTkToplevel(self)
        dialog.title("添加变体")
        dialog.geometry("300x200")
        dialog.transient(self)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 300) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 200) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # 说明
        ctk.CTkLabel(
            dialog, text=f"可选: {', '.join(available_levels)}",
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(pady=10)
        
        # 输入框
        entry = ctk.CTkEntry(dialog, placeholder_text="输入强度", font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        entry.pack(pady=5)
        
        # 结果
        result = {"value": None}
        
        def confirm():
            result["value"] = entry.get().strip().lower()
            dialog.destroy()
        
        def cancel():
            dialog.destroy()
        
        # 按钮
        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=10)
        
        ctk.CTkButton(btn_frame, text="取消", command=cancel, width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="确定", command=confirm, width=80, font=(FONT_FAMILY, FONT_SIZE_NORMAL), fg_color="green").pack(side="left", padx=5)
        
        # 绑定回车
        entry.bind("<Return>", lambda e: confirm())
        
        # 等待对话框关闭
        self.wait_window(dialog)
        
        level = result["value"]
        if level:
            if level in existing_levels:
                self.app.show_status(f"变体 '{level}' 已存在", "error")
                return
            if level not in all_levels:
                self.app.show_status(f"无效的强度: {level}", "error")
                return
            
            self._add_variant_tag(parent, level, variant_widgets, thinking_field)
    
    def _add_model_manual(self):
        """手动添加模型"""
        if not self.current_provider or self.current_provider not in self.providers:
            self.app.show_status("请先选择或创建一个 Provider", "error")
            return
        
        model_id = ctk.CTkInputDialog(text="请输入模型 ID:", title="添加模型").get_input()
        if model_id:
            provider = self.providers[self.current_provider]
            provider.setdefault("models", {})[model_id] = {
                "name": model_id,
                "limit": {
                    "context": 200000,
                    "output": 32000
                },
                "modalities": {
                    "input": ["text"],
                    "output": ["text"]
                }
            }
            self._refresh_model_list()
    
    def _sync_ui_to_provider(self):
        """将 UI 数据同步到当前 provider"""
        if not self.current_provider or self.current_provider not in self.providers:
            return
        
        old_name = self.current_provider
        new_name = self.name_entry.get().strip()
        
        if not new_name:
            return
        
        # 收集模型配置
        models = {}
        for entry in self.model_entries:
            model_id = entry["original_id"]
            if model_id:
                # 解析上下文
                try:
                    ctx_str = entry["ctx_entry"].get().strip() or "200"
                    context = int(ctx_str) * 1000
                except ValueError:
                    context = 200000
                
                # 解析输出
                try:
                    output_str = entry["output_entry"].get().strip() or "32"
                    output = int(output_str) * 1000
                except ValueError:
                    output = 32000
                
                # 构建 limit 字段
                limit = {
                    "context": context,
                    "output": output
                }
                
                # 构建 modalities 字段
                modalities = {
                    "input": ["text", "image"] if entry["img_var"].get() else ["text"],
                    "output": ["text"]
                }
                
                # 思考配置
                thinking_field = entry["think_field_entry"].get().strip() or "reasoningEffort"
                
                # 收集变体强度列表
                variant_widgets = entry.get("variant_widgets", [])
                variant_levels = [level for _, level in variant_widgets]
                
                model_cfg = {
                    "limit": limit,
                    "modalities": modalities
                }
                
                # 生成变体配置（两种模式都使用 variants）
                if thinking_field and variant_levels:
                    variants = {}
                    for level in variant_levels:
                        variants[level] = {thinking_field: level}
                    model_cfg["variants"] = variants
                
                models[model_id] = model_cfg
        
        # 获取现有的 provider 配置（保留其他字段）
        existing_provider = self.providers.get(old_name, {}).copy()
        
        # 根据协议类型更新 npm 字段
        protocol = self.protocol_var.get()
        if protocol == "openai_response":
            existing_provider["npm"] = "@ai-sdk/openai"
        else:
            existing_provider["npm"] = "@ai-sdk/openai-compatible"
        
        # 更新 provider 配置
        existing_provider["name"] = new_name
        existing_provider["options"] = {
            "baseURL": clean_base_url(self.url_entry.get().strip()),
            "apiKey": self.api_key_entry.get().strip()
        }
        existing_provider["models"] = models
        
        # 更新 providers 字典
        if old_name != new_name and old_name in self.providers:
            del self.providers[old_name]
        self.providers[new_name] = existing_provider
        self.current_provider = new_name
    
    def _clear_details(self):
        """清空详情"""
        self.name_entry.delete(0, "end")
        self.url_entry.delete(0, "end")
        self.api_key_entry.delete(0, "end")
        self.probe_status_label.configure(text="")
        for widget in self.model_frame.winfo_children():
            widget.destroy()
        self.model_entries.clear()
    
    def load_providers(self, providers: Dict):
        """加载 Provider 配置"""
        self.providers = providers
        self._refresh_provider_list()
    
    def get_providers(self) -> Dict:
        """获取 Provider 配置（同步 UI 数据，过滤空 provider）"""
        self._sync_ui_to_provider()
        
        # 过滤掉没有 baseURL 的空 provider
        filtered = {}
        for name, provider in self.providers.items():
            base_url = provider.get("options", {}).get("baseURL", "").strip()
            if base_url:  # 只保留有 baseURL 的 provider
                filtered[name] = provider
        
        return filtered


class McpCompactionFrame(ctk.CTkFrame):
    """MCP 服务器和上下文压缩配置框架"""
    
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.mcp_servers = {}
        self._create_widgets()
    
    def _create_widgets(self):
        """创建界面组件"""
        # ========== MCP 服务器管理 ==========
        mcp_label = ctk.CTkLabel(self, text="MCP 服务器", font=(FONT_FAMILY, FONT_SIZE_LARGE, "bold"))
        mcp_label.pack(anchor="w", padx=20, pady=(15, 5))
        
        # MCP 列表和操作按钮
        mcp_frame = ctk.CTkFrame(self)
        mcp_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        # MCP 列表
        self.mcp_list = ctk.CTkScrollableFrame(mcp_frame, height=200)
        self.mcp_list.pack(fill="both", expand=True, padx=5, pady=5)
        
        # 按钮行
        btn_row = ctk.CTkFrame(mcp_frame)
        btn_row.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkButton(
            btn_row, text="添加 MCP", command=self._add_mcp, width=100,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            btn_row, text="JSON 导入", command=self._import_mcp_json, width=100,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL),
            fg_color="#D4A017", hover_color="#B8860B"
        ).pack(side="left", padx=5)
        
        # ========== 上下文压缩 ==========
        compaction_label = ctk.CTkLabel(self, text="上下文压缩", font=(FONT_FAMILY, FONT_SIZE_LARGE, "bold"))
        compaction_label.pack(anchor="w", padx=20, pady=(20, 5))
        
        # 压缩选项 - 同一行
        compaction_frame = ctk.CTkFrame(self)
        compaction_frame.pack(fill="x", padx=20, pady=5)
        
        self.auto_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            compaction_frame, text="自动压缩", variable=self.auto_var,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(side="left", padx=15, pady=10)
        
        self.prune_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            compaction_frame, text="清理旧输出", variable=self.prune_var,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(side="left", padx=15, pady=10)
        
        ctk.CTkLabel(
            compaction_frame, text="缓冲区:", font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        ).pack(side="left", padx=(15, 5), pady=10)
        
        self.reserved_entry = ctk.CTkEntry(
            compaction_frame, placeholder_text="20000", width=100,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL), justify="center"
        )
        self.reserved_entry.pack(side="left", padx=5, pady=10)
        
        # 说明
        info_label = ctk.CTkLabel(
            self, text="说明: 压缩触发点 = context - reserved（默认约90%）",
            font=(FONT_FAMILY, FONT_SIZE_SMALL), text_color="gray"
        )
        info_label.pack(anchor="w", padx=25, pady=(0, 10))
    
    def _refresh_mcp_list(self):
        """刷新 MCP 列表"""
        for widget in self.mcp_list.winfo_children():
            widget.destroy()
        
        for name, config in self.mcp_servers.items():
            self._create_mcp_entry(name, config)
    
    def _create_mcp_entry(self, name: str, config: Dict):
        """创建 MCP 条目"""
        frame = ctk.CTkFrame(self.mcp_list)
        frame.pack(fill="x", pady=3)
        
        # 绑定双击事件
        frame.bind("<Double-Button-1>", lambda e, n=name: self._edit_mcp(n))
        
        # 名称和类型
        mcp_type = config.get("type", "unknown")
        type_color = "#4CAF50" if mcp_type == "local" else "#2196F3"
        
        info_frame = ctk.CTkFrame(frame)
        info_frame.pack(fill="x", padx=5, pady=5)
        info_frame.bind("<Double-Button-1>", lambda e, n=name: self._edit_mcp(n))
        
        name_label = ctk.CTkLabel(
            info_frame, text=name, font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")
        )
        name_label.pack(side="left", padx=5)
        name_label.bind("<Double-Button-1>", lambda e, n=name: self._edit_mcp(n))
        
        type_label = ctk.CTkLabel(
            info_frame, text=f"[{mcp_type}]", font=(FONT_FAMILY, FONT_SIZE_SMALL),
            text_color=type_color
        )
        type_label.pack(side="left", padx=5)
        type_label.bind("<Double-Button-1>", lambda e, n=name: self._edit_mcp(n))
        
        # URL 或 command
        if mcp_type == "remote":
            detail = config.get("url", "")
        else:
            cmd = config.get("command", [])
            detail = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        
        detail_label = ctk.CTkLabel(
            info_frame, text=detail, font=(FONT_FAMILY, FONT_SIZE_SMALL),
            text_color="gray"
        )
        detail_label.pack(side="left", padx=10, fill="x", expand=True)
        detail_label.bind("<Double-Button-1>", lambda e, n=name: self._edit_mcp(n))
        
        # 启用/禁用
        enabled_var = ctk.BooleanVar(value=config.get("enabled", True))
        ctk.CTkCheckBox(
            info_frame, text="", variable=enabled_var, width=20,
            command=lambda n=name, v=enabled_var: self._toggle_mcp(n, v.get())
        ).pack(side="right", padx=5)
        
        # 删除按钮
        ctk.CTkButton(
            info_frame, text="删除", width=50, fg_color="red", hover_color="darkred",
            command=lambda n=name: self._remove_mcp(n),
            font=(FONT_FAMILY, FONT_SIZE_SMALL)
        ).pack(side="right", padx=5)
    
    def _edit_mcp(self, name: str):
        """编辑 MCP"""
        if name not in self.mcp_servers:
            return
        
        config = self.mcp_servers[name]
        mcp_type = config.get("type", "remote")
        
        dialog = McpEditDialog(self, f"编辑 MCP: {name}", mcp_type=mcp_type, name=name, config=config)
        self.wait_window(dialog)
        
        if dialog.result:
            # 删除旧的，添加新的
            if dialog.result["name"] != name:
                del self.mcp_servers[name]
            self.mcp_servers[dialog.result["name"]] = dialog.result["config"]
            self._refresh_mcp_list()
    
    def _toggle_mcp(self, name: str, enabled: bool):
        """切换 MCP 启用状态"""
        if name in self.mcp_servers:
            self.mcp_servers[name]["enabled"] = enabled
    
    def _remove_mcp(self, name: str):
        """删除 MCP"""
        if name in self.mcp_servers:
            del self.mcp_servers[name]
            self._refresh_mcp_list()
    
    def _add_mcp(self):
        """添加 MCP"""
        dialog = McpEditDialog(self, "添加 MCP")
        self.wait_window(dialog)
        if dialog.result:
            self.mcp_servers[dialog.result["name"]] = dialog.result["config"]
            self._refresh_mcp_list()
    
    def _import_mcp_json(self):
        """从 JSON 导入 MCP"""
        dialog = JsonImportDialog(self)
        self.wait_window(dialog)
        
        if not dialog.result:
            return
        
        try:
            data = dialog.result
            
            # 处理各种外层包装
            if "mcpServers" in data:
                data = data["mcpServers"]
            elif "mcp" in data:
                data = data["mcp"]
            
            # 导入 MCP 配置
            imported_count = 0
            for name, config in data.items():
                if isinstance(config, dict) and "type" in config:
                    self.mcp_servers[name] = config
                    imported_count += 1
            
            if imported_count > 0:
                self._refresh_mcp_list()
                self.app.show_status(f"成功导入 {imported_count} 个 MCP", "success")
            else:
                messagebox.showerror("错误", "未找到有效的 MCP 配置")
                
        except Exception as e:
            messagebox.showerror("错误", f"导入失败: {str(e)}")
    
    def load_mcp(self, mcp: Dict):
        """加载 MCP 配置"""
        self.mcp_servers = mcp
        self._refresh_mcp_list()
    
    def get_mcp(self) -> Dict:
        """获取 MCP 配置"""
        return self.mcp_servers
    
    def load_compaction(self, config: Dict):
        """加载压缩配置"""
        self.auto_var.set(config.get("auto", True))
        self.prune_var.set(config.get("prune", True))
        
        self.reserved_entry.delete(0, "end")
        self.reserved_entry.insert(0, str(config.get("reserved", 20000)))
    
    def get_compaction(self) -> Dict:
        """获取压缩配置"""
        return {
            "auto": self.auto_var.get(),
            "prune": self.prune_var.get(),
            "reserved": int(self.reserved_entry.get().strip() or "20000")
        }


class InstructionsFrame(ctk.CTkFrame):
    """提示词文件编辑框架"""
    
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.agents_md_path = get_agents_md_path()
        self._create_widgets()
        self._load_file()
    
    def _create_widgets(self):
        """创建界面组件"""
        # 文件路径
        path_frame = ctk.CTkFrame(self)
        path_frame.pack(fill="x", padx=20, pady=5)
        
        ctk.CTkLabel(path_frame, text="文件路径:", font=(FONT_FAMILY, FONT_SIZE_NORMAL)).pack(side="left", padx=5)
        self.path_label = ctk.CTkLabel(
            path_frame, text=str(self.agents_md_path), 
            font=(FONT_FAMILY, FONT_SIZE_SMALL), text_color="gray"
        )
        self.path_label.pack(side="left", fill="x", expand=True, padx=5)
        
        self.open_folder_btn = ctk.CTkButton(
            path_frame, text="打开目录", width=100,
            command=self._open_folder,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.open_folder_btn.pack(side="right", padx=5)
        
        # 编辑器
        self.text_editor = ctk.CTkTextbox(self, wrap="word", font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.text_editor.pack(fill="both", expand=True, padx=20, pady=10)
        
        # 按钮框架
        btn_frame = ctk.CTkFrame(self)
        btn_frame.pack(fill="x", padx=20, pady=10)
        
        self.reload_btn = ctk.CTkButton(
            btn_frame, text="重新加载", command=self._load_file, width=120,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.reload_btn.pack(side="left", padx=5)
        
        self.save_btn = ctk.CTkButton(
            btn_frame, text="保存提示词", command=self._save_file,
            fg_color="green", hover_color="darkgreen", width=120,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.save_btn.pack(side="right", padx=5)
    
    def _load_file(self):
        """加载文件内容"""
        self.text_editor.delete("1.0", "end")
        
        if self.agents_md_path.exists():
            try:
                content = self.agents_md_path.read_text(encoding="utf-8")
                self.text_editor.insert("1.0", content)
            except Exception as e:
                self.app.show_status(f"读取文件失败: {str(e)}", "error")
        else:
            self.text_editor.insert("1.0", "# 全局提示词\n\n在此添加全局指令...")
    
    def _save_file(self):
        """保存文件"""
        try:
            self.agents_md_path.parent.mkdir(parents=True, exist_ok=True)
            content = self.text_editor.get("1.0", "end-1c")
            self.agents_md_path.write_text(content, encoding="utf-8")
            self.app.show_status("提示词已保存", "success")
        except Exception as e:
            self.app.show_status(f"保存文件失败: {str(e)}", "error")
    
    def _open_folder(self):
        """打开文件所在目录"""
        folder = self.agents_md_path.parent
        if folder.exists():
            system = platform.system()
            if system == "Windows":
                os.startfile(folder)
            elif system == "Darwin":
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')


class App(ctk.CTk):
    """主应用窗口"""
    
    def __init__(self):
        super().__init__()
        
        self.title(APP_NAME)
        self.geometry(WINDOW_SIZE)
        
        # 设置主题
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")
        
        # 配置文件路径
        self.config_path = get_opencode_config_path()
        self.config = {}
        
        self._create_widgets()
        self._load_config(silent=True)
    
    def _create_widgets(self):
        """创建主界面组件"""
        # 顶部工具栏
        toolbar = ctk.CTkFrame(self, height=55)
        toolbar.pack(fill="x", padx=10, pady=5)
        toolbar.pack_propagate(False)
        
        ctk.CTkLabel(
            toolbar, text=APP_NAME, font=(FONT_FAMILY, FONT_SIZE_TITLE, "bold")
        ).pack(side="left", padx=10)
        
        # 配置文件路径显示
        self.config_path_label = ctk.CTkLabel(
            toolbar, text=f"配置: {self.config_path}",
            font=(FONT_FAMILY, FONT_SIZE_SMALL), text_color="gray"
        )
        self.config_path_label.pack(side="left", padx=20)
        
        # 状态标签
        self.status_label = ctk.CTkLabel(
            toolbar, text="", font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.status_label.pack(side="left", padx=20)
        
        # 按钮
        self.reload_btn = ctk.CTkButton(
            toolbar, text="重新加载", command=lambda: self._load_config(silent=False), width=100,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.reload_btn.pack(side="right", padx=5)
        
        self.save_btn = ctk.CTkButton(
            toolbar, text="保存配置", command=self._save_config,
            fg_color="green", hover_color="darkgreen", width=100,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.save_btn.pack(side="right", padx=5)
        
        self.open_config_btn = ctk.CTkButton(
            toolbar, text="打开配置文件", command=self._open_config_file, width=120,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL)
        )
        self.open_config_btn.pack(side="right", padx=5)
        
        self.export_btn = ctk.CTkButton(
            toolbar, text="导出配置", command=self._export_config, width=100,
            font=(FONT_FAMILY, FONT_SIZE_NORMAL),
            fg_color="#D4A017", hover_color="#B8860B"
        )
        self.export_btn.pack(side="right", padx=5)
        
        # 主内容区域 - 标签页
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 创建标签页
        self.tab_provider = self.tabview.add("Provider 管理")
        self.tab_mcp_compaction = self.tabview.add("MCP与上下文")
        self.tab_instructions = self.tabview.add("全局提示词")
        
        # 设置标签字体
        self.tabview._segmented_button.configure(font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        
        # Provider 标签页
        self.provider_frame = ProviderFrame(self.tab_provider, self)
        self.provider_frame.pack(fill="both", expand=True)
        
        # MCP与上下文标签页
        self.mcp_compaction_frame = McpCompactionFrame(self.tab_mcp_compaction, self)
        self.mcp_compaction_frame.pack(fill="both", expand=True)
        
        # 提示词标签页
        self.instructions_frame = InstructionsFrame(self.tab_instructions, self)
        self.instructions_frame.pack(fill="both", expand=True)
    
    def show_status(self, message: str, msg_type: str = "info"):
        """显示状态信息"""
        color_map = {
            "success": "green",
            "error": "red",
            "info": "gray",
            "warning": "orange"
        }
        color = color_map.get(msg_type, "gray")
        self.status_label.configure(text=message, text_color=color)
        
        # 5秒后自动清除
        self.after(5000, lambda: self.status_label.configure(text=""))
    
    def _open_config_file(self):
        """打开配置文件"""
        if not self.config_path.exists():
            self.show_status("配置文件不存在", "error")
            return
        
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(self.config_path)
            elif system == "Darwin":
                os.system(f'open "{self.config_path}"')
            else:
                os.system(f'xdg-open "{self.config_path}"')
        except Exception as e:
            self.show_status(f"打开文件失败: {str(e)}", "error")
    
    def _load_config(self, silent=True):
        """加载配置文件"""
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    self.config = parse_jsonc(content)
            else:
                self.config = {"$schema": "https://opencode.ai/config.json"}
            
            # 加载 Provider 配置
            providers = self.config.get("provider", {})
            
            # 从 auth.json 加载 API Key
            auth_data = load_auth_json()
            for name, provider in providers.items():
                if name in auth_data and "key" in auth_data[name]:
                    provider.setdefault("options", {})["apiKey"] = auth_data[name]["key"]
            
            self.provider_frame.load_providers(providers)
            
            # 加载压缩配置
            compaction = self.config.get("compaction", {})
            self.mcp_compaction_frame.load_compaction(compaction)
            
            # 加载 MCP 配置
            mcp = self.config.get("mcp", {})
            self.mcp_compaction_frame.load_mcp(mcp)
            
            # 默认选中第一个 provider
            if providers:
                first_name = next(iter(providers))
                self.provider_frame._select_provider(first_name)
            
            if not silent:
                self.show_status("配置已加载", "success")
            
        except json.JSONDecodeError as e:
            self.show_status(f"配置文件格式错误: {str(e)}", "error")
            print(f"JSON 解析错误: {e}")  # 调试用
        except Exception as e:
            self.show_status(f"加载配置失败: {str(e)}", "error")
            print(f"加载错误: {e}")  # 调试用
    
    def _save_config(self):
        """保存配置文件（精准编辑，不覆盖其他配置）"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 收集 Provider 配置
            providers = self.provider_frame.get_providers()
            
            # 加载现有配置（保留所有其他字段）
            existing_config = {}
            if self.config_path.exists():
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        existing_config = parse_jsonc(content)
                except:
                    pass
            
            # 确保 $schema 存在
            if "$schema" not in existing_config:
                existing_config["$schema"] = "https://opencode.ai/config.json"
            
            # 加载现有 auth.json
            auth_data = load_auth_json()
            
            # 获取我们管理的 provider 名称列表
            managed_provider_names = set(providers.keys()) if providers else set()
            
            # 更新 provider 配置（只更新我们管理的 provider）
            if providers:
                # 获取现有的 provider 配置（保留用户手动添加的）
                existing_providers = existing_config.get("provider", {})
                
                for name, provider in providers.items():
                    api_key = provider["options"].get("apiKey", "")
                    
                    # 写入 auth.json
                    if api_key:
                        auth_data[name] = {
                            "type": "api",
                            "key": api_key
                        }
                    
                    # 获取现有的 provider 配置（保留其他字段如 name、env 等）
                    existing_provider = existing_providers.get(name, {})
                    
                    # 写入 npm 字段
                    if "npm" in provider:
                        existing_provider["npm"] = provider["npm"]
                    
                    # 写入 name 字段
                    if "name" in provider:
                        existing_provider["name"] = provider["name"]
                    
                    # 更新 options（只更新 baseURL，保留其他 options）
                    existing_options = existing_provider.get("options", {})
                    existing_options["baseURL"] = ensure_v1_in_url(provider["options"]["baseURL"])
                    existing_provider["options"] = existing_options
                    
                    # 更新 models
                    existing_models = existing_provider.get("models", {})
                    
                    for model_id, model_data in provider.get("models", {}).items():
                        # 获取现有的 model 配置（保留其他字段）
                        existing_model = existing_models.get(model_id, {})
                        
                        if "limit" in model_data:
                            existing_model["limit"] = model_data["limit"]
                        
                        if "modalities" in model_data:
                            existing_model["modalities"] = model_data["modalities"]
                        
                        options = model_data.get("options", {})
                        if options:
                            existing_model["options"] = options
                        
                        # 保存 variants（如果有）
                        variants = model_data.get("variants", {})
                        if variants:
                            existing_model["variants"] = variants
                        
                        existing_models[model_id] = existing_model
                    
                    existing_provider["models"] = existing_models
                    existing_providers[name] = existing_provider
                
                # 删除不在管理列表中的 provider
                providers_to_delete = [name for name in existing_providers if name not in providers]
                for name in providers_to_delete:
                    del existing_providers[name]
                
                existing_config["provider"] = existing_providers
            # 注意：如果 providers 为空，不删除 existing_config["provider"]
            # 因为用户可能有其他手动添加的 provider
            
            # 更新 compaction 配置
            compaction_config = self.mcp_compaction_frame.get_compaction()
            if compaction_config:
                existing_config["compaction"] = compaction_config
            
            # 更新 MCP 配置
            mcp_config = self.mcp_compaction_frame.get_mcp()
            if mcp_config:
                existing_config["mcp"] = mcp_config
            # 注意：如果 compaction_config 为空，不删除 existing_config["compaction"]
            
            # 保存文件
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(existing_config, f, indent=2, ensure_ascii=False)
            
            # 保存 auth.json
            save_auth_json(auth_data)
            
            # 更新内存中的配置
            self.config = existing_config
            
            self.show_status("配置已保存", "success")
            
        except Exception as e:
            self.show_status(f"保存配置失败: {str(e)}", "error")
    
    def _export_config(self):
        """导出配置（包含明文 API Key）"""
        try:
            # 弹出警告
            warning_msg = (
                "⚠️ 警告 ⚠️\n\n"
                "导出的配置文件将包含所有 API Key 的明文！\n\n"
                "请务必：\n"
                "1. 不要将此文件提交到版本控制\n"
                "2. 不要分享给不可信的人\n"
                "3. 妥善保管此文件\n\n"
                "确定要继续导出吗？"
            )
            
            if not messagebox.askyesno("安全警告", warning_msg):
                return
            
            # 选择保存路径
            file_path = filedialog.asksaveasfilename(
                title="导出配置",
                defaultextension=".json",
                filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
                initialfile="opencode-export.json"
            )
            
            if not file_path:
                return
            
            # 读取现有配置
            config = {}
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    lines = content.split("\n")
                    cleaned_lines = [l for l in lines if not l.strip().startswith("//")]
                    config = json.loads("\n".join(cleaned_lines))
            
            # 读取 auth.json
            auth_data = load_auth_json()
            
            # 将 API Key 合并到配置中
            if "provider" in config:
                for name, provider in config["provider"].items():
                    if name in auth_data and "key" in auth_data[name]:
                        if "options" not in provider:
                            provider["options"] = {}
                        provider["options"]["apiKey"] = auth_data[name]["key"]
            
            # 保存导出文件
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            self.show_status(f"已导出到: {file_path}", "success")
            
            # 询问是否打开
            if messagebox.askyesno("导出成功", f"配置已导出到:\n{file_path}\n\n是否立即打开？"):
                system = platform.system()
                if system == "Windows":
                    os.startfile(file_path)
                elif system == "Darwin":
                    os.system(f'open "{file_path}"')
                else:
                    os.system(f'xdg-open "{file_path}"')
            
        except Exception as e:
            self.show_status(f"导出失败: {str(e)}", "error")


def main():
    """主函数"""
    if platform.system() == "Windows":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
