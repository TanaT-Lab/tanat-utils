#!/bin/bash
# Extract release notes from CHANGELOG.md for a given version
#
# Usage: ./scripts/extract_changelog.sh [VERSION]
#   VERSION: version number with 'v' prefix (e.g., v0.0.1)
#            If not provided, uses GITHUB_REF_NAME environment variable
#
# Example:
#   ./scripts/extract_changelog.sh v0.0.1
#   GITHUB_REF_NAME=v0.0.1 ./scripts/extract_changelog.sh

set -e

# Get version from argument or environment
VERSION="${1:-$GITHUB_REF_NAME}"

if [ -z "$VERSION" ]; then
    echo "Error: No version provided. Pass as argument or set GITHUB_REF_NAME." >&2
    exit 1
fi

CHANGELOG_FILE="${CHANGELOG_FILE:-CHANGELOG.md}"

if [ ! -f "$CHANGELOG_FILE" ]; then
    echo "Error: $CHANGELOG_FILE not found." >&2
    exit 1
fi

# Extract section between this version header and the next version header
# Matches both "## [0.0.1]" and "## 0.0.1" formats
NOTES=$(awk "
    /^## \[?${VERSION}\]?/ { found=1; next }
    /^## \[?[0-9]+\.[0-9]+/ && found { exit }
    found { print }
" "$CHANGELOG_FILE")

# Trim leading/trailing whitespace
NOTES=$(echo "$NOTES" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

if [ -z "$NOTES" ]; then
    echo "Release $VERSION"
else
    echo "$NOTES"
fi
