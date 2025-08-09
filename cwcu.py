#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, glob, time, socket
from PIL import Image, ImageDraw, ImageFont

# pip install luma.oled luma.core
from luma.core.interface.serial import spi
from luma.oled.device import ssd1351  # use ssd1331 if your board is that controller

# ================== CONFIG ==================
WIDTH, HEIGHT = 128, 96
SPI_HZ = 24_000_000           # try 24–32 MHz if wiring is short; drop to 16 MHz if unstable
SPI_PORT, SPI_DEVICE = 0, 0   # /dev/spidev0.0
GPIO_DC, GPIO_RST = 25, 24    # change if wired differently
V_OFFSET = 32                 # <-- key fix for 128×96 on 128×128 SSD1351 RAM
H_OFFSET = 0
BGR = False                   # set True if red/blue look swapped

FAN_W, FAN_H = 16, 16
FAN_X, FAN_Y = 1, 14
IP_REFRESH_S = 1.0
TARGET_FPS = 5.0
# ============================================

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

# ---- fonts ----
font = ImageFont.load_default()

# ---- load fan frames once ----
fan_paths = sorted(glob.glob("pic/fan_*.png"))
if not fan_paths:
    raise RuntimeError("No fan frames found: pic/fan_*.png")
fan_frames = [Image.open(p).convert("RGB").resize((FAN_W, FAN_H), Image.NEAREST) for p in fan_paths]

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
text_bbox = font.getbbox("No")
text_h = text_bbox[3] - text_bbox[1]
line_gap = 1

for i in range(4):
    row = i // 2
    col = i % 2
    left = 0 + col * (rect_width + spacing) + 2 * col
    top = 12 + row * (rect_height + spacing) + 1 * row
    right = left + rect_width - 2 * col
    bottom = top + rect_height - 1
    d.rectangle((left, top, right, bottom), fill="gray")

    icon_x0 = left + 2
    icon_y0 = top + 2
    text_x = left + 2 + icon_base + 3
    text_y = top + (rect_height - (2 * text_h + line_gap)) // 2 + 2
    metric_boxes.append({
        "icon_x0": icon_x0, "icon_y0": icon_y0,
        "text_x": text_x, "text_y": text_y
    })

def make_frame(frame_idx, shrink, ip_text):
    img = bg.copy()
    draw = ImageDraw.Draw(img)

    # animate black square icons
    size = icon_base - 2 if shrink else icon_base
    offset = (icon_base - size) // 2
    for mb in metric_boxes:
        x0 = mb["icon_x0"] + offset
        y0 = mb["icon_y0"] + offset
        draw.rectangle((x0, y0, x0 + size - 1, y0 + size - 1), fill="black")
        draw.text((mb["text_x"], mb["text_y"]), "No", fill="black", font=font)
        draw.text((mb["text_x"], mb["text_y"] + 7), "Signal", fill="black", font=font)

    # fan sprite
    img.paste(fan_frames[frame_idx], (FAN_X, FAN_Y))

    # IP text in bottom white bar
    draw.text((2, 86), ip_text, fill="black", font=font)
    return img

def main():
    target_dt = 1.0 / TARGET_FPS
    next_t = time.perf_counter()

    shrink = False
    frame_idx = 0
    ip_cache = "No IP"
    ip_next = 0.0

    while True:
        now = time.perf_counter()
        if now >= ip_next:
            ip_cache = get_ip_fast()
            ip_next = now + IP_REFRESH_S

        img = make_frame(frame_idx, shrink, ip_cache)
        device.display(img)

        # advance animation
        shrink = not shrink
        frame_idx = (frame_idx + 1) % len(fan_frames)

        # frame pacing
        next_t += target_dt
        sleep = next_t - time.perf_counter()
        if sleep > 0:
            time.sleep(sleep)
        else:
            next_t = time.perf_counter()

if __name__ == "__main__":
    main()
