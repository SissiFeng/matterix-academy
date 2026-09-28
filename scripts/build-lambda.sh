#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file build/requirements.txt >/dev/null
# Build native wheels for AWS Lambda, never package macOS pydantic binaries.
python3 - <<'PY'
import shutil
from pathlib import Path
target = Path('build/lambda')
if target.exists():
    shutil.rmtree(target)
target.mkdir()
PY
uv pip install --python-version 3.12 --python-platform x86_64-manylinux2014 --only-binary :all: --target build/lambda -r build/requirements.txt
python3 - <<'PY'
from pathlib import Path
import shutil, zipfile
shutil.copytree('app/backend/academy', 'build/lambda/academy', ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
with zipfile.ZipFile('build/lambda.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(Path('build/lambda').rglob('*')):
        if file.is_file() and '__pycache__' not in file.parts:
            archive.write(file,file.relative_to('build/lambda'))
print('Built build/lambda.zip for Python 3.12 / Linux x86_64')
PY
