#!/bin/bash
# Credentials stay in the user's Keychain, never in source or command arguments.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${MACOS_SIGN_IDENTITY:?Set your Developer ID Application identity first}"
: "${NOTARY_PROFILE:?Set the name of an existing notarytool Keychain profile}"
if [[ "$MACOS_SIGN_IDENTITY" != "Developer ID Application:"* ]]; then
    echo "A Developer ID Application certificate is required." >&2
    exit 1
fi
bash scripts/build_macos.sh
codesign --verify --deep --strict "dist/Cantus PDF.app"
notary_result=$(mktemp)
trap 'rm -f "$notary_result"' EXIT
xcrun notarytool submit dist/CantusPDF-macOS-arm64.zip \
    --keychain-profile "$NOTARY_PROFILE" --wait --timeout 20m \
    --output-format json > "$notary_result"
.venv-build/bin/python - "$notary_result" <<'PY'
import json, sys
result = json.load(open(sys.argv[1]))
if result.get("status") != "Accepted":
    raise SystemExit(f"Notarization was not accepted: {result.get('status')}; submission {result.get('id')}")
print(f"Apple accepted notarization: {result['id']}")
PY
xcrun stapler staple "dist/Cantus PDF.app"
xcrun stapler validate "dist/Cantus PDF.app"
spctl --assess --type execute --verbose=2 "dist/Cantus PDF.app"
ditto -c -k --sequesterRsrc --keepParent "dist/Cantus PDF.app" dist/CantusPDF-macOS-arm64.zip
echo "Signed, notarized, stapled archive: dist/CantusPDF-macOS-arm64.zip"
