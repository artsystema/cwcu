#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, glob, time, socket
from PIL import Image, ImageDraw, ImageFont, ImageChops

# pip install luma.oled luma.core
from luma.core.interface.serial import spi
from luma.oled.device import ssd1351  # use ssd1331 if your board is that controller

# ================== CONFIG ==================
WIDTH, HEIGHT = 128, 96
SPI_HZ = 24_000_000           # try 24–32 MHz if wiring is short; drop to 16 MHz if unstable
SPI_PORT, SPI_DEVICE = 0, 0   # /dev/spidev0.0
GPIO_DC, GPIO_RST = 25, 24    # change if wired differently

# For 128×96 panel on SSD1351 (128×128 RAM), shift down to the visible window:
V_OFFSET = 32                 # <-- key fix for 128×96 on 128×128 controller
H_OFFSET = 0
BGR = False                   # set True if red/blue look swapped

ICON_W, ICON_H = 16, 16
IP_REFRESH_S = 1.0
TARGET_FPS = 5.0

# Animation behavior:
# If True: when active, animate using ALL available frames (including frame 0).
# If False: when active, animate using frames 1..N-1 (frame 0 reserved as idle look).
ANIM_USES_ALL_FRAMES = True
# ============================================

# ---- dynamic state variables ----
# 0=no signal (grey), 1=ok (white), 2=warn (yellow), 3=bad (red)
FANS   = 1
PROBES = 0   # <- fixed typo (was PROPES)
PUMPS  = 1
FLOW   = 0

def multiply_paste(base_img, overlay, xy, opacity=1.0):
    """Multiply-blend `overlay` onto `base_img` at (x,y). Overlay should be RGB."""
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
    0: (50, 50, 50),     # no signal (grey)
    1: (255, 255, 255),  # ok      (white)
    2: (255, 210, 31),   # warn    (yellow)
    3: (255, 59, 48)     # bad     (red)
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

# Working area (from your spec): white 124×84 at (0,12)–(123,95)
d.rectangle((0, 12, 123, 95), fill="white")
# Inner black metric area (top) 122×72 at (1,13)–(122,86)
d.rectangle((1, 13, 122, 86), fill="black")
# White horizontal line roughly across the middle of the metric area
line_y = 13 + (72 // 2) + 5  # +5 to match your previous visual tweak
d.line((1, line_y, 122, line_y), fill="white")
# Black header strip above (cleans top)
d.rectangle((0, 0, 123, (13 + 72 // 2) + 4), fill="black")
# Bottom white IP bar
d.rectangle((1, 87, 122, 94), fill="white")

# 4 metric tiles (2×2 grid) inside the black area
spacing = 1
rect_width = (124 - spacing) // 2
rect_height = ((13 + 72 - 13) // 2) - 2  # roughly half the black area height minus a bit
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

def pick_frame(frames, frame_idx, state_active):
    if not state_active:
        return frames[0]  # idle
    if ANIM_USES_ALL_FRAMES:
        return frames[frame_idx % len(frames)]            # 0..N-1 (uses all 3)
    else:
        if len(frames) > 1:
            return frames[(frame_idx % (len(frames) - 1)) + 1]  # 1..N-1
        else:
            return frames[0]

def make_frame(frame_idx, ip_text, states):
    img = bg.copy()
    draw = ImageDraw.Draw(img)

    # states must align with ICON_NAMES order
    for idx, mb in enumerate(metric_boxes):
        state = states[idx] if idx < len(states) else 0
        color = STATE_COLORS.get(state, STATE_COLORS[0])
        draw.rectangle(mb["rect"], fill=color)

        name = ICON_NAMES[idx]
        frames = icon_frames[name]
        frame = pick_frame(frames, frame_idx, state_active=(state != 0))
        multiply_paste(img, frame, (mb["icon_x0"], mb["icon_y0"]), opacity=1.0)

        # labels
        label_top = "No" if state == 0 else (
            "OK" if state == 1 else ("Warn" if state == 2 else "Bad")
        )
        label_bot = "Signal"
        draw.text((mb["text_x"], mb["text_y"]), label_top, fill='black', font=font)
        draw.text((mb["text_x"], mb["text_y"] + 7), label_bot, fill='black', font=font)

    # IP text in bottom white bar
    draw.text((2, 88), ip_text, fill='black', font=font)
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

        # frame pacing
        next_t += target_dt
        sleep = next_t - time.perf_counter()
        if sleep > 0:
            time.sleep(sleep)
        else:
            next_t = time.perf_counter()

if __name__ == "__main__":
    main()
