#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Easy-Open-Kilo-Code: OpenCode & KiloCode 跨平台图形化配置编辑器
基于 Flet 0.28.3 重构，单文件、高分屏适配、现代 Material 3 界面。
"""

import json
import os
import sys
import platform
import re
import threading
import time
import subprocess
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

import requests
import platformdirs
import flet as ft


# ████████████████████████████████████████████████████████████████████████████████
# ██  SECTION 1: 常量定义、协议映射与跨平台字体配置
# ████████████████████████████████████████████████████████████████████████████████

APP_NAME = "Easy OpenCode & KiloCode 配置编辑器"
APP_VERSION = "2.0.0"
WINDOW_WIDTH = 1450
WINDOW_HEIGHT = 880

# 新添加模型的默认上下文/输出限制（单位：token）
DEFAULT_MODEL_CONTEXT = 500000
DEFAULT_MODEL_OUTPUT = 64000


def get_system_font_family() -> str:
    """获取兼容 Ubuntu Desktop、Windows 以及 macOS 的最推荐字体。
    - Windows: 优先使用 'Microsoft YaHei' (微软雅黑)、'Segoe UI'
    - Ubuntu/Linux Desktop: 优先使用 'Noto Sans CJK SC' (思源黑体)、'Ubuntu'、'WenQuanYi Micro Hei'
    - macOS: 优先使用 'PingFang SC'
    """
    if sys.platform == "win32":
        return "Microsoft YaHei, Segoe UI, sans-serif"
    elif sys.platform.startswith("linux"):
        return "Noto Sans CJK SC, Ubuntu, WenQuanYi Micro Hei, DejaVu Sans, sans-serif"
    elif sys.platform == "darwin":
        return "PingFang SC, Helvetica Neue, sans-serif"
    return "sans-serif"


# Provider 协议统一定义
PROTOCOLS = {
    "openai_standard": {
        "name": "OpenAI Compatible",
        "npm": "@ai-sdk/openai-compatible",
        "api_version": "v1",
    },
    "openai_response": {
        "name": "OpenAI Responses",
        "npm": "@ai-sdk/openai",
        "api_version": "v1",
    },
    "gemini_native": {
        "name": "Gemini Native",
        "npm": "@ai-sdk/google",
        "api_version": "v1beta",
    },
    "grok_native": {
        "name": "Grok Native",
        "npm": "@ai-sdk/xai",
        "api_version": "v1",
    },
}


def npm_for_protocol(protocol: str) -> str:
    """返回协议对应的 OpenCode AI SDK npm 包。"""
    return PROTOCOLS.get(protocol, PROTOCOLS["openai_standard"])["npm"]


def protocol_for_npm(npm_package: str) -> str:
    """根据 OpenCode Provider 的 npm 包反推协议名称。"""
    for protocol, config in PROTOCOLS.items():
        if config["npm"] == npm_package:
            return protocol
    return "openai_standard"


def default_model_variants(protocol: str, model_id: str = "") -> Dict[str, Dict[str, Any]]:
    """生成与协议一致的默认思考/推理变体配置。"""
    if protocol == "gemini_native":
        return {
            level: {
                "thinkingConfig": {"includeThoughts": True, "thinkingLevel": level}
            }
            for level in ["low", "medium", "high"]
        }

    return {
        level: {"reasoningEffort": level}
        for level in ["max", "xhigh", "high", "medium", "low", "none"]
    }


def thinking_field_for_model(protocol: str, model_id: str = "") -> str:
    """返回协议原生思考控制字段名。"""
    if protocol == "gemini_native":
        return "thinkingConfig.thinkingLevel"
    return "reasoningEffort"


def build_variant_option(
    protocol: str, model_id: str, level: str, thinking_field: str
) -> Dict[str, Any]:
    """将界面中的变体档位转换为协议要求的模型选项结构。"""
    if protocol == "gemini_native":
        return {
            "thinkingConfig": {"includeThoughts": True, "thinkingLevel": level}
        }
    return {thinking_field: level}


def safe_update(control: Optional[ft.Control], page: Optional[ft.Page] = None):
    """安全更新控件，确保控件已挂载到页面后再调用 update。"""
    try:
        if control is not None and getattr(control, "page", None) is not None:
            control.update()
        elif page is not None and hasattr(page, "update"):
            page.update()
    except Exception:
        pass



# ████████████████████████████████████████████████████████████████████████████████
# ██  SECTION 2: 纯算法层 - JSONC 解析与 MCP 配置格式规范化
# ████████████████████████████████████████████████████████████████████████████████

def parse_jsonc(content: str) -> Dict:
    """解析 JSONC 内容（支持多行注释、单行注释以及尾随逗号容错）。"""
    # 移除多行注释 /* ... */
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

    # 移除单行注释 // ...
    lines = content.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('//'):
            continue
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


def normalize_mcp_config(config: Dict) -> Dict:
    """规范化 MCP 配置，兼容多种 IDE 格式（Cursor/Windsurf/OpenCode/KiloCode）。"""
    normalized = {}

    for name, server in config.items():
        if not isinstance(server, dict):
            continue

        entry = dict(server)

        # 1. 自动推断 type
        if "type" not in entry:
            if "command" in entry:
                entry["type"] = "local"
            elif "url" in entry:
                entry["type"] = "remote"
            else:
                continue

        # 2. 规范化 local 类型的 command 字段
        if entry["type"] == "local":
            command = entry.get("command")
            args = entry.get("args", [])

            # Cursor/Windsurf 格式：command 是字符串，args 是数组
            if isinstance(command, str):
                entry["command"] = [command] + (args if isinstance(args, list) else [])
                if "args" in entry:
                    del entry["args"]

            if not isinstance(entry.get("command"), list):
                continue

        # 3. 补全 enabled 字段（默认 True）
        if "enabled" not in entry:
            entry["enabled"] = True

        normalized[name] = entry

    return normalized



# ████████████████████████████████████████████████████████████████████████████████
# ██  SECTION 3: 纯算法层 - 跨平台路径与凭据管理
# ████████████████████████████████████████████████████████████████████████████████

APP_CONFIG_DIR = Path(platformdirs.user_config_dir("easy-open-kilo-code"))
APP_CONFIG_FILE = APP_CONFIG_DIR / "app-settings.json"


def load_app_settings() -> Dict:
    """加载程序自身的用户偏好设置。"""
    if APP_CONFIG_FILE.exists():
        try:
            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_app_settings(settings: Dict):
    """持久化保存程序自身的用户偏好设置。"""
    APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def _brand_config_dir(brand: str) -> Path:
    """获取指定品牌的全局配置目录。"""
    return Path.home() / ".config" / ("opencode" if brand == "OpenCode" else "kilo")


def _brand_config_path(brand: str) -> Path:
    """获取指定品牌的全局配置文件路径（优先查找 .jsonc，其次 .json）。"""
    config_dir = _brand_config_dir(brand)
    if brand == "OpenCode":
        jsonc_path = config_dir / "opencode.jsonc"
        json_path = config_dir / "opencode.json"
    else:
        jsonc_path = config_dir / "kilo.jsonc"
        json_path = config_dir / "kilo.json"

    if jsonc_path.exists():
        return jsonc_path
    if json_path.exists():
        return json_path
    return jsonc_path


def _brand_auth_json_path(brand: str) -> Path:
    """获取指定品牌的 auth.json 密钥库路径。"""
    if brand == "KiloCode":
        return Path.home() / ".local" / "share" / "kilo" / "auth.json"
    auth_path = os.environ.get("OPENCODE_AUTH_PATH")
    if auth_path:
        return Path(auth_path)
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"


def _brand_agents_md_path(brand: str) -> Path:
    """获取指定品牌的全局 AGENTS.md 路径。"""
    return _brand_config_dir(brand) / "AGENTS.md"


def _default_schema_url(brand: str) -> str:
    """返回品牌对应的默认 $schema 地址。"""
    return "https://opencode.ai/config.json" if brand == "OpenCode" else "https://app.kilo.ai/config.json"


def _to_k_display(value: int) -> str:
    """将数值转换为 K 单位显示。"""
    if value >= 1000 and value % 1000 == 0:
        return str(value // 1000)
    return str(value)


def _parse_k_display(text: str, default_k_value: int) -> int:
    """解析 K 单位显示文本并返回真实整数值。
    - 智能识别：支持 128、128K、4096、64000 等格式
    """
    raw = str(text).strip().upper()
    if not raw:
        return default_k_value * 1000
    if raw.endswith("K"):
        try:
            return int(float(raw[:-1]) * 1000)
        except ValueError:
            return default_k_value * 1000
    try:
        num = int(raw)
        # 如果 <= 1000，认为是 K 单位简写 (例如 128 -> 128000)；若 > 1000 则保留为确切值 (例如 4096)
        return num * 1000 if num <= 1000 else num
    except ValueError:
        return default_k_value * 1000


def load_auth_json(brand: str = "OpenCode") -> Dict:
    """加载指定品牌的 auth.json 密钥数据。"""
    auth_path = _brand_auth_json_path(brand)
    if auth_path.exists():
        try:
            with open(auth_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_auth_json(auth_data: Dict, brand: str = "OpenCode"):
    """安全保存指定品牌的 auth.json 密钥数据。"""
    auth_path = _brand_auth_json_path(brand)
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    with open(auth_path, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2, ensure_ascii=False)



# ████████████████████████████████████████████████████████████████████████████████
# ██  SECTION 4: 纯算法层 - 网络通信与模型探测/流式测速引擎
# ████████████████████████████████████████████████████████████████████████████████

def clean_base_url(url: str) -> str:
    """清洗 Base URL，去除尾随斜杠。"""
    return url.rstrip("/")


def ensure_protocol_endpoint(url: str, protocol: str) -> str:
    """按协议规范自动补全 API 版本端点。"""
    url = clean_base_url(url.strip())
    if not url:
        return url

    if protocol == "gemini_native":
        url = re.sub(
            r"/v1beta(?:/(?:openai/)?chat/completions|/models/[^/]+:(?:generateContent|streamGenerateContent))$",
            "/v1beta",
            url,
            flags=re.IGNORECASE,
        )
        url = re.sub(r"/v1beta-chat-completions$", "/v1beta", url, flags=re.IGNORECASE)
        url = re.sub(r"/v1(?:/(?:openai/)?chat/completions)$", "/v1", url, flags=re.IGNORECASE)

    api_version = PROTOCOLS.get(protocol, PROTOCOLS["openai_standard"])["api_version"]
    version_path = f"/{api_version}"

    version_match = re.search(r"/v1(?:beta)?(?=/|$|\?|#)", url)
    if version_match:
        return url[:version_match.start()] + version_path
    return url + version_path


def build_model_list_request(base_url: str, api_key: str, protocol: str) -> Dict[str, Any]:
    """构造探测模型列表的 HTTP 请求参数。"""
    base = ensure_protocol_endpoint(base_url, protocol)
    if protocol == "gemini_native":
        return {
            "url": f"{base}/models",
            "headers": {
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            "params": None,
        }
    return {
        "url": f"{base}/models",
        "headers": {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        "params": None,
    }


def parse_model_list(data: Dict[str, Any], protocol: str) -> List[Dict[str, Any]]:
    """解析不同协议的模型列表响应。"""
    models = []
    if protocol == "gemini_native":
        for model in data.get("models", []):
            model_id = model.get("name", "")
            if model_id.startswith("models/"):
                model_id = model_id[len("models/"):]
            if model_id:
                models.append({
                    "id": model_id,
                    "name": model.get("displayName", model_id),
                    "owned_by": "google",
                })
        return models

    for model in data.get("data", []):
        model_id = model.get("id", "")
        if model_id:
            models.append({
                "id": model_id,
                "name": model.get("id", ""),
                "owned_by": model.get("owned_by", ""),
            })
    return models


def probe_models(base_url: str, api_key: str, protocol: str = "openai_standard") -> List[Dict[str, Any]]:
    """向服务端发送 HTTP 请求探测可用模型列表。"""
    request_config = build_model_list_request(base_url, api_key, protocol)
    response = requests.get(
        request_config["url"],
        headers=request_config["headers"],
        params=request_config["params"],
        timeout=12,
    )
    response.raise_for_status()
    return parse_model_list(response.json(), protocol)


def build_model_test_request(
    base_url: str,
    api_key: str,
    protocol: str,
    model_id: str,
    prompt: str,
    max_tokens: int,
    stream: bool = False,
) -> Dict[str, Any]:
    """构造连通性探测或流式测速的 HTTP 请求参数。"""
    base = ensure_protocol_endpoint(base_url, protocol)
    if protocol == "gemini_native":
        clean_model_id = model_id.removeprefix("models/")
        action = "streamGenerateContent" if stream else "generateContent"
        params = {"alt": "sse"} if stream else None
        return {
            "url": f"{base}/models/{clean_model_id}:{action}",
            "headers": {
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            "params": params,
            "payload": {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
        }

    if protocol == "grok_native":
        return {
            "url": f"{base}/responses",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            "params": None,
            "payload": {
                "model": model_id,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt}],
                    }
                ],
                "max_output_tokens": max_tokens,
                **({"stream": True} if stream else {}),
            },
        }

    return {
        "url": f"{base}/chat/completions",
        "headers": {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        "params": None,
        "payload": {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            **({"stream": True} if stream else {}),
        },
    }


def extract_stream_text(data: Dict[str, Any], protocol: str) -> str:
    """从不同协议的 SSE 流式事件 JSON 中提取生成文本。"""
    if protocol == "gemini_native":
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts)

    if protocol == "grok_native":
        if data.get("type") == "response.output_text.delta":
            return data.get("delta", "")
        return ""

    choices = data.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("delta", {}).get("content", "")



# ████████████████████████████████████████████████████████████████████████████████
# ██  SECTION 5: 核心业务逻辑与配置无损合并管理器 (ConfigManager)
# ████████████████████████████████████████████████████████████████████████████████

class ConfigManager:
    """核心配置管理器：纯逻辑实现配置的读写、提取、无损精准合并与多品牌同步。"""

    def __init__(self, brand: str = "OpenCode"):
        self.brand = brand

    @property
    def config_path(self) -> Path:
        return _brand_config_path(self.brand)

    @property
    def auth_path(self) -> Path:
        return _brand_auth_json_path(self.brand)

    @property
    def agents_md_path(self) -> Path:
        return _brand_agents_md_path(self.brand)

    def load_config(self) -> Dict[str, Any]:
        """安全加载主配置文件（保留完整原始结构）。"""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return parse_jsonc(f.read())
            except Exception as e:
                print(f"解析配置文件失败: {e}")
        return {"$schema": _default_schema_url(self.brand)}

    def load_providers_with_keys(self) -> Dict[str, Any]:
        """加载 Providers 并关联合并 auth.json 中的 API Key。"""
        cfg = self.load_config()
        providers = cfg.get("provider", {})
        auth_data = load_auth_json(self.brand)

        for name, provider in providers.items():
            if name in auth_data and "key" in auth_data[name]:
                provider.setdefault("options", {})["apiKey"] = auth_data[name]["key"]
        return providers

    def save_config(
        self,
        providers: Dict[str, Any],
        mcp: Dict[str, Any],
        compaction: Dict[str, Any],
        sync_to_other: bool = False,
    ) -> bool:
        """精准保存配置：
        1. 仅更新管理的字段，保留未在界面开放的其他自定义配置
        2. 将 API Key 提取并安全存储到 auth.json
        3. 若启用同步，调用 sync_to_other_brand 进行精准合并
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        existing_config = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    existing_config = parse_jsonc(f.read())
            except Exception:
                pass

        if "$schema" not in existing_config:
            existing_config["$schema"] = _default_schema_url(self.brand)

        auth_data = load_auth_json(self.brand)

        if providers:
            existing_providers = existing_config.get("provider", {})
            for name, provider in providers.items():
                api_key = provider.get("options", {}).get("apiKey", "")
                if api_key:
                    auth_data[name] = {"type": "api", "key": api_key}

                existing_provider = existing_providers.get(name, {})
                if "npm" in provider:
                    existing_provider["npm"] = provider["npm"]
                if "name" in provider:
                    existing_provider["name"] = provider["name"]

                existing_options = existing_provider.get("options", {})
                protocol = protocol_for_npm(provider.get("npm", ""))
                raw_base_url = provider.get("options", {}).get("baseURL", "")
                existing_options["baseURL"] = ensure_protocol_endpoint(raw_base_url, protocol)
                existing_provider["options"] = existing_options

                # 更新 models
                existing_models = existing_provider.get("models", {})
                ui_model_ids = set(provider.get("models", {}).keys())

                for model_id, model_data in provider.get("models", {}).items():
                    existing_model = existing_models.get(model_id, {})
                    if "limit" in model_data:
                        existing_model["limit"] = model_data["limit"]
                    if "modalities" in model_data:
                        existing_model["modalities"] = model_data["modalities"]

                    options = model_data.get("options", {})
                    if options:
                        existing_model["options"] = options

                    variants = model_data.get("variants", {})
                    if variants:
                        existing_model["variants"] = variants
                    elif "variants" in existing_model and not variants:
                        del existing_model["variants"]

                    existing_models[model_id] = existing_model

                # 删除已移除的模型
                for model_id in list(existing_models.keys()):
                    if model_id not in ui_model_ids:
                        del existing_models[model_id]

                existing_provider["models"] = existing_models
                existing_providers[name] = existing_provider

            # 删除已移除的 provider
            for name in list(existing_providers.keys()):
                if name not in providers:
                    del existing_providers[name]

            existing_config["provider"] = existing_providers

        if compaction:
            existing_config["compaction"] = compaction
        if mcp is not None:
            existing_config["mcp"] = mcp

        # 保存主配置文件
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(existing_config, f, indent=2, ensure_ascii=False)

        # 保存 auth.json
        save_auth_json(auth_data, self.brand)

        if sync_to_other:
            self.sync_to_other_brand(existing_config, auth_data)

        return True

    def sync_to_other_brand(self, source_config: Dict[str, Any], auth_data: Dict[str, Any]):
        """无损精准合并当前品牌配置到目标品牌。"""
        target_brand = "KiloCode" if self.brand == "OpenCode" else "OpenCode"
        target_config_path = _brand_config_path(target_brand)
        target_agents_path = _brand_agents_md_path(target_brand)

        target_config_path.parent.mkdir(parents=True, exist_ok=True)
        _brand_auth_json_path(target_brand).parent.mkdir(parents=True, exist_ok=True)
        target_agents_path.parent.mkdir(parents=True, exist_ok=True)

        target_config = {}
        if target_config_path.exists():
            try:
                with open(target_config_path, "r", encoding="utf-8") as f:
                    target_config = parse_jsonc(f.read())
            except Exception:
                pass

        if "$schema" not in target_config:
            target_config["$schema"] = _default_schema_url(target_brand)

        # 精准合并 Provider
        if "provider" in source_config:
            source_providers = source_config["provider"]
            target_providers = target_config.get("provider", {})

            for name, source_provider in source_providers.items():
                if name in target_providers:
                    target_provider = target_providers[name]
                    target_provider["npm"] = source_provider.get("npm", target_provider.get("npm"))
                    target_provider["name"] = source_provider.get("name", target_provider.get("name"))

                    target_options = target_provider.get("options", {})
                    source_options = source_provider.get("options", {})
                    if "baseURL" in source_options:
                        target_options["baseURL"] = source_options["baseURL"]
                    target_provider["options"] = target_options

                    # 合并 models
                    target_models = target_provider.get("models", {})
                    source_models = source_provider.get("models", {})
                    for model_id, source_model in source_models.items():
                        target_model = target_models.get(model_id, {})
                        if "limit" in source_model:
                            target_model["limit"] = source_model["limit"]
                        if "modalities" in source_model:
                            target_model["modalities"] = source_model["modalities"]
                        if "options" in source_model:
                            target_model["options"] = source_model["options"]
                        if "variants" in source_model:
                            target_model["variants"] = source_model["variants"]
                        elif "variants" in target_model:
                            del target_model["variants"]
                        target_models[model_id] = target_model

                    for model_id in list(target_models.keys()):
                        if model_id not in source_models:
                            del target_models[model_id]

                    target_provider["models"] = target_models
                    target_providers[name] = target_provider
                else:
                    target_providers[name] = source_provider

            for name in list(target_providers.keys()):
                if name not in source_providers:
                    del target_providers[name]

            target_config["provider"] = target_providers

        # 精准合并 MCP
        if "mcp" in source_config:
            source_mcp = source_config["mcp"]
            target_mcp = target_config.get("mcp", {})

            for name, source_server in source_mcp.items():
                if name in target_mcp:
                    target_server = target_mcp[name]
                    for key in ["type", "command", "url", "enabled", "environment", "env", "headers"]:
                        if key in source_server:
                            target_server[key] = source_server[key]
                    target_mcp[name] = target_server
                else:
                    target_mcp[name] = source_server

            for name in list(target_mcp.keys()):
                if name not in source_mcp:
                    del target_mcp[name]

            target_config["mcp"] = target_mcp

        # 合并 compaction
        if "compaction" in source_config:
            target_config["compaction"] = source_config["compaction"]

        with open(target_config_path, "w", encoding="utf-8") as f:
            json.dump(target_config, f, indent=2, ensure_ascii=False)

        if auth_data:
            save_auth_json(auth_data, target_brand)

        if self.agents_md_path.exists():
            content = self.agents_md_path.read_text(encoding="utf-8")
            target_agents_path.write_text(content, encoding="utf-8")

    def get_config_hash(self) -> str:
        """获取当前配置文件的 MD5 哈希。"""
        if not self.config_path.exists():
            return ""
        try:
            with open(self.config_path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return ""

    @staticmethod
    def open_path_in_system(path: Path):
        """跨平台在系统资源管理器中打开文件或目录。"""
        try:
            if platform.system() == "Windows":
                os.startfile(str(path))
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(path)])
            else:
                subprocess.run(["xdg-open", str(path)])
        except Exception as e:
            print(f"打开系统路径失败: {e}")



