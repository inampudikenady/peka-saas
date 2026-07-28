"""Safely validate the configured real embedding provider."""

import json

from app.services.knowledge_runtime_health import embedding_health


def main() -> int:
    result = embedding_health(verify=True)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
