#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, glob, time, socket, random
from PIL import Image, ImageDraw, ImageFont, ImageChops, Image

# pip install luma.oled luma.core
from luma.core.interface.serial import spi
from luma.oled.device import ssd1351  # use ssd1331 if your board is that controller

# --- DS18B20 ambient probe ---
AMBIENT_SENSOR_ID = "28-845efb356461"  # set to '28-xxxxxxxxxxxx' to lock to a specific device, or leave None to auto-pick the first 28-*
W1_DEVICES_GLOB = "/sys/bus/w1/devices/28-*/w1_slave"

# ================== CONFIG ==================
WIDTH, HEIGHT = 128, 96
SPI_HZ = 24_000_000
SPI_PORT, SPI_DEVICE = 0, 0
GPIO_DC, GPIO_RST = 25, 24
V_OFFSET = 32
H_OFFSET = 0
BGR = False  # controller byte order flag for luma; keep your color tuples as BGR and we'll convert for PIL

ICON_W, ICON_H = 15, 15
IP_REFRESH_S = 1.0
TARGET_FPS = 5.0

# Temp grid (lower half) — scrolling bar chart
AMBIENT_DEFAULT = 20.0   # scale min (label at lower-left if no sensor yet)
TEMP_MAX_DEFAULT = 50.0  # scale max (label at upper-left)
TICK_S = 2.0             # advance one step every 2 seconds
STEP_W = 3               # 2 px bar + 1 px vertical grid
GRID_COLOR_V = (30, 30, 30)  # vertical grid line (RGB—neutral gray)
GRID_COLOR_H = (30, 30, 30)  # horizontal grid lines (RGB—neutral gray)
H_GRID_STEP = 3            # px between horizontal grid lines

# Bottom bar / ticker
BOTTOM_BAR_RECT = (1, 87, 122, 94)  # x0,y0,x1,y1 (inclusive)
BOTTOM_LABEL = "Temp."               # or "Loop"
TICKER_SPACER_PX = 24               # gap between repeats in pixels
TICKER_SPEED_PX = 1                 # pixels per frame

# Label look (left side of grid)
LABEL_FG_TOP = (230, 230, 230)
LABEL_FG_BOTTOM = (170, 170, 170)
LABEL_BG = (0, 0, 0)      # semi-transparent bg color
LABEL_ALPHA = 140         # 0..255 transparency
LABEL_PAD = (3, 1)        # x, y padding inside label box
# ============================================

# ---- dynamic state variables (top tiles) ----
# 0=no signal, 1=ok, 2=warn, 3=bad
FANS   = 1
PROBES = 0
PUMPS  = 1
FLOW   = 0

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
# Bottom bar background will be drawn each frame (since it's dynamic)

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

# ---- color gradient for bars (BGR order!) ----
# ambient -> blue, 1/3 -> green, 2/3 -> yellow, max -> red
BAR_BLUE = (255, 0, 0) # BGR: blue 
BAR_GREEN = (0, 255, 0) # BGR: green 
BAR_YELLOW = (0, 255, 255) # BGR: yellow 
BAR_RED = (0, 0, 255) # BGR: red

def bgr_to_rgb(c):  # convert for Pillow
    return (c[2], c[1], c[0])

def temp_to_color_bgr(temp, ambient=AMBIENT_DEFAULT, tmax=TEMP_MAX_DEFAULT):
    """Piecewise-linear 4-stop gradient in BGR: blue -> green -> yellow -> red."""
    if temp is None:
        return (120, 120, 120)

    # normalize to 0..1 across [ambient, tmax]
    if tmax <= ambient:
        t = 1.0
    else:
        t = max(0.0, min(1.0, (temp - ambient) / (tmax - ambient)))

    # blue -> green -> yellow -> red (correct order)
    if t <= 1/3:
        u = t / (1/3)
        c0, c1 = BAR_RED, BAR_YELLOW
    elif t <= 2/3:
        u = (t - 1/3) / (1/3)
        c0, c1 = BAR_YELLOW , BAR_GREEN
    else:
        u = (t - 2/3) / (1/3)
        c0, c1 = BAR_GREEN, BAR_BLUE

    # lerp per B,G,R channel (still BGR here)
    b = lerp(c0[0], c1[0], u)
    g = lerp(c0[1], c1[1], u)
    r = lerp(c0[2], c1[2], u)
    return (b, g, r)

def draw_h_grid_segment(draw, x0, x1, h):
    """Draw horizontal grid lines only in [x0,x1], so lines appear under new content after scroll."""
    for y in range(0, h, H_GRID_STEP):
        draw.line((x0, y, x1, y), fill=GRID_COLOR_H)