# ████████████████████████████████████████████████████████████████████████████████
# ██  SECTION 6: Flet 对话框组件 (Dialogs)
# ████████████████████████████████████████████████████████████████████████████████

class ModelSelectorDialog:
    """探测模型的批量勾选添加对话框，支持实时搜索与全选/反选。"""

    def __init__(
        self,
        page: ft.Page,
        models: List[Dict[str, Any]],
        existing_ids: set,
        on_confirm: Callable[[List[Dict[str, Any]]], None],
    ):
        self.page = page
        self.models = models
        self.existing_ids = existing_ids
        self.on_confirm = on_confirm

        self.checkboxes: Dict[str, ft.Checkbox] = {}
        self.search_field = ft.TextField(
            hint_text="搜索模型 ID 或名称...",
            prefix_icon=ft.Icons.SEARCH,
            dense=True,
            on_change=self._on_search_change,
            expand=True,
        )
        self.count_text = ft.Text("已选: 0", weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_400)
        self.list_view = ft.ListView(expand=True, spacing=4)

        self._build_list()

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("探测到的可用模型", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row([
                            self.search_field,
                            ft.OutlinedButton("全选", on_click=self._select_all),
                            ft.OutlinedButton("反选", on_click=self._deselect_all),
                        ]),
                        ft.Container(
                            content=self.list_view,
                            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                            border_radius=8,
                            padding=8,
                            expand=True,
                        ),
                        ft.Row([self.count_text], alignment=ft.MainAxisAlignment.END),
                    ],
                    spacing=10,
                ),
                width=680,
                height=450,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self.close()),
                ft.FilledButton("添加所选模型", icon=ft.Icons.CHECK, on_click=self._confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _build_list(self, query: str = ""):
        self.list_view.controls.clear()
        query = query.lower().strip()

        for m in self.models:
            mid = m["id"]
            mname = m.get("name", mid)
            owned = m.get("owned_by", "")
            is_existing = mid in self.existing_ids

            if query and query not in mid.lower() and query not in mname.lower():
                continue

            if mid not in self.checkboxes:
                cb = ft.Checkbox(
                    label=f"{mid}  ({owned})" if owned else mid,
                    value=False,
                    disabled=is_existing,
                    on_change=self._on_check_changed,
                )
                self.checkboxes[mid] = cb

            cb = self.checkboxes[mid]
            self.list_view.controls.append(cb)

    def _on_search_change(self, e):
        self._build_list(self.search_field.value)
        safe_update(self.list_view, self.page)

    def _on_check_changed(self, e):
        count = sum(1 for cb in self.checkboxes.values() if cb.value)
        self.count_text.value = f"已选: {count}"
        safe_update(self.count_text, self.page)

    def _select_all(self, e):
        for cb in self.checkboxes.values():
            if not cb.disabled:
                cb.value = True
        self._on_check_changed(None)
        safe_update(self.list_view, self.page)

    def _deselect_all(self, e):
        for cb in self.checkboxes.values():
            if not cb.disabled:
                cb.value = False
        self._on_check_changed(None)
        safe_update(self.list_view, self.page)

    def _confirm(self, e):
        selected = [m for m in self.models if self.checkboxes.get(m["id"]) and self.checkboxes[m["id"]].value]
        self.close()
        self.on_confirm(selected)

    def open(self):
        self.page.open(self.dialog)

    def close(self):
        self.page.close(self.dialog)


class JsonImportDialog:
    """原始 JSON/JSONC 批量导入对话框。"""

    def __init__(self, page: ft.Page, on_confirm: Callable[[Dict], None]):
        self.page = page
        self.on_confirm = on_confirm

        self.text_field = ft.TextField(
            multiline=True,
            min_lines=14,
            max_lines=18,
            hint_text="请在此粘贴 JSON 或带注释的 JSONC 内容...",
            expand=True,
        )

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("导入 JSON 配置", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=self.text_field,
                width=650,
                height=380,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self.close()),
                ft.FilledButton("解析并导入", icon=ft.Icons.DOWNLOAD, on_click=self._confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _confirm(self, e):
        content = self.text_field.value.strip()
        if not content:
            return
        try:
            data = parse_jsonc(content)
            self.close()
            self.on_confirm(data)
        except Exception as err:
            self.text_field.error_text = f"JSON 解析失败: {err}"
            safe_update(self.text_field, self.page)

    def open(self):
        self.page.open(self.dialog)

    def close(self):
        self.page.close(self.dialog)


class McpEditDialog:
    """单个 MCP 服务的添加与编辑对话框（支持 Local/Remote 动态表单）。"""

    def __init__(
        self,
        page: ft.Page,
        name: str = "",
        config: Optional[Dict[str, Any]] = None,
        on_confirm: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.page = page
        self.original_name = name
        self.on_confirm = on_confirm
        config = config or {}

        mcp_type = config.get("type", "local")
        command_list = config.get("command", [])
        command_str = " ".join(command_list) if isinstance(command_list, list) else str(command_list or "")
        url_str = config.get("url", "")
        self.enabled = config.get("enabled", True)

        self.name_field = ft.TextField(label="MCP 名称", value=name, dense=True)
        self.type_dropdown = ft.Dropdown(
            label="类型",
            value=mcp_type,
            options=[ft.dropdown.Option("local", "本地 (Local)"), ft.dropdown.Option("remote", "远程 (Remote)")],
            dense=True,
            on_change=self._on_type_change,
        )
        self.command_field = ft.TextField(
            label="启动命令 (空格分隔)",
            value=command_str,
            hint_text="例如: npx -y @modelcontextprotocol/server-filesystem D:/",
            dense=True,
            visible=(mcp_type == "local"),
        )
        self.url_field = ft.TextField(
            label="远程 URL",
            value=url_str,
            hint_text="例如: http://localhost:8000/sse",
            dense=True,
            visible=(mcp_type == "remote"),
        )
        self.enabled_switch = ft.Switch(label="启用此服务", value=self.enabled)

        # 环境变量列表
        self.env_rows: List[ft.Row] = []
        self.env_container = ft.Column(spacing=6)
        raw_env = config.get("environment") or config.get("env") or {}
        for k, v in raw_env.items():
            self._add_env_row(k, str(v))

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("编辑 MCP 服务器" if name else "添加 MCP 服务器", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    [
                        self.name_field,
                        ft.Row([self.type_dropdown, self.enabled_switch], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        self.command_field,
                        self.url_field,
                        ft.Divider(),
                        ft.Row(
                            [
                                ft.Text("环境变量 (Environment)", weight=ft.FontWeight.BOLD),
                                ft.IconButton(icon=ft.Icons.ADD_CIRCLE_OUTLINE, tooltip="添加变量", on_click=lambda e: self._add_env_row()),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Container(
                            content=self.env_container,
                            height=120,
                        ),
                    ],
                    scroll=ft.ScrollMode.ADAPTIVE,
                    spacing=12,
                ),
                width=550,
                height=420,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self.close()),
                ft.FilledButton("保存", icon=ft.Icons.CHECK, on_click=self._confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _on_type_change(self, e):
        is_local = self.type_dropdown.value == "local"
        self.command_field.visible = is_local
        self.url_field.visible = not is_local
        safe_update(self.command_field, self.page)
        safe_update(self.url_field, self.page)

    def _add_env_row(self, key: str = "", val: str = ""):
        k_field = ft.TextField(hint_text="KEY", value=key, dense=True, expand=1)
        v_field = ft.TextField(hint_text="VALUE", value=val, dense=True, expand=1)
        row = ft.Row(spacing=6)
        del_btn = ft.IconButton(
            icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
            icon_color=ft.Colors.RED_400,
            on_click=lambda e: self._remove_env_row(row),
        )
        row.controls = [k_field, v_field, del_btn]
        self.env_rows.append(row)
        self.env_container.controls.append(row)
        safe_update(self.env_container, self.page)

    def _remove_env_row(self, row: ft.Row):
        if row in self.env_rows:
            self.env_rows.remove(row)
            self.env_container.controls.remove(row)
            safe_update(self.env_container, self.page)

    def _confirm(self, e):
        name = self.name_field.value.strip()
        if not name:
            self.name_field.error_text = "名称不能为空"
            safe_update(self.name_field, self.page)
            return

        mcp_type = self.type_dropdown.value
        result: Dict[str, Any] = {
            "type": mcp_type,
            "enabled": self.enabled_switch.value,
        }

        if mcp_type == "local":
            cmd = self.command_field.value.strip()
            result["command"] = cmd.split() if cmd else []
        else:
            result["url"] = self.url_field.value.strip()

        env_dict = {}
        for row in self.env_rows:
            k = row.controls[0].value.strip()
            v = row.controls[1].value.strip()
            if k:
                env_dict[k] = v
        if env_dict:
            result["environment"] = env_dict

        self.close()
        if self.on_confirm:
            self.on_confirm(name, result)

    def open(self):
        self.page.open(self.dialog)

    def close(self):
        self.page.close(self.dialog)


class AddVariantDialog:
    """为模型添加推理变体的对话框。"""

    def __init__(
        self,
        page: ft.Page,
        protocol: str,
        existing_variants: List[str],
        on_confirm: Callable[[str], None],
    ):
        self.page = page
        self.on_confirm = on_confirm

        levels = (
            ["low", "medium", "high"]
            if protocol == "gemini_native"
            else ["max", "xhigh", "high", "medium", "low", "none"]
        )
        available = [l for l in levels if l not in existing_variants]
        if not available:
            available = ["custom"]

        self.dropdown = ft.Dropdown(
            label="变体档位 (Variant Level)",
            value=available[0],
            options=[ft.dropdown.Option(lvl) for lvl in available],
            dense=True,
        )

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("添加变体档位", weight=ft.FontWeight.BOLD),
            content=ft.Container(content=self.dropdown, width=320, height=80),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self.close()),
                ft.FilledButton("添加", icon=ft.Icons.ADD, on_click=self._confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _confirm(self, e):
        level = self.dropdown.value
        self.close()
        self.on_confirm(level)

    def open(self):
        self.page.open(self.dialog)

    def close(self):
        self.page.close(self.dialog)



# ████████████████████████████████████████████████████████████████████████████████
# ██  SECTION 7: Flet 视图组件 (ProviderView, McpCompactionView, InstructionsView)
# ████████████████████████████████████████████████████████████████████████████████

class ProviderView(ft.Container):
    """Provider 与模型管理视图：包含左侧 Provider 列表与右侧端点、密钥及模型卡片明细。"""

    def __init__(self, page: ft.Page, on_change: Optional[Callable[[], None]] = None):
        super().__init__(expand=True)
        self.page = page
        self.on_change_callback = on_change
        self.providers_data: Dict[str, Any] = {}
        self.current_provider_name: Optional[str] = None

        self._build_ui()

    def _build_ui(self):
        # 左侧列表
        self.provider_list_col = ft.ListView(expand=True, spacing=6)
        self.left_panel = ft.Container(
            width=280,
            border=ft.border.only(right=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
            padding=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Provider 列表", weight=ft.FontWeight.BOLD, size=16),
                            ft.IconButton(
                                icon=ft.Icons.ADD_CIRCLE,
                                icon_color=ft.Colors.PRIMARY,
                                tooltip="新建 Provider",
                                on_click=self._on_add_provider_click,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=1),
                    self.provider_list_col,
                ],
                expand=True,
            ),
        )

        # 右侧基本设置
        self.name_field = ft.TextField(label="Provider 名称", dense=True, expand=True, on_change=self._on_field_change)
        self.protocol_dropdown = ft.Dropdown(
            label="协议",
            dense=True,
            expand=True,
            options=[
                ft.dropdown.Option("openai_standard", "OpenAI Compatible"),
                ft.dropdown.Option("openai_response", "OpenAI Responses"),
                ft.dropdown.Option("gemini_native", "Gemini Native"),
                ft.dropdown.Option("grok_native", "Grok Native"),
            ],
            on_change=self._on_protocol_change,
        )
        self.base_url_field = ft.TextField(
            label="Base URL",
            dense=True,
            expand=True,
            on_change=self._on_field_change,
            on_blur=self._on_base_url_blur,
        )
        self.api_key_field = ft.TextField(
            label="API Key",
            dense=True,
            password=True,
            can_reveal_password=True,
            expand=True,
            on_change=self._on_field_change,
        )

        self.btn_probe = ft.FilledButton("探测可用模型", icon=ft.Icons.TRAVEL_EXPLORE, on_click=self._on_probe_models)
        self.btn_add_model = ft.OutlinedButton("手动添加模型", icon=ft.Icons.ADD, on_click=self._on_add_model_manual)
        self.btn_test_provider = ft.OutlinedButton("测试当前配置", icon=ft.Icons.NETWORK_CHECK, on_click=self._on_test_provider)

        self.models_list_col = ft.ListView(expand=True, spacing=10)

        self.right_panel = ft.Container(
            expand=True,
            padding=14,
            content=ft.Column(
                [
                    ft.Card(
                        content=ft.Container(
                            padding=14,
                            content=ft.Column(
                                [
                                    ft.Row([self.name_field, self.protocol_dropdown], spacing=12),
                                    ft.Row([self.base_url_field, self.api_key_field], spacing=12),
                                    ft.Row([self.btn_probe, self.btn_add_model, self.btn_test_provider], spacing=10),
                                ],
                                spacing=10,
                            ),
                        ),
                    ),
                    ft.Row(
                        [
                            ft.Text("已配置模型列表", weight=ft.FontWeight.BOLD, size=15),
                            ft.Text("支持调整上下文限额、开启图像识别及推理变体开关", size=12, color=ft.Colors.GREY_400),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    self.models_list_col,
                ],
                expand=True,
                spacing=10,
            ),
        )

        self.content = ft.Row([self.left_panel, self.right_panel], expand=True, spacing=0)

    # ---------------- 业务方法 ----------------

    def load_providers(self, providers: Dict[str, Any]):
        self.providers_data = providers
        self._refresh_provider_list()
        if providers:
            first_name = next(iter(providers))
            self.select_provider(first_name)
        else:
            self.current_provider_name = None
            self._clear_details()

    def get_providers(self) -> Dict[str, Any]:
        self._sync_ui_to_current_provider()
        return self.providers_data

    def _refresh_provider_list(self):
        self.provider_list_col.controls.clear()
        for name, p_data in self.providers_data.items():
            is_selected = (name == self.current_provider_name)
            select_area = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.STORAGE,
                            color=ft.Colors.PRIMARY if is_selected else ft.Colors.GREY_500,
                            size=20,
                        ),
                        ft.Text(
                            name,
                            weight=ft.FontWeight.BOLD if is_selected else ft.FontWeight.NORMAL,
                            color=ft.Colors.PRIMARY if is_selected else None,
                            expand=True,
                        ),
                    ],
                    spacing=8,
                ),
                expand=True,
                on_click=lambda e, n=name: self.select_provider(n),
            )
            tile = ft.Container(
                # 删除按钮与选择区域并列，避免点击删除时触发 Provider 选择事件。
                content=ft.Row(
                    [
                        select_area,
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            icon_size=18,
                            tooltip="删除 Provider",
                            on_click=lambda e, n=name: self._remove_provider(n),
                        ),
                    ],
                    spacing=4,
                ),
                padding=8,
                border_radius=8,
                bgcolor=ft.Colors.SECONDARY_CONTAINER if is_selected else ft.Colors.SURFACE_CONTAINER_HIGHEST,
            )
            self.provider_list_col.controls.append(tile)
        safe_update(self.provider_list_col, self.page)

    def select_provider(self, name: str):
        # 删除后可能仍有一个已排队的点击事件，不能重新选中已不存在的 Provider。
        if name not in self.providers_data:
            return

        if self.current_provider_name:
            self._sync_ui_to_current_provider()

        self.current_provider_name = name
        p_data = self.providers_data.get(name, {})

        self.name_field.value = name
        self.name_field.disabled = False
        npm = p_data.get("npm", "@ai-sdk/openai-compatible")
        self.protocol_dropdown.value = protocol_for_npm(npm)
        self.protocol_dropdown.disabled = False

        options = p_data.get("options", {})
        self.base_url_field.value = options.get("baseURL", "")
        self.base_url_field.disabled = False
        self.api_key_field.value = options.get("apiKey", "")
        self.api_key_field.disabled = False

        self._refresh_provider_list()
        self._refresh_models_list()
        safe_update(self.right_panel, self.page)

    def _sync_ui_to_current_provider(self):
        if not self.current_provider_name or self.current_provider_name not in self.providers_data:
            return
        current_name = self.current_provider_name
        p_data = self.providers_data[current_name]
        new_name = (self.name_field.value or "").strip()

        p_data["npm"] = npm_for_protocol(self.protocol_dropdown.value)
        p_data.setdefault("options", {})["baseURL"] = self.base_url_field.value.strip()
        p_data["options"]["apiKey"] = self.api_key_field.value.strip()
        # Provider 的对象名称也必须与界面名称保持一致，避免只修改配置键名。
        p_data["name"] = new_name or current_name

        # 处理重命名
        if new_name and new_name != current_name:
            self.providers_data[new_name] = self.providers_data.pop(current_name)
            self.current_provider_name = new_name
            self._refresh_provider_list()

    def _clear_details(self):
        self.name_field.value = ""
        self.name_field.disabled = True
        self.base_url_field.value = ""
        self.base_url_field.disabled = True
        self.api_key_field.value = ""
        self.api_key_field.disabled = True
        self.protocol_dropdown.disabled = True
        self.models_list_col.controls.clear()
        safe_update(self.right_panel, self.page)

    def _on_add_provider_click(self, e):
        idx = 1
        base_name = "New Provider"
        name = base_name
        while name in self.providers_data:
            idx += 1
            name = f"{base_name} {idx}"

        self.providers_data[name] = {
            "name": name,
            "npm": "@ai-sdk/openai-compatible",
            "options": {"baseURL": "https://api.openai.com/v1", "apiKey": ""},
            "models": {},
        }
        self.select_provider(name)
        self._notify_change()

    def _remove_provider(self, name: str):
        if name not in self.providers_data:
            return

        was_selected = self.current_provider_name == name
        if was_selected:
            # 先清空当前状态，防止 select_provider() 将已删除项的表单内容
            # 同步到删除后的第一个 Provider。
            self.current_provider_name = None

        del self.providers_data[name]
        if was_selected:
            next_name = next(iter(self.providers_data), None)
            if next_name:
                self.select_provider(next_name)
            else:
                self._clear_details()
                self._refresh_provider_list()
        else:
            self._refresh_provider_list()
        self._notify_change()

    def _on_protocol_change(self, e):
        if self.current_provider_name:
            protocol = self.protocol_dropdown.value
            current_url = self.base_url_field.value.strip()
            if current_url:
                self.base_url_field.value = ensure_protocol_endpoint(current_url, protocol)
                safe_update(self.base_url_field, self.page)
            self._sync_ui_to_current_provider()
            self._notify_change()

    def _on_base_url_blur(self, e):
        if self.current_provider_name:
            protocol = self.protocol_dropdown.value
            url = self.base_url_field.value.strip()
            if url:
                formatted = ensure_protocol_endpoint(url, protocol)
                if formatted != url:
                    self.base_url_field.value = formatted
                    safe_update(self.base_url_field, self.page)
            self._sync_ui_to_current_provider()

    def _on_field_change(self, e):
        self._notify_change()

    def _notify_change(self):
        if self.on_change_callback:
            self.on_change_callback()

    # ---------------- 模型列表与操作 ----------------

    def _refresh_models_list(self):
        self.models_list_col.controls.clear()
        if not self.current_provider_name or self.current_provider_name not in self.providers_data:
            return

        p_data = self.providers_data[self.current_provider_name]
        models = p_data.get("models", {})
        protocol = self.protocol_dropdown.value or "openai_standard"

        for model_id, model_data in models.items():
            card = self._create_model_card(model_id, model_data, protocol)
            self.models_list_col.controls.append(card)

        safe_update(self.models_list_col, self.page)

    def _create_model_card(self, model_id: str, model_data: Dict[str, Any], protocol: str) -> ft.Card:
        limit = model_data.get("limit", {})
        context_k = _to_k_display(limit.get("context", DEFAULT_MODEL_CONTEXT))
        output_k = _to_k_display(limit.get("output", DEFAULT_MODEL_OUTPUT))
        has_image = "image" in model_data.get("modalities", {}).get("input", ["text"])

        variants = model_data.get("variants")
        variants_enabled = variants is not None

        # 输入控件
        context_field = ft.TextField(
            label="Context(K)",
            value=context_k,
            width=110,
            dense=True,
            on_change=lambda e, mid=model_id: self._update_model_limit(mid, "context", e.control.value),
        )
        output_field = ft.TextField(
            label="Output(K)",
            value=output_k,
            width=110,
            dense=True,
            on_change=lambda e, mid=model_id: self._update_model_limit(mid, "output", e.control.value),
        )
        image_switch = ft.Switch(
            label="图像",
            value=has_image,
            on_change=lambda e, mid=model_id: self._update_model_image(mid, e.control.value),
        )

        # 变体标签组
        variant_chips_row = ft.Row(spacing=4, wrap=True, expand=True)

        def build_chips():
            variant_chips_row.controls.clear()
            if variants:
                for lvl in variants.keys():
                    chip = ft.Chip(
                        label=ft.Text(lvl),
                        on_delete=lambda e, l=lvl, mid=model_id: self._remove_variant(mid, l),
                    )
                    variant_chips_row.controls.append(chip)

        build_chips()

        btn_add_variant = ft.TextButton(
            "+ 添加变体",
            visible=variants_enabled,
            on_click=lambda e, mid=model_id: self._open_add_variant_dialog(mid, protocol),
        )

        variants_toggle_btn = ft.IconButton(
            icon=ft.Icons.CHECK_CIRCLE if variants_enabled else ft.Icons.BLOCK,
            icon_color=ft.Colors.GREEN_400 if variants_enabled else ft.Colors.RED_400,
            tooltip="点击禁用变体(保存时不写入 variants)" if variants_enabled else "点击启用变体",
            on_click=lambda e, mid=model_id: self._toggle_variants(mid, protocol),
        )

        card = ft.Card(
            content=ft.Container(
                padding=12,
                content=ft.Column(
                    [
                        # 第一行：模型基本信息与测试按钮
                        ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.AUTO_AWESOME, size=18, color=ft.Colors.AMBER_400),
                                        ft.Text(model_id, weight=ft.FontWeight.BOLD, size=14),
                                    ],
                                    spacing=6,
                                ),
                                ft.Row(
                                    [
                                        context_field,
                                        output_field,
                                        image_switch,
                                        ft.IconButton(
                                            icon=ft.Icons.PLAY_ARROW,
                                            tooltip="连通性测试 (发送 'Hi')",
                                            on_click=lambda e, mid=model_id: self._test_model(mid),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.SPEED,
                                            tooltip="流式测速",
                                            on_click=lambda e, mid=model_id: self._test_speed(mid),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.DELETE_OUTLINE,
                                            tooltip="删除模型",
                                            on_click=lambda e, mid=model_id: self._remove_model(mid),
                                        ),
                                    ],
                                    spacing=6,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        # 第二行：推理变体设置
                        ft.Row(
                            [
                                ft.Row(
                                    [
                                        variants_toggle_btn,
                                        ft.Text("推理变体: " + ("已开启" if variants_enabled else "已禁用"), size=12),
                                    ],
                                    spacing=4,
                                ),
                                variant_chips_row,
                                btn_add_variant,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=6,
                ),
            ),
        )
        return card

    def _update_model_limit(self, model_id: str, field: str, value_str: str):
        p_data = self.providers_data.get(self.current_provider_name, {})
        model = p_data.get("models", {}).get(model_id)
        if model:
            val = _parse_k_display(value_str, 500 if field == "context" else 64)
            model.setdefault("limit", {})[field] = val
            self._notify_change()

    def _update_model_image(self, model_id: str, enabled: bool):
        p_data = self.providers_data.get(self.current_provider_name, {})
        model = p_data.get("models", {}).get(model_id)
        if model:
            model.setdefault("modalities", {})["input"] = ["text", "image"] if enabled else ["text"]
            self._notify_change()

    def _toggle_variants(self, model_id: str, protocol: str):
        p_data = self.providers_data.get(self.current_provider_name, {})
        model = p_data.get("models", {}).get(model_id)
        if not model:
            return

        if model.get("variants") is not None:
            model["variants"] = None
        else:
            model["variants"] = default_model_variants(protocol, model_id)

        self._refresh_models_list()
        self._notify_change()

    def _remove_variant(self, model_id: str, level: str):
        p_data = self.providers_data.get(self.current_provider_name, {})
        model = p_data.get("models", {}).get(model_id)
        if model and model.get("variants") and level in model["variants"]:
            del model["variants"][level]
            self._refresh_models_list()
            self._notify_change()

    def _open_add_variant_dialog(self, model_id: str, protocol: str):
        p_data = self.providers_data.get(self.current_provider_name, {})
        model = p_data.get("models", {}).get(model_id, {})
        existing = list(model.get("variants", {}).keys())

        def on_add(level: str):
            tf = thinking_field_for_model(protocol, model_id)
            model.setdefault("variants", {})[level] = build_variant_option(protocol, model_id, level, tf)
            self._refresh_models_list()
            self._notify_change()

        dlg = AddVariantDialog(self.page, protocol, existing, on_add)
        dlg.open()

    def _remove_model(self, model_id: str):
        p_data = self.providers_data.get(self.current_provider_name, {})
        if "models" in p_data and model_id in p_data["models"]:
            del p_data["models"][model_id]
            self._refresh_models_list()
            self._notify_change()

    def _on_add_model_manual(self, e):
        if not self.current_provider_name:
            return

        model_id_field = ft.TextField(label="模型 ID", hint_text="例如: gpt-4o 或 claude-3-5-sonnet")
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("手动添加模型", weight=ft.FontWeight.BOLD),
            content=ft.Container(content=model_id_field, width=380, height=80),
            actions=[
                ft.TextButton("取消", on_click=lambda ev: self.page.close(dlg)),
                ft.FilledButton(
                    "添加",
                    on_click=lambda ev: self._confirm_add_model_manual(model_id_field.value.strip(), dlg),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _confirm_add_model_manual(self, model_id: str, dlg: ft.AlertDialog):
        self.page.close(dlg)
        if not model_id or not self.current_provider_name:
            return

        p_data = self.providers_data[self.current_provider_name]
        protocol = self.protocol_dropdown.value
        p_data.setdefault("models", {})[model_id] = {
            "limit": {"context": DEFAULT_MODEL_CONTEXT, "output": DEFAULT_MODEL_OUTPUT},
            "modalities": {"input": ["text", "image"]},
            "variants": default_model_variants(protocol, model_id),
        }
        self._refresh_models_list()
        self._notify_change()

    def _on_probe_models(self, e):
        if not self.current_provider_name:
            return

        base_url = self.base_url_field.value.strip()
        api_key = self.api_key_field.value.strip()
        protocol = self.protocol_dropdown.value

        if not base_url:
            self._show_snack("请先填写 Base URL", ft.Colors.ORANGE_400)
            return

        self._show_snack("正在探测模型列表...", ft.Colors.BLUE_400)

        def run_probe():
            try:
                models = probe_models(base_url, api_key, protocol)
                if not models:
                    self._show_snack("未能探测到任何可用模型", ft.Colors.AMBER_400)
                    return

                p_data = self.providers_data[self.current_provider_name]
                existing_ids = set(p_data.get("models", {}).keys())

                def on_confirm(selected_models: List[Dict[str, Any]]):
                    for m in selected_models:
                        mid = m["id"]
                        p_data.setdefault("models", {})[mid] = {
                            "limit": {"context": DEFAULT_MODEL_CONTEXT, "output": DEFAULT_MODEL_OUTPUT},
                            "modalities": {"input": ["text", "image"]},
                            "variants": default_model_variants(protocol, mid),
                        }
                    self._refresh_models_list()
                    self._notify_change()
                    self._show_snack(f"已成功添加 {len(selected_models)} 个模型", ft.Colors.GREEN_400)

                dlg = ModelSelectorDialog(self.page, models, existing_ids, on_confirm)
                dlg.open()
            except Exception as err:
                self._show_snack(f"探测失败: {err}", ft.Colors.RED_400)

        threading.Thread(target=run_probe, daemon=True).start()

    def _on_test_provider(self, e):
        """测试当前 Provider 的连通性。"""
        if not self.current_provider_name:
            return
        p_data = self.providers_data[self.current_provider_name]
        models = list(p_data.get("models", {}).keys())
        if not models:
            self._show_snack("当前 Provider 尚未配置任何模型，无法测试", ft.Colors.ORANGE_400)
            return
        self._test_model(models[0])

    def _test_model(self, model_id: str):
        base_url = self.base_url_field.value.strip()
        api_key = self.api_key_field.value.strip()
        protocol = self.protocol_dropdown.value

        self._show_snack(f"正在测试模型 {model_id}...", ft.Colors.BLUE_400)

        def run_test():
            req = build_model_test_request(base_url, api_key, protocol, model_id, "Hi", 16, stream=False)
            start_t = time.time()
            try:
                resp = requests.post(
                    req["url"],
                    headers=req["headers"],
                    json=req["payload"],
                    params=req["params"],
                    timeout=15,
                )
                cost = (time.time() - start_t) * 1000
                if resp.status_code == 200:
                    self._show_snack(f"连通成功! 响应时间: {cost:.0f}ms", ft.Colors.GREEN_400)
                else:
                    self._show_snack(f"测试失败 [{resp.status_code}]: {resp.text[:100]}", ft.Colors.RED_400)
            except Exception as err:
                self._show_snack(f"连通异常: {err}", ft.Colors.RED_400)

        threading.Thread(target=run_test, daemon=True).start()

    def _test_speed(self, model_id: str):
        base_url = self.base_url_field.value.strip()
        api_key = self.api_key_field.value.strip()
        protocol = self.protocol_dropdown.value

        self._show_snack(f"正在对 {model_id} 进行流式测速...", ft.Colors.BLUE_400)

        def run_speed():
            req = build_model_test_request(
                base_url,
                api_key,
                protocol,
                model_id,
                "以'人工智能'为主题写一段50字的简介。",
                128,
                stream=True,
            )
            try:
                start_t = time.time()
                resp = requests.post(
                    req["url"],
                    headers=req["headers"],
                    json=req["payload"],
                    params=req["params"],
                    stream=True,
                    timeout=20,
                )
                if resp.status_code != 200:
                    self._show_snack(f"测速请求失败: HTTP {resp.status_code}", ft.Colors.RED_400)
                    return

                first_token_t = None
                total_chars = 0
                for line in resp.iter_lines():
                    if line:
                        decoded = line.decode("utf-8")
                        if decoded.startswith("data: "):
                            raw_data = decoded[6:].strip()
                            if raw_data == "[DONE]":
                                break
                            try:
                                json_chunk = json.loads(raw_data)
                                text = extract_stream_text(json_chunk, protocol)
                                if text:
                                    if first_token_t is None:
                                        first_token_t = time.time()
                                    total_chars += len(text)
                            except Exception:
                                pass

                end_t = time.time()
                ttft = ((first_token_t or end_t) - start_t) * 1000
                duration = end_t - (first_token_t or start_t)
                speed = (total_chars / duration) if duration > 0 else 0
                self._show_snack(
                    f"首字延迟(TTFT): {ttft:.0f}ms | 生成速度: {speed:.1f} 字/秒",
                    ft.Colors.GREEN_400,
                )
            except Exception as err:
                self._show_snack(f"测速失败: {err}", ft.Colors.RED_400)

        threading.Thread(target=run_speed, daemon=True).start()

    def _show_snack(self, message: str, color: str = ft.Colors.GREEN_400):
        if self.page:
            sb = ft.SnackBar(content=ft.Text(message), bgcolor=color, duration=4000)
            self.page.open(sb)


class McpCompactionView(ft.Container):
    """MCP 服务器与上下文压缩管理视图。"""

    def __init__(self, page: ft.Page, on_change: Optional[Callable[[], None]] = None):
        super().__init__(expand=True)
        self.page = page
        self.on_change_callback = on_change

        self.mcp_data: Dict[str, Any] = {}
        self.compaction_data: Dict[str, Any] = {}

        self._build_ui()

    def _build_ui(self):
        self.mcp_list_col = ft.ListView(expand=True, spacing=8)

        self.switch_auto_compact = ft.Switch(
            label="自动压缩上下文 (autoCompact)",
            on_change=lambda e: self._on_compaction_change(),
        )
        self.switch_prune_output = ft.Switch(
            label="清理旧输出 (prunePreviousOutput)",
            on_change=lambda e: self._on_compaction_change(),
        )
        self.buffer_field = ft.TextField(
            label="缓冲区大小 (compactionBuffer，单位：K)",
            dense=True,
            width=280,
            on_change=lambda e: self._on_compaction_change(),
        )

        self.content = ft.Container(
            content=ft.Column(
                [
                    # 上部分：MCP 服务器管理
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.EXTENSION, color=ft.Colors.PRIMARY, size=24),
                                    ft.Text("MCP 服务器管理", weight=ft.FontWeight.BOLD, size=18),
                                ],
                                spacing=8,
                            ),
                            ft.Row(
                                [
                                    ft.FilledButton("添加 MCP", icon=ft.Icons.ADD, on_click=self._on_add_mcp),
                                    ft.OutlinedButton("导入 JSON", icon=ft.Icons.FILE_DOWNLOAD, on_click=self._on_import_json),
                                ],
                                spacing=10,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=self.mcp_list_col,
                        expand=3,
                        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                        border_radius=8,
                        padding=10,
                    ),
                    ft.Divider(height=1),
                    # 下部分：上下文压缩设置
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.COMPRESS, color=ft.Colors.PRIMARY, size=22),
                            ft.Text("上下文压缩配置 (Context Compaction)", weight=ft.FontWeight.BOLD, size=16),
                        ],
                        spacing=8,
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=14,
                            content=ft.Row(
                                [
                                    self.switch_auto_compact,
                                    self.switch_prune_output,
                                    self.buffer_field,
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_AROUND,
                            ),
                        ),
                    ),
                ],
                expand=True,
                spacing=12,
            ),
            padding=14,
            expand=True,
        )

    def load_mcp(self, mcp: Dict[str, Any]):
        self.mcp_data = dict(mcp)
        self._refresh_mcp_list()

    def get_mcp(self) -> Dict[str, Any]:
        return self.mcp_data

    def load_compaction(self, compaction: Dict[str, Any]):
        self.compaction_data = dict(compaction)
        self.switch_auto_compact.value = self.compaction_data.get("autoCompact", True)
        self.switch_prune_output.value = self.compaction_data.get("prunePreviousOutput", False)
        buf = self.compaction_data.get("compactionBuffer", 20000)
        self.buffer_field.value = _to_k_display(buf)
        safe_update(self.switch_auto_compact, self.page)
        safe_update(self.switch_prune_output, self.page)
        safe_update(self.buffer_field, self.page)

    def get_compaction(self) -> Dict[str, Any]:
        return {
            "autoCompact": self.switch_auto_compact.value,
            "prunePreviousOutput": self.switch_prune_output.value,
            "compactionBuffer": _parse_k_display(self.buffer_field.value, 20),
        }

    def _refresh_mcp_list(self):
        self.mcp_list_col.controls.clear()
        for name, srv in self.mcp_data.items():
            card = self._create_mcp_card(name, srv)
            self.mcp_list_col.controls.append(card)
        safe_update(self.mcp_list_col, self.page)

    def _create_mcp_card(self, name: str, srv: Dict[str, Any]) -> ft.Card:
        mcp_type = srv.get("type", "local")
        cmd_or_url = " ".join(srv.get("command", [])) if mcp_type == "local" else srv.get("url", "")
        enabled = srv.get("enabled", True)

        sw = ft.Switch(
            value=enabled,
            on_change=lambda e, n=name: self._toggle_mcp(n, e.control.value),
        )

        return ft.Card(
            content=ft.Container(
                padding=10,
                content=ft.Row(
                    [
                        sw,
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(name, weight=ft.FontWeight.BOLD, size=14),
                                        ft.Container(
                                            content=ft.Text(mcp_type.upper(), size=10, color=ft.Colors.WHITE),
                                            bgcolor=ft.Colors.BLUE_700 if mcp_type == "local" else ft.Colors.PURPLE_700,
                                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                            border_radius=4,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                ft.Text(
                                    cmd_or_url,
                                    size=12,
                                    color=ft.Colors.GREY_400,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    max_lines=1,
                                ),
                            ],
                            expand=True,
                            spacing=4,
                        ),
                        ft.Row(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.EDIT_OUTLINED,
                                    tooltip="编辑",
                                    on_click=lambda e, n=name, c=srv: self._edit_mcp(n, c),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    tooltip="删除",
                                    on_click=lambda e, n=name: self._remove_mcp(n),
                                ),
                            ],
                            spacing=4,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ),
        )

    def _toggle_mcp(self, name: str, enabled: bool):
        if name in self.mcp_data:
            self.mcp_data[name]["enabled"] = enabled
            self._notify_change()

    def _remove_mcp(self, name: str):
        if name in self.mcp_data:
            del self.mcp_data[name]
            self._refresh_mcp_list()
            self._notify_change()

    def _on_add_mcp(self, e):
        def on_confirm(name: str, config: Dict[str, Any]):
            self.mcp_data[name] = config
            self._refresh_mcp_list()
            self._notify_change()

        dlg = McpEditDialog(self.page, on_confirm=on_confirm)
        dlg.open()

    def _edit_mcp(self, name: str, srv: Dict[str, Any]):
        def on_confirm(new_name: str, config: Dict[str, Any]):
            if new_name != name and name in self.mcp_data:
                del self.mcp_data[name]
            self.mcp_data[new_name] = config
            self._refresh_mcp_list()
            self._notify_change()

        dlg = McpEditDialog(self.page, name=name, config=srv, on_confirm=on_confirm)
        dlg.open()

    def _on_import_json(self, e):
        def on_confirm(data: Dict):
            normalized = normalize_mcp_config(data)
            if not normalized:
                sb = ft.SnackBar(content=ft.Text("未能识别出有效的 MCP 配置"), bgcolor=ft.Colors.ORANGE_400)
                self.page.open(sb)
                return

            self.mcp_data.update(normalized)
            self._refresh_mcp_list()
            self._notify_change()
            sb = ft.SnackBar(content=ft.Text(f"成功导入 {len(normalized)} 个 MCP 服务"), bgcolor=ft.Colors.GREEN_400)
            self.page.open(sb)

        dlg = JsonImportDialog(self.page, on_confirm=on_confirm)
        dlg.open()

    def _on_compaction_change(self):
        self._notify_change()

    def _notify_change(self):
        if self.on_change_callback:
            self.on_change_callback()


