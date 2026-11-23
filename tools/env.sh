# Source before every collect.py run:  . /home/user/Project/tools/env.sh
# collect.py copies os.environ into the agent process, so these reach OpenCode.

export PATH="$HOME/.opencode/bin:$PATH"

# Pinned harness version for all runs (also "autoupdate": false in ~/.config/opencode/opencode.json).
export OPENCODE_DISABLE_AUTOUPDATE=1

# Without this, OpenCode 1.19.6 also advertises the 13 Claude Code skills found under
# ~/.claude/skills (including its hidden .trash/), so the agent's skill list would not
# match baseline.json. Do NOT use OPENCODE_DISABLE_EXTERNAL_SKILLS: it also drops
# the workspace's .agents/skills.
export OPENCODE_DISABLE_CLAUDE_CODE=1
