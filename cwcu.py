#!/usr/bin/python
# -*- coding:utf-8 -*-

import sys, glob, os, time, socket
from PIL import Image, ImageDraw, ImageFont

# Waveshare lib path
libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), '../OLED_Module_Code/RaspberryPi/python/lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

from waveshare_OLED import OLED_1in27_rgb
from waveshare_OLED import config

# ---------- utils ----------
def get_ip_fast():
    """Best-effort IP without blocking DNS. Cached by caller."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.05)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "No IP"

# ---------- init display ----------
disp = OLED_1in27_rgb.OLED_1in27_rgb()

# Set SPI speed BEFORE Init()
# Try 24000000 if your wiring is short/clean. Fall back to 16000000 if you see artifacts.
disp.spi.max_speed_hz = 24000000
print("SPI freq:", disp.spi.max_speed_hz)

disp.Init()
disp.clear()

W, H = disp.width, disp.height  # expect 128x96
font = ImageFont.load_default()

# ---------- load & prep fan frames once ----------
fan_paths = sorted(glob.glob("pic/fan_*.png"))
if not fan_paths:
    raise RuntimeError("No fan frames found in pic/fan_*.png")
# fan anim goes at (1,14); target box is roughly 122x72 top area. Use a sane size.
FAN_W, FAN_H = 20, 20  # adjust if you like
fan_frames = []
for p in fan_paths:
    im = Image.open(p).convert("RGB").resize((FAN_W, FAN_H), Image.NEAREST)
    fan_frames.append(im)

# ---------- build static background once ----------
# Everything that never changes: the white working area, black metric panel,
# separators, rectangles, and the white IP bar. We'll draw dynamic bits later.
bg = Image.new('RGB', (W, H), 'black')
bgd = ImageDraw.Draw(bg)

# Outer white working area (124x84)
bgd.rectangle((0, 12, 123, 95), fill='white')
# Inner black metric area (122x72, top)
bgd.rectangle((1, 13, 122, 86), fill='black')
# White horizontal line (middle of metric area)
line_y = 13 + (72 // 2)
line_y_upd = 18 + (72 // 2)
bgd.line((1, line_y_upd, 122, line_y_upd), fill='white')
# Black area above horizontal line
bgd.rectangle((0, 0, 123, line_y + 4), fill='black')
# Bottom white IP bar
bgd.rectangle((1, 87, 122, 94), fill='white')

# Four metric rectangles (static white boxes)
spacing = 1
rect_width = (124 - spacing) // 2
rect_height = ((line_y - 10) - spacing) // 2
text_bbox = font.getbbox("No")
text_h = text_bbox[3] - text_bbox[1]
line_gap = 1
icon_base = rect_height - 4  # max icon size

metric_boxes = []  # store geometry for fast redraw
for i in range(4):
    row = i // 2
    col = i % 2
    left = 0 + col * (rect_width + spacing) + 2 * col
    top = 12 + row * (rect_height + spacing) + 1 * row
    right = left + rect_width - 2 * col
    bottom = top + rect_height - 1
    bgd.rectangle((left, top, right, bottom), fill='white')
    # Precompute placements used each frame
    icon_x0 = left + 2
    icon_y0 = top + 2
    text_x = left + 2 + icon_base + 3
    text_y = top + (rect_height - (2 * text_h + line_gap)) // 2 + 2
    metric_boxes.append({
        "icon_x0": icon_x0, "icon_y0": icon_y0,
        "text_x": text_x, "text_y": text_y
    })

# Fan icon anchor
FAN_X, FAN_Y = 1, 14

# ---------- drawing of dynamic frame ----------
def draw_frame(frame_idx, shrink, ip_text):
    # Copy static bg (cheap, uses shared memory until modified)
    img = bg.copy()
    d = ImageDraw.Draw(img)

    # Animated black square icons in each metric box
    size = icon_base - 2 if shrink else icon_base
    offset = (icon_base - size) // 2
    for mb in metric_boxes:
        x0 = mb["icon_x0"] + offset
        y0 = mb["icon_y0"] + offset
        d.rectangle((x0, y0, x0 + size - 1, y0 + size - 1), fill='black')
        d.text((mb["text_x"], mb["text_y"]), "No", fill='black', font=font)
        d.text((mb["text_x"], mb["text_y"] + 7), "Signal", fill='black', font=font)

    # Fan frame
    img.paste(fan_frames[frame_idx], (FAN_X, FAN_Y))

    # IP text (in the white bar)
    d.text((2, 86), ip_text, fill='black', font=font)

    # Push to display
    disp.ShowImage(disp.getbuffer(img))

# ---------- main loop with solid frame pacing ----------
def main():
    target_fps = 20.0
    frame_interval = 1.0 / target_fps
    next_time = time.perf_counter()

    shrink = False
    frame_idx = 0

    ip_cache = "No IP"
    ip_next_refresh = 0.0
    ip_period = 1.0  # refresh IP text once per second

    while True:
        now = time.perf_counter()
        if now >= ip_next_refresh:
            ip_cache = get_ip_fast()
            ip_next_refresh = now + ip_period

        draw_frame(frame_idx, shrink, ip_cache)

        # advance simple anim
        shrink = not shrink
        frame_idx = (frame_idx + 1) % len(fan_frames)

        # frame pacing
        next_time += frame_interval
        sleep_time = next_time - time.perf_counter()
        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            # we're late; reset schedule to avoid spiraling
            next_time = time.perf_counter()

if __name__ == "__main__":
    main()
