# iterm-matrixfx

Command output in iTerm2, written to the screen like the cast credits of *The Matrix Revolutions*.

![Preview](docs/preview.gif)

Lines don't appear all at once. A glowing head streams across each line from left to right, dragging a short ghost trail of random Matrix glyphs, and the real text is left glowing behind it before it settles into its normal colors.

## Features

- Works on the output of **any command**: `ls`, `git status`, `cat`, scripts, pipelines, ...
- The **whole output of a command always finishes within 1 second**, however long it is.
- Lines start in a quick top-to-bottom wave and all move at the same speed, so short lines finish first.
- The effect **stops at the last character of each line**. Nothing is drawn in the empty space after the text.
- Original colors and layout are kept. Commands still run in a real terminal, so `ls` keeps its columns and colors.
- Full-screen and interactive programs (`vim`, `less`, `top`, `ssh`, REPLs, ...) are never animated.
- Press any key while an animation runs to skip it.

## How it works

Terminal themes can only change colors, not animate text. Instead, `mfx.py` is a small pseudo-terminal (PTY) proxy that runs your zsh inside it:

1. `mfx.zsh` adds a `preexec` hook that prints an invisible marker when a command starts, and a `precmd` hook that prints one when it finishes.
2. `mfx.py` passes everything through untouched (prompt, typed input, full-screen apps) and only animates what arrives between those two markers.
3. Output that moves the cursor around (`clear`, progress UIs, alternate screen) is detected and printed as-is.
4. If you type anything while a command is running, the rest of that command's output is passed through untouched.

## Requirements

- macOS with [iTerm2](https://iterm2.com)
- zsh (the default macOS shell)
- `python3` (comes with the Xcode Command Line Tools: `xcode-select --install`)
- A font that can display half-width katakana (the default macOS fonts can)

## Installation

```bash
git clone https://github.com/ferhatsanli/iterm-matrixfx.git
cd iterm-matrixfx
zsh install.sh
```

Then open a new iTerm2 tab.

`install.sh`:

- copies `mfx.py` and `mfx.zsh` to `~/.mfx/`
- backs up your `~/.zshrc` to `~/.zshrc.before-mfx`
- adds a small launcher block at the **top** of `~/.zshrc` and `source ~/.mfx/mfx.zsh` at the **end**

The effect only starts in iTerm2. Other terminals keep working as before.

### Updating

```bash
cd iterm-matrixfx
git pull
zsh install.sh
```

Re-running the installer only updates the files in `~/.mfx/`. It doesn't touch `~/.zshrc` again.

## Usage

Just use your shell as usual. In addition:

| Command   | What it does                          |
|-----------|---------------------------------------|
| `mfx off` | Turn the effect off for this session  |
| `mfx on`  | Turn it back on                       |
| `mfx`     | Show whether the effect is on or off  |

## Configuration

Export these environment variables **above** the launcher block at the top of `~/.zshrc`, for example `export MFX_DURATION=0.6`:

| Variable       | Default | Description                                              |
|----------------|---------|----------------------------------------------------------|
| `MFX_DURATION` | `1.0`   | Total animation time per output burst, in seconds        |
| `MFX_FPS`      | `40`    | Frames per second                                        |
| `MFX_GLOW`     | `1`     | `1` = glowing background around the head, `0` = off      |

The commands that are never animated live in two arrays in `mfx.zsh`. Change them after the `source` line in `~/.zshrc`:

```zsh
MFX_SKIP+=(k9s)               # never animated
MFX_SKIP_NOARGS+=(deno)       # not animated when called without arguments (REPL)
```

## Uninstall

1. Remove the block between `# >>> MFX-BEGIN` and `# <<< MFX-END` at the top of `~/.zshrc`, and the `source $HOME/.mfx/mfx.zsh` line at the end. Alternatively, restore the backup: `mv ~/.zshrc.before-mfx ~/.zshrc`.
2. Delete the files: `rm -rf ~/.mfx`

## Limitations

- **zsh + iTerm2 only** for now.
- Commands that produce output continuously (e.g. `ping`, build logs) are animated in bursts. Each burst gets its own 1-second animation.
- When an output is taller than the window, only the part that stays visible is animated. The lines above it are printed instantly.
- Hyperlinks in command output (OSC 8) are dropped.
- If `mfx.py` ever crashes, you fall back to a normal zsh, so you are never locked out of your terminal.

## Files

| File         | Purpose                                         |
|--------------|-------------------------------------------------|
| `mfx.py`     | PTY proxy and the animation itself              |
| `mfx.zsh`    | zsh hooks, the `mfx` command and the skip lists |
| `install.sh` | Installer                                       |