def _read_ds18b20_file(path):
    try:
        with open(path, "r") as f:
            data = f.read()
        if "YES" not in data:
            return None
        t_eq = data.strip().split("t=")[-1]
        return float(t_eq) / 1000.0
    except Exception:
        return None

def read_ambient_c():
    """Read the ambient DS18B20 in °C. Returns float or None."""
    if AMBIENT_SENSOR_ID:
        path = f"/sys/bus/w1/devices/{AMBIENT_SENSOR_ID}/w1_slave"
        return _read_ds18b20_file(path)
    # auto-pick first 28-* device
    for path in sorted(glob.glob(W1_DEVICES_GLOB)):
        c = _read_ds18b20_file(path)
        if c is not None:
            return c
    return None

def graph_tick(temp_value, ambient=AMBIENT_DEFAULT, tmax=TEMP_MAX_DEFAULT):
    """Advance the grid one step: scroll left by STEP_W, add 2px bar + 1px vertical grid at right, with horiz lines."""
    global graph_img
    w, h = graph_img.size
    # scroll left
    if STEP_W > 0:
        graph_img.paste(graph_img.crop((STEP_W, 0, w, h)), (0, 0))
        # clear rightmost STEP_W columns
        segment = Image.new("RGB", (STEP_W, h), "black")
        graph_img.paste(segment, (w - STEP_W, 0))

    draw = ImageDraw.Draw(graph_img)

    # draw horizontal grid lines in the new rightmost segment (under the bar)
    seg_x0 = w - STEP_W
    seg_x1 = w - 2  # leave last col for vertical grid
    if seg_x0 <= seg_x1:
        draw_h_grid_segment(draw, seg_x0, seg_x1, h)

    # compute bar height from ambient..tmax, bottom anchored
    if temp_value is not None and tmax > ambient:
        frac = max(0.0, min(1.0, (temp_value - ambient) / (tmax - ambient)))
    else:
        frac = 0.0
    bar_h = int(frac * (h - 1))
    y0 = (h - 1) - bar_h
    col_bgr = temp_to_color_bgr(temp_value, ambient, tmax)
    col_rgb = bgr_to_rgb(col_bgr)

    # draw 2-px bar (columns w-STEP_W .. w-STEP_W+1)
    bar_cols = max(2, STEP_W - 1)
    bx0 = w - STEP_W
    for dx in range(bar_cols):  # typically 0,1
        x = bx0 + dx
        if x <= w - 2:  # avoid last grid column
            draw.line((x, y0, x, h - 1), fill=col_rgb)

    # draw 1-px vertical grid line at far right (column w-1)
    draw.line((w - 1, 0, w - 1, h - 1), fill=GRID_COLOR_V)

def draw_label(img, text, pos_xy, fg, bg, alpha):
    """Draw text with a semi-transparent background box."""
    tx, ty = pos_xy
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad_x, pad_y = LABEL_PAD
    w, h = tw + 2 * pad_x, th + 2 * pad_y
    label = Image.new("RGBA", (w, h), (bg[0], bg[1], bg[2], alpha))
    ld = ImageDraw.Draw(label)
    ld.text((pad_x, pad_y), text, fill=fg, font=font)
    img.paste(label, (tx, ty), label)

def draw_temp_grid(img, ambient=AMBIENT_DEFAULT, tmax=TEMP_MAX_DEFAULT, current_ambient=None):
    """Paste the scrolling grid; draw only two labels on the LEFT (top=max, bottom=ambient) with translucent bg."""
    img.paste(graph_img, (AX0, AY0))
    # Top-left: max (scale)
    max_txt = f"{int(tmax)}°C"
    draw_label(img, max_txt, (AX0, AY0 + 1), LABEL_FG_TOP, LABEL_BG, LABEL_ALPHA)
    # Bottom-left: show live ambient if provided; otherwise the scale min
    shown = current_ambient if (current_ambient is not None) else ambient
    amb_txt = f"{shown:0.1f}°C"
    amb_y = AY1 - (font.getbbox('Ay')[3] - font.getbbox('Ay')[1]) - 1
    draw_label(img, amb_txt, (AX0, amb_y), LABEL_FG_BOTTOM, LABEL_BG, LABEL_ALPHA)

# ======== Bottom bar with scrolling ticker ========
def _text_width(draw, text, font):
    # robust width measure across Pillow versions
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

