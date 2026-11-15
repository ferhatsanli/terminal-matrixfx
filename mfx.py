#!/usr/bin/env python3
"""
mfx - Matrix Revolutions style output effect for interactive shells.

Works in any terminal emulator. Runs your shell inside a pseudo-terminal and animates the output of every
command: each line streams in from left to right behind a glowing head that
drags a ghost trail of random Matrix glyphs. The whole output of a command
always finishes within MFX_DURATION seconds (default 1.0).

The shell marks where command output starts/ends with two private OSC
sequences (see mfx.zsh / mfx.bash). Everything else (prompt, typed input, full-screen
apps) is passed through untouched.

Environment variables:
  MFX_DURATION   total animation time per output burst in seconds (default 1.0)
  MFX_FPS        frames per second (default 40)
  MFX_GLOW       1 = glowing background around the head, 0 = off (default 1)
  MFX_COLORS     truecolor | 256 | 16 (default: detected from the terminal)
  MFX_GLYPHS     katakana | ascii (default: katakana, ascii on the Linux console)

Usage: mfx.py [shell]   (default: $SHELL)
"""

import codecs
import errno
import fcntl
import os
import random
import re
import select
import signal
import struct
import sys
import termios
import time
import tty
import unicodedata

MARK_START = b"\x1b]7770;S\x07"
MARK_END = b"\x1b]7770;E\x07"
MARKERS = (MARK_START, MARK_END)

DURATION = float(os.environ.get("MFX_DURATION", "1.0"))
FPS = float(os.environ.get("MFX_FPS", "40"))
GLOW = os.environ.get("MFX_GLOW", "1") != "0"

IDLE_GAP = 0.03          # seconds of silence that closes an output burst
MAX_PARSE = 512 * 1024   # bigger bursts: only the tail is parsed/animated

# Trail geometry (in cells, measured backwards from the head)
GHOST = 3      # random glyphs right behind the head
GLOWTXT = 10   # real text still glowing after the ghost
AHEAD = 3      # glow bleeding in front of the head (never past the text)
TRAIL = GHOST + GLOWTXT

KATAKANA_GLYPHS = ("ｦｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ"
                   "0123456789" "Z:.=*+-<>|¦")
ASCII_GLYPHS = "0123456789ABCDEFZ:.=*+-<>|$#%&@"


def detect_color_mode():
    forced = os.environ.get("MFX_COLORS", "").strip().lower()
    if forced in ("truecolor", "24bit"):
        return "truecolor"
    if forced in ("256", "16"):
        return forced
    term = os.environ.get("TERM", "")
    colorterm = os.environ.get("COLORTERM", "").lower()
    program = os.environ.get("TERM_PROGRAM", "")
    if term in ("linux", "dumb", "vt100", "vt220"):
        return "16"
    if colorterm in ("truecolor", "24bit"):
        return "truecolor"
    if program == "Apple_Terminal":
        # Terminal.app supports 24-bit color since macOS 26 Tahoe (Darwin 25)
        try:
            darwin = int(os.uname().release.split(".")[0])
        except ValueError:
            darwin = 0
        return "truecolor" if darwin >= 25 else "256"
    if program in ("iTerm.app", "WezTerm", "vscode", "ghostty", "Hyper", "Tabby",
                   "WarpTerminal", "rio"):
        return "truecolor"
    if term in ("xterm-kitty", "alacritty", "foot", "wezterm", "xterm-ghostty",
                "contour") or term.endswith("-direct"):
        return "truecolor"
    if "256" in term:
        return "256"
    return "16"


COLOR_MODE = detect_color_mode()
if COLOR_MODE == "16":
    GLOW = False                      # no way to draw a soft glow with 16 colors
_glyph_mode = os.environ.get("MFX_GLYPHS", "").strip().lower()
if _glyph_mode not in ("katakana", "ascii"):
    _glyph_mode = "ascii" if os.environ.get("TERM") == "linux" else "katakana"
GLYPHS = ASCII_GLYPHS if _glyph_mode == "ascii" else KATAKANA_GLYPHS

HEAD_FG = (235, 255, 235)
GHOST_FG = ((200, 255, 210), (120, 255, 160), (80, 235, 130))
TEXT_GLOW_FROM = (190, 255, 200)
TEXT_GLOW_TO = (60, 230, 120)
GLOW_BG = ((26, 92, 46), (16, 64, 32), (9, 38, 19), (4, 18, 9), (2, 8, 4))

CSI_RE = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")
OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


class Complex(Exception):
    """Output uses cursor addressing etc. - cannot be animated safely."""


