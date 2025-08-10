# cwcu

Custom water cooling unity software for a 128x96 OLED display.

## Overview

`cwcu.py` drives an SSD1351/SSD1331 based OLED screen over hardware SPI. The
script renders the state of several water‑cooling components, a scrolling
temperature graph, and the current IP address in real time.

## Features

- Animated 2×2 status tiles for **fans**, **probes**, **pumps**, and **flow**.
- Scrolling temperature bar chart with configurable ambient and maximum labels.
- IP address readout in a dedicated bottom bar.
- Pure Python implementation using [`Pillow`](https://pillow.readthedocs.io/)
  and [`luma.oled`](https://github.com/rm-hull/luma.oled).

## Requirements

- Python 3.8+
- `pip install pillow luma.oled luma.core`
- An SPI-capable host such as a Raspberry Pi connected to an SSD1351/SSD1331
  OLED module.

## Running

Clone the repository and run the script:

```bash
python cwcu.py
```

The program targets ~5 FPS and will continually update the display. Running
without the required hardware will raise errors from `luma.oled`.

## Dynamic state variables

The display exposes four global variables that represent the state of each
metric tile. They can be changed at runtime:

- `FANS`
- `PUMPS`
- `PROBES`
- `FLOW`

Each variable accepts:

- `0` – no signal
- `1` – ok
- `2` – warn
- `3` – bad

All variables default to `0` which indicates *no signal* for the corresponding
metric tile.

## Temperature grid

A scrolling bar chart occupies the lower half of the display. The top label
shows `TEMP_MAX_DEFAULT` (50°C by default) while the bottom label shows
`AMBIENT_DEFAULT` (20°C by default). The grid advances every `TICK_S`
seconds using a fake random walk temperature source.

## Customization

Icon frames are stored in the `pic/` directory as PNGs named
`<metric>_<frame>.png`. Replace these images or adjust constants near the top
of `cwcu.py` to tweak icon sizes, colours, refresh rates, and more.

