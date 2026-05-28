"""
统一配置管理模块
所有配置读写集中在此，避免 gui.py 中散落的 try/except pass。
"""
import json
import logging
from pathlib import Path

_log = logging.getLogger("config")

DEFAULT_CONFIG = {
    "save_dir": "E:/",
    "theme": "light",
    "history": [],
    "max_workers": 6,
    "hls_workers": 24,
    "timeout": 30,
    "proxy": "",  # HTTP/SOCKS5 代理，如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080
}

# Windows: %APPDATA%\WebScraper\config.json
_appdata = Path.home() / "AppData" / "Roaming"
CONFIG_DIR = _appdata / "WebScraper"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    """读取配置，失败返回默认值（带日志，不再静默吞错）"""
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            # 合并默认值，防止旧配置缺键
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
    except Exception as e:
        _log.warning(f"[config] 读取失败，使用默认配置: {e}")
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    """写入配置，失败记录日志"""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        _log.warning(f"[config] 写入失败: {e}")


def _coerce_int(value, default: int, min_value: int, max_value: int) -> int:
    """将配置值转为指定范围内的整数。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(parsed, max_value))


def get_config_int(
    cfg: dict,
    key: str,
    default: int,
    min_value: int = 1,
    max_value: int = 32,
) -> int:
    """读取兼容新旧配置格式的整数值。

    优先读取 cfg[key]；若不存在则读取旧格式 cfg["settings"][key]。
    """
    if key in cfg:
        return _coerce_int(cfg.get(key), default, min_value, max_value)
    settings = cfg.get("settings", {})
    if isinstance(settings, dict) and key in settings:
        return _coerce_int(settings.get(key), default, min_value, max_value)
    return default


def load_history() -> list:
    """返回最近 50 条 URL 历史"""
    return load_config().get("history", [])[:50]


def save_history(urls: list) -> None:
    """持久化 URL 历史（最多保留 50 条）"""
    cfg = load_config()
    cfg["history"] = urls[:50]
    save_config(cfg)


def get_proxy() -> dict[str, str]:
    """读取代理配置，返回 requests 可用的 proxies 字典。

    Returns:
        如 {"http": "http://...", "https": "http://..."}，或空字典表示无代理。
    """
    proxy_url = load_config().get("proxy", "").strip()
    if not proxy_url:
        return {}
    return {"http": proxy_url, "https": proxy_url}
