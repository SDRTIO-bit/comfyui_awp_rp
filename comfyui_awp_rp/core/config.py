"""
Global configuration for AWP RP Plugin.

Manages providers, default models, and plugin settings.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional
from .types import ProviderConfig, LocalizedText


def _env_provider_configs() -> tuple[dict[str, ProviderConfig], Optional[str]]:
    """Build runtime provider configs from environment variables."""
    providers: dict[str, ProviderConfig] = {}
    requested_provider = os.environ.get("RP_PROVIDER", "").strip()

    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key or requested_provider == "deepseek":
        providers["deepseek"] = ProviderConfig(
            provider_id="deepseek",
            api_key=deepseek_key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
            default_model=(
                os.environ.get("RP_MODEL")
                or os.environ.get("DEEPSEEK_MODEL")
                or "deepseek-chat"
            ),
            models=[],
        )

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key or requested_provider == "openai":
        providers["openai"] = ProviderConfig(
            provider_id="openai",
            api_key=openai_key,
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            default_model=os.environ.get("RP_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4.1-mini",
            models=[],
        )

    # GLM (智谱)
    glm_key = os.environ.get("GLM_API_KEY", "").strip()
    if glm_key or requested_provider == "glm":
        providers["glm"] = ProviderConfig(
            provider_id="glm",
            api_key=glm_key,
            base_url=os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/"),
            default_model=os.environ.get("RP_MODEL") or os.environ.get("GLM_MODEL") or "glm-4-flash",
            models=[],
        )

    # 通配供应商：任何 RP_CUSTOM_PROVIDER_<NAME>_API_KEY 环境变量自动注册
    for env_key, env_val in os.environ.items():
        prefix = "RP_CUSTOM_PROVIDER_"
        suffix = "_API_KEY"
        if env_key.startswith(prefix) and env_key.endswith(suffix) and env_val.strip():
            pid = env_key[len(prefix):-len(suffix)].lower()
            providers[pid] = ProviderConfig(
                provider_id=pid,
                api_key=env_val.strip(),
                base_url=os.environ.get(f"RP_CUSTOM_PROVIDER_{pid.upper()}_BASE_URL", "").rstrip("/"),
                default_model=os.environ.get(f"RP_CUSTOM_PROVIDER_{pid.upper()}_MODEL", ""),
                models=[],
            )

    default_provider = requested_provider if requested_provider in providers else None
    if not default_provider and providers:
        default_provider = next(iter(providers))
    return providers, default_provider

@dataclass
class Config:
    """Global configuration for the plugin."""
    
    # Data directory for persistent storage
    data_dir: str = ""
    
    # Provider configurations
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    
    # Default provider ID
    default_provider_id: str = "deepseek"
    
    # Plugin settings
    debug_mode: bool = False
    log_level: str = "INFO"
    
    def __post_init__(self):
        """Initialize data directory if not set."""
        if not self.data_dir:
            # Default to plugin's data directory
            plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.data_dir = os.path.join(plugin_dir, "data")
        
        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, "profiles"), exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, "skills"), exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, "presets"), exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, "cards"), exist_ok=True)
    
    def get_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        """Get a provider configuration by ID."""
        return self.providers.get(provider_id)
    
    def get_default_provider(self) -> ProviderConfig:
        """Get the default provider configuration."""
        return self.providers[self.default_provider_id]
    
    def add_provider(self, config: ProviderConfig) -> None:
        """Add or update a provider configuration."""
        self.providers[config.provider_id] = config
    
    def save(self) -> None:
        """Save configuration to file."""
        config_path = os.path.join(self.data_dir, "config.json")
        data = {
            "data_dir": self.data_dir,
            "default_provider_id": self.default_provider_id,
            "debug_mode": self.debug_mode,
            "log_level": self.log_level,
            "providers": {
                pid: {
                    "provider_id": p.provider_id,
                    "api_key": p.api_key,
                    "base_url": p.base_url,
                    "default_model": p.default_model,
                    "models": p.models,
                }
                for pid, p in self.providers.items()
            }
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    @classmethod
    def load(cls, data_dir: Optional[str] = None) -> "Config":
        """Load configuration from file."""
        if data_dir is None:
            plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(plugin_dir, "data")
        
        config_path = os.path.join(data_dir, "config.json")
        
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            providers = {}
            for pid, pdata in data.get("providers", {}).items():
                providers[pid] = ProviderConfig(
                    provider_id=pdata["provider_id"],
                    api_key=pdata["api_key"],
                    base_url=pdata["base_url"],
                    default_model=pdata["default_model"],
                    models=pdata.get("models", []),
                )

            env_providers, env_default_provider = _env_provider_configs()
            providers.update(env_providers)
            
            return cls(
                data_dir=data_dir,
                providers=providers,
                default_provider_id=env_default_provider or data.get("default_provider_id", "deepseek"),
                debug_mode=data.get("debug_mode", False),
                log_level=data.get("log_level", "INFO"),
            )
        
        # Return default config if file doesn't exist
        env_providers, env_default_provider = _env_provider_configs()
        return cls(
            data_dir=data_dir,
            providers=env_providers,
            default_provider_id=env_default_provider or "deepseek",
        )


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def set_config(config: Config) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config


def initialize_config(
    providers: Optional[dict[str, dict]] = None,
    default_provider: str = "deepseek",
    data_dir: Optional[str] = None,
) -> Config:
    """Initialize the global configuration."""
    global _config
    
    provider_configs = {}
    if providers:
        for pid, pdata in providers.items():
            provider_configs[pid] = ProviderConfig(
                provider_id=pid,
                api_key=pdata.get("api_key", ""),
                base_url=pdata.get("base_url", ""),
                default_model=pdata.get("default_model", ""),
                models=pdata.get("models", []),
            )
    
    _config = Config(
        data_dir=data_dir or "",
        providers=provider_configs,
        default_provider_id=default_provider,
    )
    _config.save()
    return _config
