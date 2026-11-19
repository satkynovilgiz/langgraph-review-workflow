#!/bin/sh
# Fails if any tracked or staged file contains something that looks like
# a real Google API key (they all start with "AIza").
# Installed as .git/hooks/pre-commit so it runs before every commit.
if git grep --cached -n "AIza" -- . ':!scripts/check_no_keys.sh'; then
  echo "ERROR: a Google API key (AIza...) is in a staged file. Commit blocked."
  exit 1
fi
echo "Key check passed: no AIza... keys in tracked files."
