from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    data_dir: Path
    vectorstore_path: Path
    log_path: Path
    llm_provider: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        data_dir = Path(os.getenv("DATA_DIR", "data"))
        return cls(
            app_name=os.getenv("APP_NAME", "EduRAG-Agent"),
            app_env=os.getenv("APP_ENV", "local"),
            data_dir=data_dir,
            vectorstore_path=Path(
                os.getenv("VECTORSTORE_PATH", str(data_dir / "processed" / "vectorstore.json"))
            ),
            log_path=Path(os.getenv("LOG_PATH", "logs/interactions.jsonl")),
            llm_provider=os.getenv("LLM_PROVIDER", "local").lower(),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
        )


settings = Settings.from_env()

