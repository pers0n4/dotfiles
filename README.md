# dotfiles

## [Homebrew](https://brew.sh/)

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Activate Homebrew in the current shell
eval "$(/opt/homebrew/bin/brew shellenv)"
```

- [Official installation and post-installation steps](https://docs.brew.sh/Installation)
- [Brew Bundle and Brewfile](https://docs.brew.sh/Brew-Bundle-and-Brewfile)

## [mise-en-place](https://mise.jdx.dev/)

- `activate`: manages tool paths, environment variables, and hooks in the current shell.
- `--shims`: adds shims to `PATH` and selects tools per command without changing the parent shell's environment variables or hooks.

For interactive terminals alone, `activate` is sufficient. Add `--shims` when IDEs or editors inheriting the login environment also need tool access. Verify environment inheritance separately for GUI apps.

Place these lines after Homebrew setup. Do not duplicate entries already present in your personal configuration.

```sh
# ~/.zprofile: add shims to the login environment
eval "$(mise activate zsh --shims)"
# ~/.zshrc: activate tools, environment variables, and hooks for interactive shells
eval "$(mise activate zsh)"
```

For scripts and CI, use `mise exec -- <command>` without separate activation.

- [mise activate reference](https://mise.jdx.dev/cli/activate.html)
- [Shims: usage, PATH setup, and activation differences](https://mise.jdx.dev/dev-tools/shims.html)
