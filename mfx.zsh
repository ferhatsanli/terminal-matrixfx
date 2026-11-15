# mfx.zsh - shell hooks for the Matrix output effect (source at the END of ~/.zshrc)
# Only active inside the mfx proxy.
[[ -n $MFX_ACTIVE ]] || return 0

typeset -g MFX_ENABLED=${MFX_ENABLED:-1}
# mfx itself marks output that did not end with a newline
setopt NO_PROMPT_SP

# Full-screen / interactive programs: never animated.
typeset -ga MFX_SKIP=(
  vim nvim vi view nano pico emacs micro hx
  less more most man top htop btop atop glances
  ssh mosh tmux screen watch fzf tig lazygit ranger nnn yazi mc
  sftp ftp telnet nc
)
# Animated only when given arguments (a bare call opens a REPL).
typeset -ga MFX_SKIP_NOARGS=(
  python python3 ipython node irb ruby lua sqlite3 psql mysql redis-cli bc kotlinc kotlin
)

_mfx_preexec() {
  (( MFX_ENABLED )) || return 0
  local -a words=(${(z)1})
  local i=1
  # skip leading VAR=value assignments and sudo/time/nocorrect/command prefixes
  while (( i <= $#words )) && [[ ${words[i]} == *=* || ${words[i]} == (sudo|time|nocorrect|noglob|command|builtin|exec) ]]; do
    (( i++ ))
  done
  local cmd=${words[i]:t}
  (( ${MFX_SKIP[(Ie)$cmd]} )) && return 0
  (( ${MFX_SKIP_NOARGS[(Ie)$cmd]} )) && (( i == $#words )) && return 0
  printf '\e]7770;S\a'
}

_mfx_precmd() {
  printf '\e]7770;E\a'
}

mfx() {
  case $1 in
    on)  MFX_ENABLED=1 ;;
    off) MFX_ENABLED=0 ;;
    *)   print -r -- "mfx: $( (( MFX_ENABLED )) && print on || print off )  (usage: mfx on|off)" ;;
  esac
}

autoload -Uz add-zsh-hook
add-zsh-hook preexec _mfx_preexec
# our precmd must run first, before anything else prints
precmd_functions=(_mfx_precmd ${precmd_functions:#_mfx_precmd})
