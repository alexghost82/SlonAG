#!/usr/bin/env bash
set -euo pipefail

WORKTREES="/home/slon/Documents/GitHub/SlonAG-fix-worktrees"
FIX_AGENTS_DIR="/home/slon/Documents/GitHub/SlonAG/fix_agents"
BASE_SHA="da1336723933f743f01027022ea7bda5ec35b0ca"

COUNT=0

for i in $(seq -w 3 26); do
    WORKTREE="$WORKTREES/$i"
    [ ! -d "$WORKTREE" ] && continue
    [ ! -f "$WORKTREE/.git" ] && [ ! -d "$WORKTREE/.git" ] && continue

    TASK_FILE="$FIX_AGENTS_DIR/${i}_*.md"
    TASK_FILE=$(ls $TASK_FILE 2>/dev/null | head -1)
    [ -z "$TASK_FILE" ] && continue

    TASK_NAME=$(basename "$TASK_FILE" .md)
    BRANCH="fix-agent/$i-$TASK_NAME"

    echo "[$i] Starting: $TASK_NAME in $WORKTREE"
    (
        cd "$WORKTREE"
        git checkout "$BASE_SHA" 2>/dev/null || true
        git checkout -b "$BRANCH" 2>/dev/null || git checkout "$BRANCH" 2>/dev/null || true

        # Read task file and create prompt
        TASK_CONTENT=$(cat "$TASK_FILE")

        # Run codex exec
        codex exec -m gpt-5.6-sol -C "$WORKTREE" << PROMPT
# ORCHESTRATOR TASK #$i

This task is part of a parallel fix wave.

## Task file
$TASK_FILE

## Repository
/home/slon/Documents/GitHub/SlonAG

## Worktree
$WORKTREE

## Branch
$BRANCH

## Base SHA
$BASE_SHA

---
$TASK_CONTENT
---

## IMPORTANT RULES
- Work ONLY in this worktree ($WORKTREE)
- Do NOT push, merge, rebase, force push, modify remotes, reset --hard, or git clean
- Create ONE commit with your changes
- Report: SHA, changed files, test results, known issues, integration notes
PROMPT
    ) &

    COUNT=$((COUNT + 1))
    sleep 0.5
done

echo ""
echo "Started $COUNT agents in background."
wait

echo ""
echo "All agents finished. Checking results..."

for i in $(seq -w 3 26); do
    WORKTREE="$WORKTREES/$i"
    [ ! -d "$WORKTREE" ] && continue

    TASK_FILE=$(ls "$FIX_AGENTS_DIR"/${i}_*.md 2>/dev/null | head -1)
    [ -z "$TASK_FILE" ] && continue

    cd "$WORKTREE"
    TASK_NAME=$(basename "$TASK_FILE" .md)
    git checkout "fix-agent/$i-$TASK_NAME" 2>/dev/null || true
    COMMIT_COUNT=$(git log --oneline 2>/dev/null | wc -l)

    if [ "$COMMIT_COUNT" -gt 1 ]; then
        echo "[$i] ✅ COMMIT ($COMMIT_COUNT commits)"
        git log --oneline -1
    else
        echo "[$i] ❌ NO COMMIT"
    fi
done

echo "Done."
