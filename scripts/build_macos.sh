#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    echo "This build recipe requires an Apple Silicon Mac." >&2
    exit 1
fi

BUILD_PYTHON="${BUILD_PYTHON:-python3}"
"$BUILD_PYTHON" -m venv .venv-build
.venv-build/bin/python -m pip install -r requirements-build-macos.txt
mkdir -p build
.venv-build/bin/python -m pytest -q --junitxml=build/test-results.xml
.venv-build/bin/python scripts/build_icon.py
.venv-build/bin/python -m PyInstaller --clean --noconfirm CantusPDF.spec
codesign --verify --deep --strict "dist/Cantus PDF.app"
"dist/Cantus PDF.app/Contents/MacOS/CantusPDF" --self-test build/release-check.json
ditto -c -k --sequesterRsrc --keepParent "dist/Cantus PDF.app" dist/CantusPDF-macOS-arm64.zip
.venv-build/bin/python scripts/record_release.py
echo "Built: dist/Cantus PDF.app"
echo "Archive: dist/CantusPDF-macOS-arm64.zip"
