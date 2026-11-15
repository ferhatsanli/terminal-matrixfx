# mfx.bash - bash hooks for the Matrix output effect (sourced at the END of ~/.bashrc)
# Needs bash 4.4+ (PS0). Only active directly inside the mfx proxy.
[[ -n $MFX_ACTIVE && $MFX_ACTIVE == "$(tty 2>/dev/null)" ]] || return 0
if (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4) )); then
  return 0
fi

MFX_ENABLED=${MFX_ENABLED:-1}

# Full-screen / interactive programs: never animated.
MFX_SKIP=(
  vim nvim vi view nano pico emacs micro hx
  less more most man top htop btop atop glances
  ssh mosh tmux screen watch fzf tig lazygit ranger nnn yazi mc
  sftp ftp telnet nc
)
# Animated only when given arguments (a bare call opens a REPL).
MFX_SKIP_NOARGS=(
  python python3 ipython node irb ruby lua sqlite3 psql mysql redis-cli bc kotlinc kotlin
)

_mfx_in() {
  local needle=$1 item
  shift
  for item in "$@"; do [[ $item == "$needle" ]] && return 0; done
  return 1
}

# Runs from PS0, after a command line is read and before it executes.
_mfx_start() {
  (( MFX_ENABLED )) || return 0
  local line
  line=$(HISTTIMEFORMAT= builtin history 1)
  line=${line#"${line%%[![:space:]]*}"}   # leading spaces
  line=${line#*[[:space:]]}               # history number
  local -a words
  read -r -a words <<< "$line"
  local i=0
  while (( i < ${#words[@]} )) && [[ ${words[i]} == *=* || ${words[i]} =~ ^(sudo|time|command|builtin|exec|nohup)$ ]]; do
    (( i++ ))
  done
  local cmd=${words[i]##*/}
  _mfx_in "$cmd" "${MFX_SKIP[@]}" && return 0
  _mfx_in "$cmd" "${MFX_SKIP_NOARGS[@]}" && (( i == ${#words[@]} - 1 )) && return 0
  printf '\e]7770;S\a'
}

_mfx_end() {
  printf '\e]7770;E\a'
}

mfx() {
  case $1 in
    on)  MFX_ENABLED=1 ;;
    off) MFX_ENABLED=0 ;;
    *)   if (( MFX_ENABLED )); then echo "mfx: on  (usage: mfx on|off)"; else echo "mfx: off  (usage: mfx on|off)"; fi ;;
  esac
}

PS0='$(_mfx_start)'"${PS0}"
# _mfx_end must run first, before anything else prints
if [[ "$(declare -p PROMPT_COMMAND 2>/dev/null)" == "declare -a"* ]]; then
  PROMPT_COMMAND=(_mfx_end "${PROMPT_COMMAND[@]}")
else
  PROMPT_COMMAND="_mfx_end${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
fi