def lerp(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


_CUBE = (0, 95, 135, 175, 215, 255)
_cache256 = {}


def rgb_to_256(c):
    """Nearest xterm-256 palette index for an RGB tuple."""
    if c in _cache256:
        return _cache256[c]

    def q(v):
        return 0 if v < 48 else 1 if v < 115 else (v - 35) // 40

    qr, qg, qb = q(c[0]), q(c[1]), q(c[2])
    cube = (_CUBE[qr], _CUBE[qg], _CUBE[qb])
    cube_idx = 16 + 36 * qr + 6 * qg + qb
    avg = sum(c) // 3
    gi = 0 if avg < 8 else min(23, (avg - 8) // 10)
    gv = 8 + 10 * gi

    def dist(a):
        return sum((a[i] - c[i]) ** 2 for i in range(3))

    gray_penalty = 3 if max(c) - min(c) > 30 else 1   # keep the green hue
    idx = cube_idx if dist(cube) <= gray_penalty * dist((gv, gv, gv)) else 232 + gi
    _cache256[c] = idx
    return idx


def fg(c):
    if COLOR_MODE == "truecolor":
        return "\x1b[38;2;%d;%d;%dm" % c
    if COLOR_MODE == "256":
        return "\x1b[38;5;%dm" % rgb_to_256(c)
    if min(c) > 170:
        return "\x1b[97m"            # bright white
    if max(c) >= 200:
        return "\x1b[92m"            # bright green
    if max(c) >= 100:
        return "\x1b[32m"            # green
    return "\x1b[2;32m"              # dim green


def bg(c):
    if COLOR_MODE == "truecolor":
        return "\x1b[48;2;%d;%d;%dm" % c
    if COLOR_MODE == "256":
        return "\x1b[48;5;%dm" % rgb_to_256(c)
    return ""


def glow_bg(dist):
    if not GLOW:
        return ""
    dist = abs(dist)
    if dist < len(GLOW_BG):
        return bg(GLOW_BG[dist])
    return ""


def char_width(ch):
    o = ord(ch)
    if o < 32 or 0x7F <= o < 0xA0:
        return 0
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


CONT = ("", "", 0)  # second half of a wide character


def term_size():
    try:
        rows, cols, _, _ = struct.unpack(
            "HHHH", fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 8))
        if rows and cols:
            return rows, cols
    except OSError:
        pass
    return 24, 80


class Model:
    """Tiny line-oriented screen model of one output burst."""

    def __init__(self, width, first_row, col, sgr):
        self.width = width
        self.rows = [dict(first_row)]
        self.first_changed = col
        self.row = 0
        self.col = col
        self.sgr = sgr

    def feed(self, text):
        pos = 0
        n = len(text)
        while pos < n:
            ch = text[pos]
            if ch == "\x1b":
                m = CSI_RE.match(text, pos)
                if m:
                    self._csi(m.group(1), m.group(2), m.group(3), m.group(0))
                    pos = m.end()
                    continue
                m = OSC_RE.match(text, pos)
                if m:
                    pos = m.end()          # hyperlinks / titles: dropped
                    continue
                if pos + 1 < n and text[pos + 1] in "78MDEc":
                    raise Complex()
                if pos + 1 >= n:
                    break
                pos += 3 if text[pos + 1] in "()*+#%" else 2
                continue
            if ch == "\n":
                self._newline()
            elif ch == "\r":
                self.col = 0
            elif ch == "\t":
                self.col = min(self.width - 1, (self.col // 8 + 1) * 8)
            elif ch == "\b":
                self.col = max(0, self.col - 1)
            else:
                self._put(ch)
            pos += 1

    def _newline(self):
        self.row += 1
        self.col = 0
        if self.row >= len(self.rows):
            self.rows.append({})

    def _put(self, ch):
        w = char_width(ch)
        cells = self.rows[self.row]
        if w == 0:
            if ord(ch) >= 32 and self.col > 0:
                prev = cells.get(self.col - 1)
                if prev and prev is not CONT:
                    cells[self.col - 1] = (prev[0] + ch, prev[1], prev[2])
            return
        if self.col + w > self.width:
            self._newline()
            cells = self.rows[self.row]
        if self.row == 0:
            self.first_changed = min(self.first_changed, self.col)
        cells[self.col] = (ch, self.sgr, w)
        if w == 2:
            cells[self.col + 1] = CONT
        self.col += w

    def _csi(self, params, inter, final, seq):
        if final == "m" and not inter:
            if params in ("", "0"):
                self.sgr = ""
            elif params.startswith("0;"):
                self.sgr = seq
            else:
                self.sgr += seq
            return
        if final == "K":
            cells = self.rows[self.row]
            if params in ("", "0"):
                gone = [c for c in cells if c >= self.col]
            elif params == "2":
                gone = list(cells)
            else:
                gone = [c for c in cells if c <= self.col]
            for c in gone:
                del cells[c]
            if self.row == 0 and gone:
                self.first_changed = min(self.first_changed, min(gone))
            return
        if final in "hl" and params.startswith("?"):
            modes = params[1:].split(";")
            if any(m in ("1049", "47", "1047", "1048") for m in modes):
                raise Complex()
            return                      # cursor visibility, paste mode ...
        if final in "ABCDEFGHJSTdfrsuLMP@Xa`e" :
            raise Complex()
        # anything else: ignore


def render_final(cells, start, sgr_reset=True):
    out = []
    cur = None
    if not cells:
        return "\x1b[0m\x1b[K"
    end = max(cells) + 1
    x = start
    while x < end:
        cell = cells.get(x)
        if cell is CONT:
            x += 1
            continue
        if cell is None:
            if cur != "":
                out.append("\x1b[0m")
                cur = ""
            out.append(" ")
            x += 1
            continue
        ch, sgr, w = cell
        if sgr != cur:
            out.append("\x1b[0m" + sgr)
            cur = sgr
        out.append(ch)
        x += w
    out.append("\x1b[0m\x1b[K")
    return "".join(out)


class Animation:
    def __init__(self, write, model, start_col):
        self.write = write
        self.model = model
        self.width = model.width
        self.done = False
        rows = model.rows
        self.cur_row = 0
        self.start = time.monotonic()
        self.lines = []  # [row_index, start_col, text_len, head_prev, finished]
        for i, cells in enumerate(rows):
            sc = model.first_changed if i == 0 else 0
            # the effect stops at the last visible character of the line
            visible = [c for c, v in cells.items()
                       if v is not CONT and v[0].strip()]
            ln = max([c + cells[c][2] for c in visible] or [0])
            if i == len(rows) - 1 and ln == 0:
                continue                      # cursor row after final newline
            if ln <= sc:
                continue                      # nothing visible to animate
            self.lines.append([i, sc, ln, float(sc), False])
        n = len(self.lines)
        # same speed for every line: short lines simply finish earlier
        self.travel = max([l[2] - l[1] for l in self.lines] or [1]) + TRAIL
        if n <= 1:
            self.row_dur, self.stagger = DURATION, 0.0
        else:
            self.row_dur = DURATION * 0.55
            self.stagger = (DURATION - self.row_dur) / (n - 1)
        # reserve the rows on screen
        last = len(rows) - 1
        buf = ["\x1b[?25l"]
        if last:
            buf.append("\n" * last)
            buf.append("\x1b[%dA" % last)
        self.write("".join(buf))
        if not self.lines:
            self.finish()

    def goto(self, row, col):
        s = ""
        if row > self.cur_row:
            s += "\x1b[%dB" % (row - self.cur_row)
        elif row < self.cur_row:
            s += "\x1b[%dA" % (self.cur_row - row)
        self.cur_row = row
        return s + "\x1b[%dG" % (col + 1)

    def tick(self, now=None):
        if self.done:
            return
        now = time.monotonic() if now is None else now
        t = now - self.start
        out = []
        all_done = True
        for idx, ln in enumerate(self.lines):
            row, sc, tl, head_prev, finished = ln
            if finished:
                continue
            p = (t - idx * self.stagger) / self.row_dur
            if p <= 0:
                all_done = False
                continue
            head = sc + p * self.travel
            if p >= 1 or head >= tl + TRAIL:
                out.append(self.goto(row, sc))
                out.append(render_final(self.model.rows[row], sc))
                ln[4] = True
                continue
            all_done = False
            ln[3] = head
            out.append(self._draw(row, sc, tl, head_prev, head))
        if out:
            self.write("".join(out))
        if all_done:
            self.finish()

    def _draw(self, row, sc, tl, head_prev, head):
        cells = self.model.rows[row]
        h = int(head)
        lo = max(sc, int(head_prev) - TRAIL - 1)
        hi = min(self.width - 1, h + AHEAD, tl - 1)
        while lo > sc and cells.get(lo) is CONT:
            lo -= 1
        if lo > hi:
            return ""
        out = [self.goto(row, lo)]
        x = lo
        while x <= hi:
            d = h - x
            cell = cells.get(x)
            if d < 0:
                out.append("\x1b[0m" + glow_bg(d) + " ")
                x += 1
                continue
            if d == 0:
                out.append("\x1b[0;1m" + fg(HEAD_FG) + glow_bg(0)
                           + random.choice(GLYPHS))
                x += 1
                continue
            if d <= GHOST:
                out.append("\x1b[0m" + fg(GHOST_FG[d - 1]) + glow_bg(d)
                           + random.choice(GLYPHS))
                x += 1
                continue
            if cell is CONT:
                x += 1
                continue
            if d <= GHOST + GLOWTXT:
                c = lerp(TEXT_GLOW_FROM, TEXT_GLOW_TO, (d - GHOST) / GLOWTXT)
                pre = "\x1b[0m" + fg(c) + glow_bg(d)
            else:
                pre = "\x1b[0m" + (cell[1] if cell else "")
            if cell is None:
                out.append(pre + " ")
                x += 1
            else:
                if cell[2] == 2 and x + 1 > hi:
                    out.append(pre + " ")   # no room, finish next frame
                    x += 1
                    continue
                out.append(pre + cell[0])
                x += cell[2]
        out.append("\x1b[0m")
        return "".join(out)

    def finish(self):
        """Jump to the final state immediately (also used when skipping)."""
        if self.done:
            return
        out = []
        for ln in self.lines:
            if not ln[4]:
                out.append(self.goto(ln[0], ln[1]))
                out.append(render_final(self.model.rows[ln[0]], ln[1]))
                ln[4] = True
        last = len(self.model.rows) - 1
        out.append(self.goto(last, self.model.col))
        out.append("\x1b[0m\x1b[?25h")
        self.write("".join(out))
        self.done = True


class Proxy:
    def __init__(self, master):
        self.master = master
        self.queue = []          # [kind, bytes]  kind: 'raw' | 'anim'
        self.pending = b""       # possible partial marker
        self.capturing = False
        self.interactive = False
        self.last_data = 0.0
        self.anim = None
        self.reset_command()

    def reset_command(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.carry_row = {}
        self.col = 0
        self.sgr = ""

    # ---- output side -------------------------------------------------
    def write(self, s):
        data = s.encode("utf-8") if isinstance(s, str) else s
        while data:
            try:
                n = os.write(1, data)
                data = data[n:]
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EINTR):
                    time.sleep(0.001)
                    continue
                raise

    def push(self, kind, data):
        if not data:
            return
        if self.queue and self.queue[-1][0] == kind:
            self.queue[-1][1] += data
        else:
            self.queue.append([kind, data])

    def on_child_output(self, data):
        self.last_data = time.monotonic()
        buf = self.pending + data
        self.pending = b""
        while buf:
            i = buf.find(b"\x1b]7770;")
            if i < 0:
                # keep a possible partial marker at the end
                j = buf.rfind(b"\x1b")
                if j >= 0 and len(buf) - j < len(MARK_START) and \
                        any(m.startswith(buf[j:]) for m in MARKERS):
                    self.pending = buf[j:]
                    buf = buf[:j]
                self._push_data(buf)
                return
            self._push_data(buf[:i])
            rest = buf[i:]
            if rest.startswith(MARK_START):
                self.capturing = True
                self.interactive = False
                self.queue.append(["start", b""])
                buf = rest[len(MARK_START):]
            elif rest.startswith(MARK_END):
                if self.capturing and not self.interactive:
                    self.queue.append(["end", b""])
                self.capturing = False
                buf = rest[len(MARK_END):]
            elif len(rest) < len(MARK_START):
                self.pending = rest
                return
            else:
                self._push_data(rest[:1])
                buf = rest[1:]

    def _push_data(self, data):
        if self.capturing and not self.interactive:
            self.push("anim", data)
        else:
            self.push("raw", data)

    def go_interactive(self):
        """User typed something or output is not animatable: stop effects."""
        if self.anim and not self.anim.done:
            self.anim.finish()
        self.anim = None
        if self.capturing:
            self.interactive = True
        for item in self.queue:
            if item[0] == "anim":
                item[0] = "raw"

    def process(self, now):
        if self.anim:
            self.anim.tick(now)
            if not self.anim.done:
                return
            self.anim = None
        while self.queue:
            kind, data = self.queue[0]
            if kind == "start":
                self.queue.pop(0)
                self.reset_command()
                continue
            if kind == "end":
                self.queue.pop(0)
                if self.col:
                    # output did not end with a newline (zsh PROMPT_SP replacement)
                    self.write("\x1b[0;1;7m%\x1b[0m\r\n")
                    self.col = 0
                continue
            if kind == "raw":
                self.queue.pop(0)
                self.write(data)
                continue
            # anim: wait until the burst is complete
            more = len(self.queue) > 1
            if not more and now - self.last_data < IDLE_GAP and len(data) < MAX_PARSE:
                return
            self.queue.pop(0)
            self.start_animation(data)
            if self.anim:
                return

    def start_animation(self, data):
        if len(data) > MAX_PARSE:
            # print the head raw, animate only the tail
            cut = data.rfind(b"\n", 0, len(data) - MAX_PARSE // 4)
            if cut > 0:
                head, data = data[:cut + 1], data[cut + 1:]
                self.write(head)
                sgrs = re.findall(rb"\x1b\[[0-9;]*m", head)
                self.sgr = sgrs[-1].decode() if sgrs else ""
                self.carry_row, self.col = {}, 0
                self.decoder.reset()
        text = self.decoder.decode(data)
        if os.environ.get("MFX_DEBUG"):
            with open(os.environ["MFX_DEBUG"], "a") as f:
                f.write(repr(text) + "\n")
        rows_h, width = term_size()
        model = Model(width, self.carry_row, self.col, self.sgr)
        try:
            model.feed(text)
        except Complex:
            self.write("\x1b[0m")
            self.write(data)
            self.go_interactive()
            self.interactive = True
            return
        # too many rows for the screen: print the top part instantly
        limit = max(1, rows_h - 1)
        if len(model.rows) > limit:
            k = len(model.rows) - limit
            parts = [render_final(model.rows[0], model.first_changed)]
            for r in range(1, k):
                parts.append("\r\n" + render_final(model.rows[r], 0))
            parts.append("\r\n")
            self.write("\x1b[%dG" % (model.first_changed + 1) + "".join(parts))
            model.rows = model.rows[k:]
            model.first_changed = 0
            model.row -= k
        self.carry_row = model.rows[-1]
        self.col = model.col
        self.sgr = model.sgr
        self.anim = Animation(self.write, model, model.first_changed)
        if self.anim.done:
            self.anim = None

    def next_timeout(self, now):
        if self.anim:
            return 1.0 / FPS
        if self.queue and self.queue[0][0] == "anim":
            return max(0.0, IDLE_GAP - (now - self.last_data)) + 0.001
        return None


def set_winsize(fd):
    try:
        ws = fcntl.ioctl(0, termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, ws)
    except OSError:
        pass


def main():
    if not (os.isatty(0) and os.isatty(1)):
        return 2
    shell = (sys.argv[1] if len(sys.argv) > 1 else "") or \
        os.environ.get("SHELL") or "/bin/sh"
    master, slave = os.openpty()
    try:
        termios.tcsetattr(slave, termios.TCSANOW, termios.tcgetattr(0))
    except termios.error:
        pass
    set_winsize(slave)

    pid = os.fork()
    if pid == 0:
        try:
            os.close(master)
            os.setsid()
            try:
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            except (AttributeError, OSError):
                os.close(os.open(os.ttyname(slave), os.O_RDWR))
            for fd in (0, 1, 2):
                os.dup2(slave, fd)
            if slave > 2:
                os.close(slave)
            # hooks only fire on this exact terminal (not in nested tmux panes)
            os.environ["MFX_ACTIVE"] = os.ttyname(0)
            os.execvp(shell, [shell, "-i"])
        finally:
            os._exit(127)
    os.close(slave)

    winch = [False]
    signal.signal(signal.SIGWINCH, lambda *_: winch.__setitem__(0, True))

    old = termios.tcgetattr(0)
    tty.setraw(0)
    proxy = Proxy(master)
    try:
        while True:
            if winch[0]:
                winch[0] = False
                set_winsize(master)
            now = time.monotonic()
            proxy.process(now)
            timeout = proxy.next_timeout(time.monotonic())
            try:
                r, _, _ = select.select([0, master], [], [], timeout)
            except InterruptedError:
                continue
            if master in r:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    data = b""
                if not data:
                    break
                proxy.on_child_output(data)
            if 0 in r:
                data = os.read(0, 4096)
                if data:
                    if proxy.capturing or proxy.anim:
                        proxy.go_interactive()
                    os.write(master, data)
        # flush whatever is left
        proxy.go_interactive()
        proxy.process(time.monotonic())
    finally:
        termios.tcsetattr(0, termios.TCSAFLUSH, old)
        proxy.write("\x1b[0m\x1b[?25h")
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never leave the user without a shell
        if os.environ.get("MFX_DEBUG"):
            import traceback
            with open(os.environ["MFX_DEBUG"], "a") as f:
                traceback.print_exc(file=f)
        sys.stderr.write("mfx: %s\n" % exc)
        sys.exit(3)
