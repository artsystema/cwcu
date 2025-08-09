#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, glob, time, socket
from PIL import Image, ImageDraw, ImageFont, ImageChops

# pip install luma.oled luma.core
from luma.core.interface.serial import spi
from luma.oled.device import ssd1351  # use ssd1331 if your board is that controller

# ================== CONFIG ==================
WIDTH, HEIGHT = 128, 96
SPI_HZ = 24_000_000
SPI_PORT, SPI_DEVICE = 0, 0
GPIO_DC, GPIO_RST = 25, 24
V_OFFSET = 32
H_OFFSET = 0
BGR = False

ICON_W, ICON_H = 14, 14
IP_REFRESH_S = 1.0
TARGET_FPS = 5.0

# Temp bar grid (lower half)
AMBIENT_DEFAULT = 20.0   # left end of scale
TEMP_MAX_DEFAULT = 50.0  # right end of scale
TEMP_WARN = 45.0         # >= warn -> yellow
TEMP_BAD  = 50.0         # >= bad  -> red
TEMP_COLS = 2            # columns in the grid
TEMP_BAR_H = 9           # bar height (pixels)
TEMP_ROW_GAP = 2         # vertical gap between rows
TEMP_LABEL_W = 40        # reserved pixels at left for label
TEMP_OUTLINE = (90, 90, 90)  # bar outline color
TEMP_TRACK   = (40, 40, 40)  # bar track color
# ============================================

# ---- dynamic state variables (top tiles) ----
# 0=no signal, 1=ok, 2=warn, 3=bad
FANS   = 1
PROBES = 0
PUMPS  = 1
FLOW   = 0

# ---- placeholder temps to render as bars (feed these later) ----
# Use floats in °C or None for missing
TEMP_VALUES = [30.0, 29.2, 31.7, None, 27.5, 33.0]  # edit/update this at runtime

def multiply_paste(base_img, overlay, xy, opacity=1.0):
    x, y = xy
    w, h = overlay.size
    region = base_img.crop((x, y, x + w, y + h)).convert("RGB")
    ov = overlay.convert("RGB")
    mul = ImageChops.multiply(region, ov)
    if opacity < 1.0:
        mul = Image.blend(region, mul, opacity)
    base_img.paste(mul, (x, y))

def get_ip_fast():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.05)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "No IP"

# ---- init display (hardware SPI) ----
serial = spi(
    port=SPI_PORT,
    device=SPI_DEVICE,
    gpio_DC=GPIO_DC,
    gpio_RST=GPIO_RST,
    bus_speed_hz=SPI_HZ
)
device = ssd1351(
    serial,
    width=WIDTH,
    height=HEIGHT,
    rotate=0,
    h_offset=H_OFFSET,
    v_offset=V_OFFSET,
    bgr=BGR
)

STATE_COLORS = {
    0: (50, 50, 50),     # no signal
    1: (255, 255, 255),  # ok
    2: (255, 210, 31),   # warn
    3: (255, 59, 48)     # bad
}

# ---- fonts ----
font = ImageFont.load_default()

# ---- load icon frames once ----
ICON_NAMES = ["fan", "probe", "pump", "flow"]
icon_frames = {}
for name in ICON_NAMES:
    paths = sorted(glob.glob(f"pic/{name}_*.png"))
    if not paths:
        raise RuntimeError(f"No {name} frames found: pic/{name}_*.png")
    frames = [Image.open(p).convert("RGB").resize((ICON_W, ICON_H), Image.NEAREST) for p in paths]
    icon_frames[name] = frames
MAX_FRAMES = max(len(frames) for frames in icon_frames.values())

# ---- build static background once ----
bg = Image.new("RGB", (WIDTH, HEIGHT), "black")
d = ImageDraw.Draw(bg)

