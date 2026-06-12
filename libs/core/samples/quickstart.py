"""auropro-core quickstart — config loading + structured logging in ~30 lines.

Run: uv run python libs/core/samples/quickstart.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from auropro_core.logging import configure_logging, get_logger, log_context
from auropro_core.yamlconfig import load_yaml_model


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = "127.0.0.1"
    port: int = 8080


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: str = "demo"
    server: ServerConfig = ServerConfig()


def main() -> None:
    configure_logging("console")
    log = get_logger("quickstart")

    with tempfile.TemporaryDirectory() as td:
        cfg_file = Path(td) / "app.yaml"
        cfg_file.write_text("app_name: accelerated-app\nserver:\n  port: 9000\n", encoding="utf-8")

        os.environ["DEMO__SERVER__HOST"] = "0.0.0.0"  # env beats file
        cfg = load_yaml_model(cfg_file, AppConfig, env_prefix="DEMO__")

    with log_context(component="quickstart", app=cfg.app_name):
        log.info("config loaded", host=cfg.server.host, port=cfg.server.port)

    assert cfg.server.host == "0.0.0.0" and cfg.server.port == 9000
    print(f"OK: {cfg.app_name} -> {cfg.server.host}:{cfg.server.port}")


if __name__ == "__main__":
    main()
