from __future__ import annotations

import uvicorn

from env.environment import app


def main() -> None:
    uvicorn.run("env.environment:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
