# Amazon Q pre block. Keep at the top of this file.
[[ -f "${HOME}/Library/Application Support/amazon-q/shell/zshrc.pre.zsh" ]] && builtin source "${HOME}/Library/Application Support/amazon-q/shell/zshrc.pre.zsh"

BLACK=$(tput setaf 0)
RED=$(tput setaf 1)
GREEN=$(tput setaf 2)
YELLOW=$(tput setaf 3)
BLUE=$(tput setaf 4)
MAGENTA=$(tput setaf 5)
CYAN=$(tput setaf 6)
WHITE=$(tput setaf 7)
RESET=$(tput sgr0)

# load zgenom
source "${HOME}/.zgenom/zgenom.zsh"

# Check for plugin and zgenom updates every 7 days
# This does not increase the startup time.
zgenom autoupdate

# if the init script doesn't exist
if ! zgenom saved; then
    echo "${BLUE}Creating a zgenom save${RESET}"

    # Add this if you experience issues with missing completions or errors mentioning compdef.
    # zgenom compdef

    # Ohmyzsh base library
    zgenom ohmyzsh

    # plugins
    zgenom ohmyzsh plugins/alias-finder # alias-finder
    zgenom ohmyzsh plugins/aliases # als
    zgenom ohmyzsh plugins/bgnotify
    zgenom ohmyzsh plugins/command-not-found
    zgenom ohmyzsh plugins/copybuffer # ⌃ + o
    zgenom ohmyzsh plugins/fancy-ctrl-z
    zgenom ohmyzsh plugins/git
    zgenom ohmyzsh plugins/sudo # ␛ + ␛
    zgenom ohmyzsh plugins/zoxide
    zgenom ohmyzsh plugins/docker
    zgenom ohmyzsh plugins/docker-compose

    # Install ohmyzsh osx plugin if on macOS
    [[ "$(uname -s)" = Darwin ]] && zgenom ohmyzsh plugins/macos

    # prezto options
    # zgenom prezto editor key-bindings 'emacs'
    # zgenom prezto prompt theme 'sorin'

    # prezto and modules
    # If you use prezto and ohmyzsh - load ohmyzsh first.
    # zgenom prezto
    # zgenom prezto command-not-found

    # Load prezto tmux when tmux is installed
    # if hash tmux &>/dev/null; then
    #     zgenom prezto tmux
    # fi

    # completions
    zgenom load zsh-users/zsh-completions
    # zgenom load zsh-users/zsh-autosuggestions # disabled by q

    # bulk load
    zgenom loadall <<EOPLUGINS
        zsh-users/zsh-syntax-highlighting
        zsh-users/zsh-history-substring-search
EOPLUGINS
    # ^ can't indent this EOPLUGINS

    # add binaries
    # zgenom bin tj/git-extras

    # theme
    # zgenom ohmyzsh themes/arrow

    # save all to init script
    zgenom save

    # Compile your zsh files
    zgenom compile "$HOME/.zshrc"
    # Uncomment if you set ZDOTDIR manually
    # zgenom compile $ZDOTDIR

    # You can perform other "time consuming" maintenance tasks here as well.
    # If you use `zgenom autoupdate` you're making sure it gets
    # executed every 7 days.
    echo "\n${BLUE}Homebrew${RESET}"
    brew doctor
    brew outdated

    echo "\n${BLUE}Amazon Q${RESET}"
    q doctor

    echo "${BLUE}mise${RESET}"
    mise outdated
fi

clear:python() {
    find . -type f -name "*.py[co]" -delete
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type d -name ".mypy_cache" -exec rm -rf {} +
    find . -type d -name ".ruff_cache" -exec rm -rf {} +
    find . -type d -name ".pytest_cache" -exec rm -rf {} +
}

clear:node() {
    find . -type d -name "node_modules" -exec rm -rf {} +
}

unalias l
alias ls="eza --classify=always --color=auto --color-scale=all --color-scale-mode=gradient --icons=auto --no-quotes --group-directories-first"
alias ll="ls --long --header \
    --inode --octal-permissions --links \
    --blocksize \
    --group --flags \
    --created --modified --time-style=long-iso \
    --mounts --git --git-repos"
    # --total-size --changed --accessed
alias lsa="ls --all"
alias la="ll --almost-all"

eval "$(mise activate zsh)"
eval "$(zoxide init zsh)"
# Add the following to the end of ~/.zshrc:
eval "$(starship init zsh)"

# Amazon Q post block. Keep at the bottom of this file.
[[ -f "${HOME}/Library/Application Support/amazon-q/shell/zshrc.post.zsh" ]] && builtin source "${HOME}/Library/Application Support/amazon-q/shell/zshrc.post.zsh"
