#!/usr/bin/env bash
# .claude/hooks/pre-commit.sh
# Enabled via: git config core.hooksPath .claude/hooks

# 1. Block credential files (.env.example is allowed)
if git diff --cached --name-only --diff-filter=AM | grep -qE '(^|/)\.env$|\.(key|pem)$|secrets\.json$'; then
  echo "BLOCKED: Attempting to commit credentials or sensitive files."
  exit 1
fi

# 2. Block hardcoded Ring/AWS secrets in added source lines.
#    Reading the variable from the environment is fine; assigning a literal is not.
added=$(git diff --cached -U0 --diff-filter=AM -- backend web | grep -E '^\+[^+]')
if echo "$added" | grep -qE "RING_ACCESS_TOKEN[\"']?\s*[:=]\s*[\"'][^\"']+[\"']"; then
  echo "BLOCKED: Hardcoded Ring token detected in staged diff."
  exit 1
fi
if echo "$added" | grep -qE 'AKIA[0-9A-Z]{16}'; then
  echo "BLOCKED: AWS access key ID detected in staged diff."
  exit 1
fi

exit 0