class InstructionsView(ft.Container):
    """全局提示词 (AGENTS.md) 查看与在线轻量级文本编辑器。"""

    def __init__(self, page: ft.Page, brand: str = "OpenCode"):
        super().__init__(expand=True)
        self.page = page
        self.brand = brand
        self.agents_path = _brand_agents_md_path(self.brand)

        self._build_ui()
        self.load_file()

    def _build_ui(self):
        self.path_text = ft.Text(f"路径: {self.agents_path}", size=12, color=ft.Colors.GREY_400, italic=True)
        self.text_editor = ft.TextField(
            multiline=True,
            expand=True,
            min_lines=20,
            border_radius=8,
            hint_text="可以在此编写专属于你的全局角色或提示词指令 (AGENTS.md)...",
        )

        self.content = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.DESCRIPTION, color=ft.Colors.PRIMARY, size=24),
                                    ft.Text("全局提示词 (AGENTS.md)", weight=ft.FontWeight.BOLD, size=18),
                                ],
                                spacing=8,
                            ),
                            ft.Row(
                                [
                                    ft.OutlinedButton("重新加载", icon=ft.Icons.REFRESH, on_click=lambda e: self.load_file(silent=False)),
                                    ft.FilledButton("保存文件", icon=ft.Icons.SAVE, on_click=lambda e: self.save_file()),
                                    ft.OutlinedButton("打开所在文件夹", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e: self.open_folder()),
                                ],
                                spacing=10,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    self.path_text,
                    self.text_editor,
                ],
                expand=True,
                spacing=10,
            ),
            padding=14,
            expand=True,
        )

    def switch_brand(self, brand: str):
        self.brand = brand
        self.agents_path = _brand_agents_md_path(brand)
        self.path_text.value = f"路径: {self.agents_path}"
        self.load_file(silent=True)
        safe_update(self.path_text, self.page)

    def load_file(self, silent: bool = True):
        if self.agents_path.exists():
            try:
                content = self.agents_path.read_text(encoding="utf-8")
                self.text_editor.value = content
            except Exception as e:
                self.text_editor.value = f"读取失败: {e}"
        else:
            self.text_editor.value = ""

        safe_update(self.text_editor, self.page)
        if not silent and self.page:
            sb = ft.SnackBar(content=ft.Text("提示词已重新加载"), bgcolor=ft.Colors.GREEN_400)
            self.page.open(sb)

    def save_file(self):
        try:
            self.agents_path.parent.mkdir(parents=True, exist_ok=True)
            self.agents_path.write_text(self.text_editor.value, encoding="utf-8")
            if self.page:
                sb = ft.SnackBar(content=ft.Text(f"已保存至 {self.agents_path.name}"), bgcolor=ft.Colors.GREEN_400)
                self.page.open(sb)
        except Exception as e:
            if self.page:
                sb = ft.SnackBar(content=ft.Text(f"保存失败: {e}"), bgcolor=ft.Colors.RED_400)
                self.page.open(sb)

    def open_folder(self):
        ConfigManager.open_path_in_system(self.agents_path.parent)



