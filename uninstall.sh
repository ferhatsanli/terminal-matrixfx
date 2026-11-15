#!/bin/sh
# Removes the Matrix output effect (mfx) from your shell config and deletes ~/.mfx.
set -e

for rc in "${ZDOTDIR:-$HOME}/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
  [ -f "$rc" ] || continue
  grep -q -e 'MFX-' -e '\.mfx/' -e 'added by mfx' "$rc" || continue
  tmp=$(mktemp)
  sed -e '/>>> MFX-BEGIN/,/<<< MFX-END/d' \
      -e '/>>> MFX-HOOKS/,/<<< MFX-HOOKS/d' \
      -e '/^# Matrix output effect hooks/d' \
      -e '/\.mfx\/mfx\.zsh/d' \
      -e '/\.mfx\/mfx\.bash/d' \
      -e '/# added by mfx$/d' "$rc" > "$tmp"
  cat "$tmp" > "$rc"
  rm -f "$tmp"
  echo "Cleaned $rc"
done

rm -rf "$HOME/.mfx"
echo "Removed ~/.mfx. Open a new terminal window or tab."
