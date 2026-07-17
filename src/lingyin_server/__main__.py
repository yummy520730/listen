from __future__ import annotations

import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "lingyin_server.app:app",
        host="0.0.0.0",
        port=settings.port,
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()