# Outer white working area (124x84)
d.rectangle((0, 12, 123, 95), fill="white")
# Inner black metric area (122x72, top)
d.rectangle((1, 13, 122, 86), fill="black")
# White horizontal line (middle of metric area)
line_y = 13 + (72 // 2)
line_y_upd = 18 + (72 // 2)
d.line((1, line_y_upd, 122, line_y_upd), fill="white")
# Black area above horizontal line
d.rectangle((0, 0, 123, line_y + 4), fill="black")
# Bottom white IP bar
d.rectangle((1, 87, 122, 94), fill="white")

spacing = 1
rect_width = (124 - spacing) // 2
rect_height = ((line_y - 10) - spacing) // 2
icon_base = rect_height - 4  # max icon size

metric_boxes = []
text_h = font.getbbox("No")[3] - font.getbbox("No")[1]
line_gap = 1

for i in range(4):
    row = i // 2
    col = i % 2
    left = 0 + col * (rect_width + spacing) + 2 * col
    top = 12 + row * (rect_height + spacing) + 1 * row
    right = left + rect_width - 2 * col
    bottom = top + rect_height - 1
    d.rectangle((left, top, right, bottom), fill=(25, 25, 25))

    icon_x0 = left + 2
    icon_y0 = top + 2
    text_x = left + 2 + icon_base + 3
    text_y = top + (rect_height - (2 * text_h + line_gap)) // 2 + 2
    metric_boxes.append({
        "icon_x0": icon_x0,
        "icon_y0": icon_y0,
        "text_x": text_x,
        "text_y": text_y,
        "rect": (left, top, right, bottom)
    })

# ============= TEMP BAR GRID (no sensor read) =============
def clamp01(x): return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)

def temp_color(c):
    if c is None:
        return (200, 200, 200)       # grey for missing
    if c >= TEMP_BAD:
        return (255, 59, 48)         # red
    if c >= TEMP_WARN:
        return (255, 210, 31)        # yellow
    return (255, 255, 255)           # white

def draw_temp_bars(img, temps, ambient=AMBIENT_DEFAULT, tmax=TEMP_MAX_DEFAULT):
    """
    Draw horizontal bars for temps in the LOWER half (between divider and y=86).
    Layout: TEMP_COLS columns; each cell shows "Tn: xx.x°" + bar.
    """
    draw = ImageDraw.Draw(img)
    # drawing area inside lower half (same as earlier lower metric region)
    ax0, ay0, ax1, ay1 = 1, line_y_upd + 1, 122, 86
    # compute rows/cols
    n = len(temps)
    cols = max(1, TEMP_COLS)
    rows = max(1, (n + cols - 1) // cols)

    # vertical packing
    total_row_h = TEMP_BAR_H + TEMP_ROW_GAP
    needed_h = rows * total_row_h - TEMP_ROW_GAP
    # fit if needed
    if needed_h > (ay1 - ay0 + 1):
        # shrink bar height a bit
        scale = (ay1 - ay0 + 1) / needed_h
        bar_h = max(6, int(TEMP_BAR_H * scale))
        row_gap = max(1, int(TEMP_ROW_GAP * scale))
        total_row_h = bar_h + row_gap
    else:
        bar_h = TEMP_BAR_H
        row_gap = TEMP_ROW_GAP

    col_w = (ax1 - ax0 + 1) // cols

    # labels use small font
    for idx, c in enumerate(temps):
        col = idx % cols
        row = idx // cols
        x0 = ax0 + col * col_w
        y0 = ay0 + row * total_row_h

        # label
        label = f"T{idx+1}: " + ("--.-°" if c is None else f"{c:0.1f}°")
        draw.text((x0, y0), label, fill=temp_color(c), font=font)

        # bar track rect
        bx0 = x0 + TEMP_LABEL_W
        bx1 = ax0 + (col + 1) * col_w - 2
        by0 = y0
        by1 = y0 + bar_h

        # track
        draw.rectangle((bx0, by0, bx1, by1), fill=TEMP_TRACK, outline=TEMP_OUTLINE)

        # fill if we have a value
        if c is not None:
            t = clamp01((c - ambient) / max(1e-6, (tmax - ambient)))
            fx1 = int(bx0 + t * (bx1 - bx0))
            draw.rectangle((bx0, by0, fx1, by1), fill=temp_color(c))

        # optional tick marks at ambient, 30°C midpoint, and max
        # ambient tick
        amb_t = clamp01((ambient - ambient) / max(1e-6, (tmax - ambient)))  # 0
        mid_t = clamp01((30.0 - ambient) / max(1e-6, (tmax - ambient)))
        max_t = 1.0
        for frac in (amb_t, mid_t, max_t):
            tx = int(bx0 + frac * (bx1 - bx0))
            draw.line((tx, by0, tx, by1), fill=(80, 80, 80))
# ===========================================================

def make_frame(frame_idx, ip_text, states):
    img = bg.copy()
    draw = ImageDraw.Draw(img)

    # top 2x2 status boxes + icons
    for idx, mb in enumerate(metric_boxes):
        state = states[idx] if idx < len(states) else 0
        color = STATE_COLORS.get(state, STATE_COLORS[0])
        draw.rectangle(mb["rect"], fill=color)

        name = ICON_NAMES[idx]
        frames = icon_frames[name]
        frame = frames[0] if state == 0 else frames[frame_idx % len(frames)]
        multiply_paste(img, frame, (mb["icon_x0"], mb["icon_y0"]), opacity=1.0)

        draw.text((mb["text_x"], mb["text_y"]),
                  "No" if state == 0 else ("OK" if state == 1 else ("Warn" if state == 2 else "Bad")),
                  fill='black', font=font)
        draw.text((mb["text_x"], mb["text_y"] + 7), "Signal", fill='black', font=font)

    # temps as bars in lower half (no sensor access yet)
    draw_temp_bars(img, TEMP_VALUES, ambient=AMBIENT_DEFAULT, tmax=TEMP_MAX_DEFAULT)

    # IP in bottom white bar
    draw.text((2, 86), ip_text, fill='black', font=font)
    return img

def main():
    target_dt = 1.0 / TARGET_FPS
    next_t = time.perf_counter()

    frame_idx = 0
    ip_cache = "No IP"
    ip_next = 0.0

    while True:
        now = time.perf_counter()
        if now >= ip_next:
            ip_cache = get_ip_fast()
            ip_next = now + IP_REFRESH_S

        # Order matches ICON_NAMES = ["fan","probe","pump","flow"]
        states = [FANS, PROBES, PUMPS, FLOW]
        img = make_frame(frame_idx, ip_cache, states)
        device.display(img)

        frame_idx = (frame_idx + 1) % MAX_FRAMES

        next_t += target_dt
        sleep = next_t - time.perf_counter()
        if sleep > 0:
            time.sleep(sleep)
        else:
            next_t = time.perf_counter()

if __name__ == "__main__":
    main()
