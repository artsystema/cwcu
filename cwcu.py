#!/usr/bin/python
# -*- coding:utf-8 -*-

import sys
import os
import time
import socket
from PIL import Image, ImageDraw, ImageFont

# Set up Waveshare library path
libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), '../OLED_Module_Code/RaspberryPi/python/lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

from waveshare_OLED import OLED_1in27_rgb


# Function to get IP address
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Doesn't need to connect
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "No IP"


# Initialize display
disp = OLED_1in27_rgb.OLED_1in27_rgb()
disp.Init()
disp.clear()

font = ImageFont.load_default()


def draw_frame(shrink):
    """Render a single frame on the OLED display."""
    img = Image.new('RGB', (disp.width, disp.height), 'black')
    draw = ImageDraw.Draw(img)

    # Step 1: Outer white working area (124x84)
    draw.rectangle((0, 12, 123, 95), fill='white')

    # Step 2: Inner black metric area (122x72, top)
    draw.rectangle((1, 13, 122, 86), fill='black')

    # Step 3: Bottom white IP bar (122x10)
    draw.rectangle((1, 87, 122, 94), fill='white')

    # Step 4: Four metric rectangles (2x2) with animated icons and placeholder text
    h_spacing = 1
    v_spacing = 1
    metric_left, metric_top, metric_right, metric_bottom = 1, 13, 122, 86
    metric_width = metric_right - metric_left + 1
    metric_height = metric_bottom - metric_top + 1
    rect_width = (metric_width - h_spacing) // 2
    rect_height = (metric_height - v_spacing) // 2
    icon_base = rect_height - 10  # max icon size within each rectangle
    _, text_h = font.getsize("No signal")

    for i in range(4):
        row, col = divmod(i, 2)
        left = metric_left + col * (rect_width + h_spacing)
        top = metric_top + row * (rect_height + v_spacing)
        right = left + rect_width - 1
        bottom = top + rect_height - 1
        draw.rectangle((left, top, right, bottom), fill='white')

        # Animated black square icon
        size = icon_base - 4 if shrink else icon_base
        offset = (icon_base - size) // 2
        icon_x = left + 2 + offset
        icon_y = top + (rect_height - icon_base) // 2 + offset
        draw.rectangle((icon_x, icon_y, icon_x + size - 1, icon_y + size - 1), fill='black')

        # Placeholder text
        text_x = left + 2 + icon_base + 3
        text_y = top + (rect_height - text_h) // 2
        draw.text((text_x, text_y), "No signal", fill='black', font=font)

    # Step 5: Draw IP in white bar (in black text)
    ip = get_ip()
    ip_text_y = 87 + 1  # slight top padding

    draw.text((2, ip_text_y), ip, fill='black', font=font)

    disp.ShowImage(disp.getbuffer(img))


def main():
    shrink = False
    while True:
        draw_frame(shrink)
        shrink = not shrink
        time.sleep(0.5)


if __name__ == "__main__":
    main()
