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
    except:
        return "No IP"

# Initialize display
disp = OLED_1in27_rgb.OLED_1in27_rgb()
disp.Init()
disp.clear()

# Create full-screen black image
img = Image.new('RGB', (disp.width, disp.height), 'black')
draw = ImageDraw.Draw(img)

# Step 1: Outer white working area (124x84)
draw.rectangle((0, 12, 123, 95), fill='white')

# Step 2: Inner black metric area (122x72, top)
draw.rectangle((1, 13, 122, 86), fill='black')  # up to y=84

# Step 3: Bottom white IP bar (122x10)
draw.rectangle((1, 87, 122, 94), fill='white')  # 10px height

# Step 4: Text in black metric area
font = ImageFont.load_default()
text = "Please wait..."
bbox = draw.textbbox((0, 0), text, font=font)
tw = bbox[2] - bbox[0]
th = bbox[3] - bbox[1]
text_x = 1 + ((122 - tw) // 2)
text_y = 13 + ((72 - th) // 2)
draw.text((text_x, text_y), text, fill='white', font=font)

# Step 5: Draw IP in white bar (in black text)
ip = get_ip()
ip_text_y = 85 + 1  # slight top padding
draw.text((2, ip_text_y), ip, fill='black', font=font)

# Show on display
disp.ShowImage(disp.getbuffer(img))