# ████████████████████████████████████████████████████████████████████████████████
# ██  SECTION 8: Flet GUI 顶层应用与主窗口 (EasyOpenKiloApp)
# ████████████████████████████████████████████████████████████████████████████████

class EasyOpenKiloApp:
    """应用主控制器：负责整体布局、品牌切换、自动保存定时调度及状态展示。"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.brand = "OpenCode"
        self.auto_save_enabled = False
        self.sync_enabled = False

        self._auto_save_timer: Optional[threading.Timer] = None
        self._config_manager = ConfigManager(self.brand)
        self._last_config_hash = ""

        self._load_app_settings()
        self._setup_window()
        self._build_ui()
        self.load_all_config()

    def _setup_window(self):
        self.page.title = f"{APP_NAME} v{APP_VERSION}"
        self.page.window.width = WINDOW_WIDTH
        self.page.window.height = WINDOW_HEIGHT
        self.page.window.min_width = 1050
        self.page.window.min_height = 650
        self.page.window.center()

        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.theme = ft.Theme(
            font_family=get_system_font_family(),
            color_scheme_seed=ft.Colors.BLUE_ACCENT,
            use_material3=True,
        )

    def _load_app_settings(self):
        settings = load_app_settings()
        self.brand = settings.get("brand", "OpenCode")
        self.auto_save_enabled = settings.get("auto_save", False)
        self.sync_enabled = settings.get("sync_enabled", False)
        self._config_manager = ConfigManager(self.brand)

    def _save_app_settings(self):
        settings = {
            "brand": self.brand,
            "auto_save": self.auto_save_enabled,
            "sync_enabled": self.sync_enabled,
        }
        save_app_settings(settings)

    def _build_ui(self):
        # 顶栏 Header
        self.brand_dropdown = ft.Dropdown(
            value=self.brand,
            options=[
                ft.dropdown.Option("OpenCode", "OpenCode (TUI)"),
                ft.dropdown.Option("KiloCode", "KiloCode (VSCode)"),
            ],
            dense=True,
            width=200,
            on_change=self._on_brand_change,
        )

        self.switch_auto_save = ft.Switch(
            label="自动保存",
            value=self.auto_save_enabled,
            on_change=self._on_auto_save_toggle,
        )
        self.switch_sync = ft.Switch(
            label="同步修改",
            value=self.sync_enabled,
            tooltip="开启后，修改将自动精准合并到另一个品牌的配置中",
            on_change=self._on_sync_toggle,
        )

        self.btn_save = ft.FilledButton("保存配置", icon=ft.Icons.SAVE, on_click=lambda e: self.save_all_config(silent=False))
        self.btn_sync = ft.OutlinedButton("同步到目标品牌", icon=ft.Icons.SYNC, on_click=lambda e: self._manual_sync_dialog())
        self.btn_open_file = ft.OutlinedButton("打开配置文件", icon=ft.Icons.FILE_OPEN, on_click=lambda e: self._open_config_file())

        self.header = ft.Container(
            padding=ft.padding.symmetric(horizontal=16, vertical=8),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=8,
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.DASHBOARD_CUSTOMIZE, color=ft.Colors.PRIMARY, size=24),
                            self.brand_dropdown,
                        ],
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            self.switch_auto_save,
                            self.switch_sync,
                            self.btn_save,
                            self.btn_sync,
                            self.btn_open_file,
                        ],
                        spacing=12,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        )

        # 核心三大视图
        self.provider_view = ProviderView(self.page, on_change=self._on_content_modified)
        self.mcp_view = McpCompactionView(self.page, on_change=self._on_content_modified)
        self.instructions_view = InstructionsView(self.page, brand=self.brand)

        # 选项卡 Tabs
        self.tabs = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Provider 与模型管理", icon=ft.Icons.STORAGE, content=self.provider_view),
                ft.Tab(text="MCP 与上下文压缩", icon=ft.Icons.EXTENSION, content=self.mcp_view),
                ft.Tab(text="全局提示词 (AGENTS.md)", icon=ft.Icons.DESCRIPTION, content=self.instructions_view),
            ],
            expand=True,
        )

        self.page.add(
            ft.Column(
                [
                    self.header,
                    self.tabs,
                ],
                expand=True,
                spacing=8,
            )
        )

    # ---------------- 配置生命周期 ----------------

    def load_all_config(self, silent: bool = True):
        self._config_manager = ConfigManager(self.brand)
        raw_cfg = self._config_manager.load_config()

        # 加载 providers
        providers = self._config_manager.load_providers_with_keys()
        self.provider_view.load_providers(providers)

        # 加载 MCP 与 compaction
        self.mcp_view.load_mcp(raw_cfg.get("mcp", {}))
        self.mcp_view.load_compaction(raw_cfg.get("compaction", {}))

        # 加载 instructions
        self.instructions_view.switch_brand(self.brand)

        self._last_config_hash = self._config_manager.get_config_hash()

        if not silent:
            self.show_status("配置已成功重新加载", ft.Colors.GREEN_400)

    def save_all_config(self, silent: bool = False):
        try:
            providers = self.provider_view.get_providers()
            mcp = self.mcp_view.get_mcp()
            compaction = self.mcp_view.get_compaction()

            self._config_manager.save_config(
                providers=providers,
                mcp=mcp,
                compaction=compaction,
                sync_to_other=self.sync_enabled,
            )
            self._last_config_hash = self._config_manager.get_config_hash()

            if not silent:
                hint = (
                    "按 Ctrl+Shift+P 执行 Reload Window 生效"
                    if self.brand == "KiloCode"
                    else "在终端中输入 /reload 或重启生效"
                )
                self.show_status(f"配置已保存至 {self.brand} | {hint}", ft.Colors.GREEN_400)
        except Exception as e:
            self.show_status(f"保存失败: {e}", ft.Colors.RED_400)

    def _on_content_modified(self):
        if self.auto_save_enabled:
            self._schedule_auto_save()

    def _schedule_auto_save(self):
        if self._auto_save_timer:
            self._auto_save_timer.cancel()
        self._auto_save_timer = threading.Timer(1.0, lambda: self.save_all_config(silent=True))
        self._auto_save_timer.daemon = True
        self._auto_save_timer.start()

    def _on_brand_change(self, e):
        new_brand = self.brand_dropdown.value
        if new_brand != self.brand:
            self.brand = new_brand
            self._save_app_settings()
            self.load_all_config(silent=True)
            self.show_status(f"已切换当前品牌为: {self.brand}", ft.Colors.BLUE_400)

    def _on_auto_save_toggle(self, e):
        self.auto_save_enabled = self.switch_auto_save.value
        self._save_app_settings()

    def _on_sync_toggle(self, e):
        self.sync_enabled = self.switch_sync.value
        self._save_app_settings()

    def _open_config_file(self):
        cfg_path = self._config_manager.config_path
        if not cfg_path.exists():
            self.save_all_config(silent=True)
        ConfigManager.open_path_in_system(cfg_path)

    def _manual_sync_dialog(self):
        target_brand = "KiloCode" if self.brand == "OpenCode" else "OpenCode"
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"确认同步到 {target_brand}？", weight=ft.FontWeight.BOLD),
            content=ft.Text(
                f"将当前 {self.brand} 的 Provider、模型配置、MCP 服务及全局提示词精准合并至 {target_brand}。\n"
                f"目标品牌中专有及未支持编辑的字段将被安全保留。",
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda ev: self.page.close(dlg)),
                ft.FilledButton("确认同步", on_click=lambda ev: self._do_manual_sync(dlg)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _do_manual_sync(self, dlg: ft.AlertDialog):
        self.page.close(dlg)
        try:
            self.save_all_config(silent=True)
            curr_cfg = self._config_manager.load_config()
            curr_auth = load_auth_json(self.brand)
            self._config_manager.sync_to_other_brand(curr_cfg, curr_auth)
            target = "KiloCode" if self.brand == "OpenCode" else "OpenCode"
            self.show_status(f"已成功将配置精准合并同步至 {target}", ft.Colors.GREEN_400)
        except Exception as err:
            self.show_status(f"同步失败: {err}", ft.Colors.RED_400)

    def show_status(self, text: str, color: str = ft.Colors.GREEN_400):
        if self.page:
            sb = ft.SnackBar(content=ft.Text(text), bgcolor=color, duration=4000)
            self.page.open(sb)



# ████████████████████████████████████████████████████████████████████████████████
# ██  SECTION 9: 应用主入口 (main)
# ████████████████████████████████████████████████████████████████████████████████

def main(page: ft.Page):
    """Flet 应用启动入口。"""
    EasyOpenKiloApp(page)


if __name__ == "__main__":
    ft.app(target=main)
