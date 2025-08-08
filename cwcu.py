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

    # Step 3: White horizontal line in the middle of the metric area
    line_y = 13 + (72 // 2)
    draw.line((1, line_y, 122, line_y), fill='white')

    # Step 4: Bottom white IP bar (122x10)
    draw.rectangle((1, 87, 122, 94), fill='white')

    # Step 5: Four metric rectangles with animated icons and placeholder text
    rect_height = 8
    spacing = 1
    icon_base = rect_height - 2  # max icon size
    _, text_h = font.getsize("No signal")
    for i in range(4):
        top = 13 + i * (rect_height + spacing)
        bottom = top + rect_height - 1
        draw.rectangle((1, top, 122, bottom), fill='white')

        # Animated black square icon
        size = icon_base - 2 if shrink else icon_base
        offset = (icon_base - size) // 2
        icon_x = 2 + offset
        icon_y = top + 1 + offset
        draw.rectangle((icon_x, icon_y, icon_x + size - 1, icon_y + size - 1), fill='black')

        # Placeholder text
        text_x = 2 + icon_base + 3
        text_y = top + (rect_height - text_h) // 2
        draw.text((text_x, text_y), "No signal", fill='black', font=font)

    # Step 6: Draw IP in white bar (in black text)
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
