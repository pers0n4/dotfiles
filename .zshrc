# Kiro CLI pre block. Keep at the top of this file.
[[ -f "${HOME}/Library/Application Support/kiro-cli/shell/zshrc.pre.zsh" ]] && builtin source "${HOME}/Library/Application Support/kiro-cli/shell/zshrc.pre.zsh"

export LS_COLORS="$(vivid generate catppuccin-mocha)"

#region antidote
source /opt/homebrew/opt/antidote/share/antidote/antidote.zsh

zstyle ':omz:plugins:alias-finder' autoload yes
zstyle ':omz:plugins:alias-finder' cheaper yes

antidote load ${HOME}/.zsh_plugins.txt
#endregion

#region alias
alias mv="mv -iv"
alias cp="cp -iv"
alias mkdir="mkdir -pv"

alias ls="eza --grid --classify=auto --color=auto --color-scale=all --color-scale-mode=gradient --icons=auto --no-quotes --hyperlink --group-directories-first"
alias lsa="eza --grid --classify=auto --color=auto --color-scale=all --color-scale-mode=gradient --icons=auto --no-quotes --hyperlink --group-directories-first --all"
alias ll="eza --long --header --links --flags --blocksize --no-user --time-style=long-iso --mounts --git --classify=auto --color=auto --color-scale=all --color-scale-mode=gradient --icons=auto --no-quotes --hyperlink --group-directories-first"
alias lla="eza --long --header --links --flags --blocksize --no-user --time-style=long-iso --mounts --git --classify=auto --color=auto --color-scale=all --color-scale-mode=gradient --icons=auto --no-quotes --hyperlink --group-directories-first --all"
alias lt="eza --tree --level=2"

alias vim="nvim"
alias vi="nvim"
alias n="nvim"

alias gatewayip="route get default | grep gateway | awk '{print $2}'"
alias privateip="ipconfig getifaddr en0"
alias publicip="curl -s api.ipify.org"
alias wifiinfo="networksetup -getinfo Wi-Fi"
alias portinfo="lsof -iTCP -sTCP:LISTEN -n -P"
#endregion

# eval "$(mise activate zsh)"
eval "$(zoxide init zsh)"
eval "$(starship init zsh)"

[[ "$TERM_PROGRAM" == "kiro" ]] && . "$(kiro --locate-shell-integration-path zsh)"

# Kiro CLI post block. Keep at the bottom of this file.
[[ -f "${HOME}/Library/Application Support/kiro-cli/shell/zshrc.post.zsh" ]] && builtin source "${HOME}/Library/Application Support/kiro-cli/shell/zshrc.post.zsh"
