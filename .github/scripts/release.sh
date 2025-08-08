#!/bin/bash

set -e  # trigger failure on error - do not remove!
set -x  # display command on output

## debug
# TARGET_VERSION="1.2.x"

if [ -z "${TARGET_VERSION}" ]; then
    >&2 echo "No TARGET_VERSION specified"
    exit 1
fi
CHGLOG_FILE="${CHGLOG_FILE:-CHANGELOG.md}"

# Update package version
uvx --from=toml-cli toml set --toml-path=pyproject.toml project.version "${TARGET_VERSION}"
uv lock --upgrade-package docling-serve

# Extract all docling packages and versions from uv.lock
DOCVERSIONS=$(uvx --with toml python3 - <<'PY'
import toml
data = toml.load("uv.lock")
for pkg in data.get("package", []):
    if pkg["name"].startswith("docling"):
        print(f"{pkg['name']} {pkg['version']}")
PY
)

# Format docling versions list without trailing newline
DOCLING_VERSIONS="### Docling libraries included in this release:"
while IFS= read -r line; do
  DOCLING_VERSIONS+="
- $line"
done <<< "$DOCVERSIONS"

# Collect release notes
REL_NOTES=$(mktemp)
uv run --no-sync semantic-release changelog --unreleased >> "${REL_NOTES}"

# Strip trailing blank lines from release notes and append docling versions
{
  sed -e :a -e '/^\n*$/{$d;N;};/\n$/ba' "${REL_NOTES}"
  printf "\n"
  printf "%s" "${DOCLING_VERSIONS}"
  printf "\n"
} > "${REL_NOTES}.tmp" && mv "${REL_NOTES}.tmp" "${REL_NOTES}"

# Update changelog
TMP_CHGLOG=$(mktemp)
TARGET_TAG_NAME="v${TARGET_VERSION}"
RELEASE_URL="$(gh repo view --json url -q ".url")/releases/tag/${TARGET_TAG_NAME}"
## debug
#RELEASE_URL="myrepo/releases/tag/${TARGET_TAG_NAME}"

# Strip leading blank lines from existing changelog to avoid multiple blank lines when appending
EXISTING_CL=$(sed -e :a -e '/^\n*$/{$d;N;};/\n$/ba' "${CHGLOG_FILE}")

{
  printf "## [${TARGET_TAG_NAME}](${RELEASE_URL}) - $(date -Idate)\n\n"
  cat "${REL_NOTES}"
  printf "\n"
  printf "%s\n" "${EXISTING_CL}"
} >> "${TMP_CHGLOG}"

mv "${TMP_CHGLOG}" "${CHGLOG_FILE}"

# Push changes
git config --global user.name 'github-actions[bot]'
git config --global user.email 'github-actions[bot]@users.noreply.github.com'
git add pyproject.toml uv.lock "${CHGLOG_FILE}"
COMMIT_MSG="chore: bump version to ${TARGET_VERSION} [skip ci]"
git commit -m "${COMMIT_MSG}"
git push origin main

# Create GitHub release (incl. Git tag)
gh release create "${TARGET_TAG_NAME}" -F "${REL_NOTES}"
