#!/usr/bin/env bash

root="${MISE_PROJECT_ROOT:-}"
[ -n "$root" ] && [ "$root" != "${MISE_CONFIG_ROOT:-}" ] || exit 0
stamp="${XDG_CACHE_HOME:-$HOME/.cache}/mise-outdated/$(printf %s "$root" | shasum | cut -c1-16)"
[ -f "$stamp" ] && [ -z "$(find "$stamp" -mmin +1440)" ] && exit 0
out="$(mise outdated --no-global 2>/dev/null)" || exit 0
mkdir -p "${stamp%/*}" && printf '%s\n' "$root" >"$stamp"
[ -n "$out" ] || exit 0
printf '\033[33m[INFO] mise: 업데이트 가능한 프로젝트 도구가 있습니다. 업데이트: mise upgrade --no-global\033[0m\n%s\n' "$out" >&2
