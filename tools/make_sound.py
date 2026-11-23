#!/usr/bin/env python3
"""
Generates mfx-done.wav: the short "output finished" sound of matrixfx.

A quick trickle of high digital blips (the code rain passing by), followed by
a soft low pulse and a resonant two-tone chime that locks in, with a small
echo. Uses only the Python standard library, so the sound can be tweaked and
rebuilt without extra dependencies:

    python3 tools/make_sound.py [output.wav]
"""

import math
import random
import struct
import sys
import wave

RATE = 44100
LENGTH = 0.75            # seconds
PEAK = 0.45              # final peak level (0..1), keeps it from being loud

random.seed(1999)        # same sound every time
buf = [0.0] * int(RATE * LENGTH)


def add_tone(start, dur, freqs, attack, decay, gain, square=0.0):
    """Sum of sines with an attack and exponential decay."""
    s0 = int(start * RATE)
    n = int(dur * RATE)
    for i in range(n):
        if s0 + i >= len(buf):
            break
        t = i / RATE
        env = min(1.0, t / attack) * math.exp(-t / decay)
        v = 0.0
        for f in freqs:
            ph = 2 * math.pi * f * t
            v += math.sin(ph) + square * math.sin(3 * ph) / 3
        buf[s0 + i] += gain * env * v / len(freqs)


# 1) digital rain: a fast, slightly accelerating trickle of high blips
scale = [1568, 1760, 2093, 2349, 2637, 3136, 3520]   # G6 pentatonic-ish
t = 0.0
for k in range(9):
    f = random.choice(scale)
    add_tone(t, 0.06, [f], attack=0.002, decay=0.012,
             gain=0.55 - k * 0.03, square=0.35)
    t += 0.032 - k * 0.0015

# 2) low pulse when the line locks in
add_tone(t, 0.25, [98, 147], attack=0.004, decay=0.06, gain=0.7)

# 3) the chime: a fifth with a slight detune shimmer
add_tone(t, LENGTH - t, [880, 1318.5, 1322.5], attack=0.006, decay=0.16, gain=0.6)
add_tone(t + 0.012, LENGTH - t, [1760], attack=0.004, decay=0.07, gain=0.25)

# 4) small echo
delay = int(0.085 * RATE)
for i in range(delay, len(buf)):
    buf[i] += 0.28 * buf[i - delay]

# fade out the tail and normalize
fade = int(0.08 * RATE)
for i in range(fade):
    buf[-1 - i] *= i / fade
peak = max(abs(v) for v in buf) or 1.0
frames = b"".join(struct.pack("<h", int(v / peak * PEAK * 32767)) for v in buf)

out = sys.argv[1] if len(sys.argv) > 1 else "mfx-done.wav"
with wave.open(out, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(frames)
print("wrote", out)
