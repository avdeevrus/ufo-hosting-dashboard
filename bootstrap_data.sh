#!/usr/bin/env bash
# Одноразово заливает локальные data/orders/*.csv и data/ads/*.xlsx
# в приватный HF Dataset avdeevrus/ufo-hosting-data.
# После этого дашборд при каждом старте будет видеть эти файлы.
#
# Использование:
#   HF_TOKEN=hf_xxxxxxxxxxxx ./bootstrap_data.sh

set -euo pipefail

if [ -z "${HF_TOKEN:-}" ]; then
  echo "❌ HF_TOKEN не задан"
  echo "   Используйте:  HF_TOKEN=hf_xxx ./bootstrap_data.sh"
  exit 1
fi

cd "$(dirname "$0")"
python3 - <<'PY'
import os
from pathlib import Path
from huggingface_hub import HfApi

REPO = "avdeevrus/ufo-hosting-data"
api = HfApi(token=os.environ["HF_TOKEN"])

api.create_repo(repo_id=REPO, repo_type="dataset", private=True, exist_ok=True)
print(f"✓ Dataset {REPO} готов (private)")

data_dir = Path("data")
uploaded = 0
for sub in ("orders", "ads"):
    folder = data_dir / sub
    if not folder.exists():
        continue
    for f in folder.iterdir():
        if f.name.startswith(".") or not f.is_file():
            continue
        api.upload_file(
            path_or_fileobj=str(f),
            path_in_repo=f"{sub}/{f.name}",
            repo_id=REPO,
            repo_type="dataset",
        )
        print(f"↑ {sub}/{f.name}")
        uploaded += 1

print(f"\n✓ Загружено файлов: {uploaded}")
print(f"  Dataset URL: https://huggingface.co/datasets/{REPO}")
PY
