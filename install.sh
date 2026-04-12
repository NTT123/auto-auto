#!/bin/bash
# Auto-Auto installer
#
# Installs Python dependencies for the auto-auto workflow engine and verifies
# that the PROJECT-level /auto-auto skill is in place.
#
# The /auto-auto skill lives at ./.claude/skills/auto-auto/SKILL.md inside
# this repository. Claude Code auto-loads project-level skills when you run
# `claude` from the repo root, so there is no user-level install step.
#
# Earlier versions of this installer created a symlink at
# ~/.claude/skills/auto-auto pointing at skill/auto-auto/ inside this repo.
# That layout is gone. If a stale symlink is left on your machine from an
# older install, we clean it up below.

set -e

AUTO_AUTO_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_SKILL="$AUTO_AUTO_DIR/.claude/skills/auto-auto/SKILL.md"
LEGACY_USER_SKILL="$HOME/.claude/skills/auto-auto"

echo "🔧 Auto-Auto Installer"
echo "  Project dir: $AUTO_AUTO_DIR"
echo ""

# 1. Install Python dependencies
echo "📦 Installing Python dependencies..."
cd "$AUTO_AUTO_DIR"
uv sync 2>&1 | tail -1
echo "   Done."

# 2. Clean up any stale user-level install from previous versions
echo ""
echo "🧹 Checking for legacy user-level install..."
if [ -L "$LEGACY_USER_SKILL" ]; then
    target="$(readlink "$LEGACY_USER_SKILL" 2>/dev/null || echo unknown)"
    rm "$LEGACY_USER_SKILL"
    echo "   Removed stale symlink: $LEGACY_USER_SKILL -> $target"
elif [ -d "$LEGACY_USER_SKILL" ]; then
    echo "   ⚠️  Found a directory (not a symlink) at $LEGACY_USER_SKILL"
    echo "      This looks like a hand-placed user-level copy of the skill."
    echo "      Auto-Auto is now a project-level skill; you can safely delete it."
    echo "      (Not deleting it automatically, since it's not something we created.)"
else
    echo "   None found."
fi

# 3. Verify the project-level skill is present
echo ""
echo "🔎 Verifying project-level /auto-auto skill..."
if [ -f "$PROJECT_SKILL" ]; then
    echo "   Found: $PROJECT_SKILL"
else
    echo "   ❌ Missing: $PROJECT_SKILL"
    echo "   The auto-auto skill is supposed to live at .claude/skills/auto-auto/SKILL.md"
    echo "   inside this repository. Re-check your working tree."
    exit 1
fi

# 4. Done
echo ""
echo "✅ Auto-Auto installed!"
echo ""
echo "Usage:"
echo "  This is a PROJECT-level skill. To use it:"
echo "    cd $AUTO_AUTO_DIR"
echo "    claude"
echo ""
echo "  Then in the Claude Code session, type:"
echo "    /auto-auto Build a REST API for user management"
echo ""
echo "  Auto-Auto will:"
echo "    1. Research the task"
echo "    2. Ask you clarification questions"
echo "    3. Design a workflow"
echo "    4. Design a VERIFICATION plan (with 2x the thinking of implementation)"
echo "    5. Scaffold a ready-to-go workspace"
echo ""
echo "  Then just cd into the scaffolded workspace and run: claude"
