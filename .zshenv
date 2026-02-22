# https://specifications.freedesktop.org/basedir/latest/
# https://wiki.archlinux.org/title/XDG_Base_Directory
export XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-$HOME/.cache}
export XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
export XDG_STATE_HOME=${XDG_STATE_HOME:-$HOME/.local/state}

# https://zsh.sourceforge.io/Guide/zshguide02.html
# https://wiki.archlinux.org/title/Zsh
export ZDOTDIR=${ZDOTDIR:-$HOME}

# https://zsh.sourceforge.io/Doc/Release/Options.html#Options
# 1. History metadata and immediate append
setopt EXTENDED_HISTORY INC_APPEND_HISTORY_TIME
# 2. Duplicate control
setopt HIST_IGNORE_ALL_DUPS HIST_SAVE_NO_DUPS HIST_FIND_NO_DUPS HIST_EXPIRE_DUPS_FIRST
# 3. Drop noisy entries
setopt HIST_NO_FUNCTIONS HIST_NO_STORE
# 4. Normalize command lines before storing
setopt HIST_REDUCE_BLANKS

export HOMEBREW_BUNDLE_DUMP_NO_VSCODE=1
export HOMEBREW_BUNDLE_DUMP_NO_GO=1
export HOMEBREW_BUNDLE_DUMP_NO_CARGO=1

export MISE_CONFIG_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/mise
export MISE_CACHE_DIR=${XDG_CACHE_HOME:-$HOME/.cache}/mise
export MISE_STATE_DIR=${XDG_STATE_HOME:-$HOME/.local/state}/mise
export MISE_DATA_DIR=${XDG_DATA_HOME:-$HOME/.local/share}/mise
export MISE_SHIMS_DIR=${XDG_DATA_HOME:-$HOME/.local/share}/mise/shims

export EZA_CONFIG_DIR=$XDG_CONFIG_HOME/eza

export SKIM_DEFAULT_OPTIONS="$SKIM_DEFAULT_OPTIONS --color=fg:#cdd6f4,bg:#1e1e2e,matched:#313244,matched_bg:#f2cdcd,current:#cdd6f4,current_bg:#45475a,current_match:#1e1e2e,current_match_bg:#f5e0dc,spinner:#a6e3a1,info:#cba6f7,prompt:#89b4fa,cursor:#f38ba8,selected:#eba0ac,header:#94e2d5,border:#6c7086"
