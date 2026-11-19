#!/bin/sh
# Blocks a commit if a staged file seems to contain a real Google API key.
# Installed as .git/hooks/pre-commit so it runs before every commit.
#  1. Classic Google keys start with "AIza".
#  2. Newer keys can look different, so we also block ANY
#     "GOOGLE_API_KEY=<value>" whose value is not the placeholder.
if git grep --cached -n "AIza" -- . ':!scripts/check_no_keys.sh'; then
  echo "ERROR: a Google API key (AIza...) is in a staged file. Commit blocked."
  exit 1
fi
if git grep --cached -nE "GOOGLE_API_KEY=[^ ]" -- . ':!scripts/check_no_keys.sh' \
    | grep -v "GOOGLE_API_KEY=your-key-here"; then
  echo "ERROR: GOOGLE_API_KEY has a real-looking value in a staged file. Commit blocked."
  exit 1
fi
echo "Key check passed: no API keys in tracked files."
