#!/bin/bash
# Auto-Auto installer
# Installs the /auto-auto skill and sets up the MCP server

set -e

AUTO_AUTO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$HOME/.claude/skills/auto-auto"

echo "🔧 Auto-Auto Installer"
echo "  Project dir: $AUTO_AUTO_DIR"
echo ""

# 1. Install Python dependencies
echo "📦 Installing Python dependencies..."
cd "$AUTO_AUTO_DIR"
uv sync 2>&1 | tail -1
echo "   Done."

# 2. Install the /auto-auto skill (symlink)
echo "🔗 Installing /auto-auto skill..."
mkdir -p "$HOME/.claude/skills"
if [ -L "$SKILL_DIR" ]; then
    rm "$SKILL_DIR"
fi
if [ -d "$SKILL_DIR" ]; then
    echo "   Warning: $SKILL_DIR already exists as a directory. Backing up."
    mv "$SKILL_DIR" "$SKILL_DIR.bak.$(date +%s)"
fi
ln -s "$AUTO_AUTO_DIR/skill/auto-auto" "$SKILL_DIR"
echo "   Installed at: $SKILL_DIR -> $AUTO_AUTO_DIR/skill/auto-auto"

# 3. Verify
echo ""
echo "✅ Auto-Auto installed!"
echo ""
echo "Usage:"
echo "  In any Claude Code session, type:"
echo "    /auto-auto Build a REST API for user management"
echo ""
echo "  Auto-Auto will:"
echo "    1. Research the task"
echo "    2. Ask you clarification questions"
echo "    3. Design a workflow"
echo "    4. Scaffold a ready-to-go workspace"
echo ""
echo "  Then just cd into the workspace and run: claude"
