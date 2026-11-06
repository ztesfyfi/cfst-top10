import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    data_dir: Path
    engine_dir: Path
    admin_token: str

    @classmethod
    def from_env(cls):
        token = os.getenv("CFST_ADMIN_TOKEN", "").strip()
        if len(token) < 32 or token.startswith("replace-this"):
            raise RuntimeError("CFST_ADMIN_TOKEN must be a unique secret of at least 32 characters")
        return cls(
            Path(os.getenv("CFST_DATA_DIR", "/data")).resolve(),
            Path(os.getenv("CFST_ENGINE_DIR", "/opt/cfst")).resolve(),
            token,
        )
