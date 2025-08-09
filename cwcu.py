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

ICON_W, ICON_H = 16, 16
IP_REFRESH_S = 1.0
TARGET_FPS = 5.0

# Temp grid (lower half) — scrolling bar chart
AMBIENT_DEFAULT = 20.0   # label at bottom-right
TEMP_MAX_DEFAULT = 50.0  # label at top-right
TICK_S = 2.0             # advance one step every 2 seconds
STEP_W = 3               # 2 px bar + 1 px grid
GRID_COLOR = (60, 60, 60)
BAR_BLUE  = (0, 150, 255)    # at ambient
BAR_RED   = (255, 59, 48)    # at max
# ============================================

# ---- dynamic state variables (top tiles) ----
# 0=no signal, 1=ok, 2=warn, 3=bad
FANS   = 1
PROBES = 0
PUMPS  = 1
FLOW   = 0

# current temperature value to plot (feed this later)
CURRENT_TEMP = 30.0

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

# ======== TEMP GRID (scrolling) ========
# Lower-half area (inside black metric region)
AX0, AY0, AX1, AY1 = 1, line_y_upd + 1, 122, 86
GRID_W, GRID_H = AX1 - AX0 + 1, AY1 - AY0 + 1
graph_img = Image.new("RGB", (GRID_W, GRID_H), "black")

def lerp(a, b, t): return int(a + (b - a) * t + 0.5)

def temp_to_color(temp, ambient=AMBIENT_DEFAULT, tmax=TEMP_MAX_DEFAULT):
    """Linear gradient from BAR_BLUE at ambient to BAR_RED at max."""
    if temp is None:
        return (120, 120, 120)
    if tmax <= ambient:
        t = 1.0
    else:
        t = max(0.0, min(1.0, (temp - ambient) / (tmax - ambient)))
    r = lerp(BAR_BLUE[0], BAR_RED[0], t)
    g = lerp(BAR_BLUE[1], BAR_RED[1], t)
    b = lerp(BAR_BLUE[2], BAR_RED[2], t)
    return (r, g, b)

def graph_tick(temp_value, ambient=AMBIENT_DEFAULT, tmax=TEMP_MAX_DEFAULT):
    """Advance the grid one step: scroll left by STEP_W, add new bar (2 px) + 1 px grid at right."""
    global graph_img
    w, h = graph_img.size
    # scroll left
    if STEP_W > 0:
        graph_img.paste(graph_img.crop((STEP_W, 0, w, h)), (0, 0))
        # clear rightmost STEP_W columns
        ImageDraw.Draw(graph_img).rectangle((w-STEP_W, 0, w-1, h-1), fill=(0, 0, 0))

    # compute bar height from ambient..tmax, bottom anchored
    draw = ImageDraw.Draw(graph_img)
    if temp_value is not None and tmax > ambient:
        frac = max(0.0, min(1.0, (temp_value - ambient) / (tmax - ambient)))
    else:
        frac = 0.0
    bar_h = int(frac * (h - 1))
    y0 = (h - 1) - bar_h
    col = temp_to_color(temp_value, ambient, tmax)

    # draw 2-px bar (columns w-3, w-2)
    bx0 = w - STEP_W
    # ensure we have at least 2 columns for the bar
    bar_cols = max(2, STEP_W - 1)
    for dx in range(bar_cols):  # typically 0,1
        x = bx0 + dx
        draw.line((x, y0, x, h-1), fill=col)

    # draw 1-px grid line at far right (column w-1)
    draw.line((w-1, 0, w-1, h-1), fill=GRID_COLOR)

def draw_temp_grid(img, ambient=AMBIENT_DEFAULT, tmax=TEMP_MAX_DEFAULT):
    """Paste the scrolling grid and draw only two labels on the right (top=max, bottom=ambient)."""
    img.paste(graph_img, (AX0, AY0))
    d = ImageDraw.Draw(img)
    # Top-right: max
    max_txt = f"{int(tmax)}°C"
    tw = font.getbbox(max_txt)[2]
    d.text((AX1 - tw, AY0), max_txt, fill=(220, 220, 220), font=font)
    # Bottom-right: ambient
    amb_txt = f"{int(ambient)}°C"
    tw2 = font.getbbox(amb_txt)[2]
    d.text((AX1 - tw2, AY1 - (font.getbbox('Ay')[3] - font.getbbox('Ay')[1])), amb_txt,
           fill=(160, 160, 160), font=font)
# =======================================

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

    # scrolling temp grid (no per-bar labels, just right-edge labels)
    draw_temp_grid(img, AMBIENT_DEFAULT, TEMP_MAX_DEFAULT)

    # IP in bottom white bar
    draw.text((2, 86), ip_text, fill='black', font=font)
    return img

def main():
    target_dt = 1.0 / TARGET_FPS
    next_t = time.perf_counter()

    frame_idx = 0
    ip_cache = "No IP"
    ip_next = 0.0

    # grid tick pacing
    next_tick = time.perf_counter() + TICK_S

    while True:
        now = time.perf_counter()
        if now >= ip_next:
            ip_cache = get_ip_fast()
            ip_next = now + IP_REFRESH_S

        # advance the grid one step every TICK_S
        if now >= next_tick:
            graph_tick(CURRENT_TEMP, AMBIENT_DEFAULT, TEMP_MAX_DEFAULT)
            next_tick += TICK_S

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