def draw_bottom_bar(img, label, ticker_text, offset_px):
    x0, y0, x1, y1 = BOTTOM_BAR_RECT
    bar_w = x1 - x0 + 1
    bar_h = y1 - y0 + 3

    # draw onto an off-screen buffer to clip cleanly
    bar = Image.new("RGB", (bar_w, bar_h), "black")
    bd = ImageDraw.Draw(bar)
    bd.line((0, 0, bar_w, 0), fill="white")
    # label at left
    label_y = max(0, (bar_h - (font.getbbox('Ay')[3] - font.getbbox('Ay')[1])) // 2 - 1)
    
    label_w = _text_width(bd, label, font) + 2  # include padding

    # ticker area starts after label
    ticker_x0 = label_w
    ticker_w = max(0, bar_w - ticker_x0 + 12)

    # compose ticker string and measure
    tw = _text_width(bd, ticker_text, font)

    # draw scrolling text (two copies for seamless wrap)
    x = ticker_x0 - offset_px
    y = label_y
    
    bd.rectangle((x + 20, y + 1, x1, y1), fill="black")
    
    bd.text((x - 1, y), ticker_text, fill="white", font=font)
    # secondary copy if first has scrolled enough
    if x + tw < bar_w:
        bd.text((x + tw + TICKER_SPACER_PX - 1, y), ticker_text, fill="white", font=font)

    bd.rectangle((0, label_y , label_w + 3, 8), fill="white")
    bd.text((3, label_y - 1), label, fill="black", font=font)
    # paste back to main image
    img.paste(bar, (x0, y0))

    # return updated offset modulo cycle
    cycle = tw + TICKER_SPACER_PX
    if cycle <= 0:
        return 0
    return (offset_px + TICKER_SPEED_PX) % cycle

# =======================================

# ---- fake live temp source (fallback) ----
_fake_prev = 30.0
_fake_drift = 0.0

def next_fake_temp(prev, ambient=AMBIENT_DEFAULT, tmax=TEMP_MAX_DEFAULT):
    """Random walk with slow drift and occasional small bumps."""
    global _fake_drift
    # slow drift
    _fake_drift += random.uniform(-0.02, 0.02)
    _fake_drift = max(-0.6, min(0.6, _fake_drift))
    # jitter
    val = prev + _fake_drift + random.uniform(-0.75, 0.75)
    # occasional micro-bump
    if random.random() < 0.05:
        val += random.uniform(-2.8, 2.8)
    # clamp
    val = max(ambient, min(tmax, val))
    return val

def make_frame(frame_idx, ip_text, states, current_ambient, ticker_text, ticker_offset):
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

    # scrolling temp grid + left labels
    draw_temp_grid(img, AMBIENT_DEFAULT, TEMP_MAX_DEFAULT, current_ambient)

    # bottom bar with ticker
    new_offset = draw_bottom_bar(img, BOTTOM_LABEL, ticker_text, ticker_offset)

    return img, new_offset

def main():
    target_dt = 1.0 / TARGET_FPS
    next_t = time.perf_counter()

    frame_idx = 0
    ip_cache = "No IP"
    ip_next = 0.0

    # grid tick pacing
    next_tick = time.perf_counter() + TICK_S
    global _fake_prev
    _fake_prev = 30.0

    # persistent values between frames
    current_ambient = AMBIENT_DEFAULT
    ticker_offset = 0
    last_log = "ready"
    warn_msg = ""  # set to something when needed

    while True:
        now = time.perf_counter()
        if now >= ip_next:
            ip_cache = get_ip_fast()
            ip_next = now + IP_REFRESH_S

        # advance the grid one step every TICK_S with real ambient (or fake fallback)
        if now >= next_tick:
            ambient_c = read_ambient_c()
            if ambient_c is None:
                ambient_c = next_fake_temp(_fake_prev, AMBIENT_DEFAULT, TEMP_MAX_DEFAULT)
            _fake_prev = ambient_c
            current_ambient = ambient_c
            graph_tick(ambient_c, AMBIENT_DEFAULT, TEMP_MAX_DEFAULT)
            next_tick += TICK_S

        # Compose ticker text
        # You can append last_log / warnings dynamically later.
        parts = [f"IP {ip_cache}", f"Ambient {current_ambient:0.1f}°C"]
        if last_log:
            parts.append(f"Log {last_log}")
        if warn_msg:
            parts.append(f"Warn {warn_msg}")
        ticker_text = " | ".join(parts)

        # Order matches ICON_NAMES = ["fan","probe","pump","flow"]
        states = [FANS, PROBES, PUMPS, FLOW]
        img, ticker_offset = make_frame(frame_idx, ip_cache, states, current_ambient, ticker_text, ticker_offset)
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
