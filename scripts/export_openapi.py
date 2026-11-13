"""Write the public API contract to docs/openapi.json (run via `make openapi` after changing api.py)."""

import json
import os
import sys

sys.path.append(os.getcwd())

from api import app  # noqa: E402

if __name__ == "__main__":
    with open("docs/openapi.json", "w") as f:
        json.dump(app.openapi(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("Wrote docs/openapi.json")
