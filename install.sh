#!/bin/zsh
# Installs the Matrix output effect (mfx) for zsh in iTerm2.
set -e
SRC=${0:A:h}
DEST=$HOME/.mfx
ZSHRC=$HOME/.zshrc

command -v python3 >/dev/null || { echo "python3 not found (install Xcode Command Line Tools: xcode-select --install)"; exit 1; }

mkdir -p $DEST
cp $SRC/mfx.py $SRC/mfx.zsh $DEST/
chmod +x $DEST/mfx.py

touch $ZSHRC
if ! grep -q 'MFX-BEGIN' $ZSHRC; then
  cp $ZSHRC $ZSHRC.before-mfx
  {
    cat <<'EOF'
# >>> MFX-BEGIN (Matrix output effect) - keep at the very top of .zshrc
if [[ -o interactive && -z $MFX_ACTIVE && -z $MFX_DISABLE && $TERM_PROGRAM == iTerm.app && -x $HOME/.mfx/mfx.py ]]; then
  $HOME/.mfx/mfx.py && exit
fi
# <<< MFX-END
EOF
    cat $ZSHRC.before-mfx
    cat <<'EOF'

# Matrix output effect hooks (keep at the end of .zshrc)
[[ -f $HOME/.mfx/mfx.zsh ]] && source $HOME/.mfx/mfx.zsh
EOF
  } > $ZSHRC
  echo "Updated $ZSHRC (backup: $ZSHRC.before-mfx)"
else
  echo "$ZSHRC already contains mfx, only the files were updated"
fi
echo "Done. Open a new iTerm2 tab."
