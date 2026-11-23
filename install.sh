#!/bin/sh
# Installs the Matrix output effect (mfx) for zsh and/or bash.
#
#   sh install.sh             install for your login shell ($SHELL)
#   sh install.sh zsh bash    install for the given shells
#
# Re-running it updates the files and the blocks in your shell config.
set -e
# also works when started as "zsh install.sh"
[ -n "$ZSH_VERSION" ] && setopt SH_WORD_SPLIT

SRC=$(cd "$(dirname "$0")" && pwd)
DEST="$HOME/.mfx"

if ! command -v python3 >/dev/null 2>&1; then
  echo "mfx: python3 not found."
  echo "     macOS: xcode-select --install    Linux: install python3 with your package manager"
  exit 1
fi

shells="$*"
if [ -z "$shells" ]; then
  shells=$(basename "${SHELL:-}")
fi

mkdir -p "$DEST"
cp "$SRC/mfx.py" "$SRC/mfx.zsh" "$SRC/mfx.bash" "$SRC/mfx-done.wav" "$DEST/"
chmod +x "$DEST/mfx.py"

# Remove blocks written by any earlier version of this installer.
strip_mfx() {
  sed -e '/>>> MFX-BEGIN/,/<<< MFX-END/d' \
      -e '/>>> MFX-HOOKS/,/<<< MFX-HOOKS/d' \
      -e '/^# Matrix output effect hooks/d' \
      -e '/\.mfx\/mfx\.zsh/d' \
      -e '/\.mfx\/mfx\.bash/d' "$1" |
  awk '{ l[NR] = $0 } END { n = NR; while (n > 0 && l[n] == "") n--; for (i = 1; i <= n; i++) print l[i] }'
}

# install_rc FILE LAUNCHER HOOKS
install_rc() {
  rc=$1
  touch "$rc"
  [ -f "$rc.before-mfx" ] || cp "$rc" "$rc.before-mfx"
  tmp=$(mktemp)
  {
    printf '%s\n' "$2"
    strip_mfx "$rc"
    printf '\n%s\n' "$3"
  } > "$tmp"
  cat "$tmp" > "$rc"   # keeps symlinks and permissions
  rm -f "$tmp"
  echo "Updated $rc (backup: $rc.before-mfx)"
}

ZSH_LAUNCHER='# >>> MFX-BEGIN (Matrix output effect) - keep at the very top of .zshrc
if [[ -o interactive && -t 0 && -t 1 && "$MFX_ACTIVE" != "$TTY" && -z "$MFX_DISABLE" && "$TERM" != dumb && -z "$INSIDE_EMACS" && "$TERM_PROGRAM" != WarpTerminal && -x "$HOME/.mfx/mfx.py" ]]; then
  "$HOME/.mfx/mfx.py" "${ZSH_ARGZERO#-}" && exit
fi
# <<< MFX-END'

ZSH_HOOKS='# >>> MFX-HOOKS (Matrix output effect) - keep at the end of .zshrc
[[ -f "$HOME/.mfx/mfx.zsh" ]] && source "$HOME/.mfx/mfx.zsh"
# <<< MFX-HOOKS'

BASH_LAUNCHER='# >>> MFX-BEGIN (Matrix output effect) - keep at the very top of .bashrc
if [[ $- == *i* && -t 0 && -t 1 && "$MFX_ACTIVE" != "$(tty)" && -z "$MFX_DISABLE" && "$TERM" != dumb && -z "$INSIDE_EMACS" && "$TERM_PROGRAM" != WarpTerminal && -x "$HOME/.mfx/mfx.py" ]] \
   && (( BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 4) )); then
  "$HOME/.mfx/mfx.py" "$BASH" && exit
fi
# <<< MFX-END'

BASH_HOOKS='# >>> MFX-HOOKS (Matrix output effect) - keep at the end of .bashrc
[[ -f "$HOME/.mfx/mfx.bash" ]] && source "$HOME/.mfx/mfx.bash"
# <<< MFX-HOOKS'

for sh in $shells; do
  case $sh in
    zsh)
      install_rc "${ZDOTDIR:-$HOME}/.zshrc" "$ZSH_LAUNCHER" "$ZSH_HOOKS"
      ;;
    bash)
      install_rc "$HOME/.bashrc" "$BASH_LAUNCHER" "$BASH_HOOKS"
      # macOS terminals start login shells, which read ~/.bash_profile, not ~/.bashrc
      if [ "$(uname)" = Darwin ]; then
        profile=""
        for f in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
          if [ -f "$f" ]; then profile=$f; break; fi
        done
        [ -n "$profile" ] || profile="$HOME/.bash_profile"
        if ! grep -q 'bashrc' "$profile" 2>/dev/null; then
          printf '\n%s\n' '[ -n "$BASH_VERSION" ] && [ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"  # added by mfx' >> "$profile"
          echo "Updated $profile so that login shells load ~/.bashrc"
        fi
        bv=$(bash -c 'echo ${BASH_VERSINFO[0]}${BASH_VERSINFO[1]}' 2>/dev/null || echo 0)
        if [ "$bv" -lt 44 ]; then
          echo "Note: mfx needs bash 4.4+. The bash shipped with macOS is 3.2; install a newer one with: brew install bash"
        fi
      fi
      ;;
    *)
      echo "mfx: '$sh' is not supported (only zsh and bash). Run: sh install.sh zsh   or   sh install.sh bash"
      ;;
  esac
done

echo "Done. Open a new terminal window or tab."
