# Kiro CLI pre block. Keep at the top of this file.
[[ -f "${HOME}/Library/Application Support/kiro-cli/shell/zprofile.pre.zsh" ]] && builtin source "${HOME}/Library/Application Support/kiro-cli/shell/zprofile.pre.zsh"

# Added by Windsurf
export PATH="$HOME/.codeium/windsurf/bin:$PATH"

# Added by Antigravity
export PATH="$HOME/.antigravity/antigravity/bin:$PATH"

# Homebrew
eval "$(/opt/homebrew/bin/brew shellenv)"

# mise
eval "$(mise activate zsh --shims)"

# Set up fzf key bindings and fuzzy completion
source <(fzf --zsh)

# Added by OrbStack: command-line tools and integration
# This won't be added again if you remove it.
source $HOME/.orbstack/shell/init.zsh 2>/dev/null || :

# Added by Toolbox App
export PATH="$PATH:$HOME/Library/Application Support/JetBrains/Toolbox/scripts"

# Kiro CLI post block. Keep at the bottom of this file.
[[ -f "${HOME}/Library/Application Support/kiro-cli/shell/zprofile.post.zsh" ]] && builtin source "${HOME}/Library/Application Support/kiro-cli/shell/zprofile.post.zsh"
