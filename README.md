# Haier SmartAir2 for Home Assistant

Unofficial Home Assistant integration for **legacy Haier air conditioners** — the
ones paired with the old **SmartAir2** app (not hOn). It gives you native `climate`
entities, controlled either through the Haier cloud or directly over your LAN,
picked per device for whatever works.

> **Why this exists:** newer Haier units use the *hOn* app (well supported by
> [Andre0512/hon](https://github.com/Andre0512/hon)). Older units use *SmartAir2*,
> which hOn can't talk to. Their Wi-Fi dongles come in two flavours: some speak a
> plaintext protocol on the LAN, others encrypt it and only the cloud can reach
> them. This integration handles both.

## Features

- Native `climate` entities (target temp, HVAC mode, fan speed, on/off)
- Room-temperature sensor per unit
- **Hybrid transport, chosen per device:**
  - **Cloud** — MQTT gateway (`gw-gea-*.haieriot.net`), for encrypted-dongle units
  - **Local** — direct TCP `56800`, for plaintext-dongle units (instant, no internet)
- Fan selector with `auto / low / medium / high`, plus **quiet** (super-silent) and
  **turbo** on supported units
- Config UI: e-mail, password, region, and an optional per-device local IP mapping
- Options flow to change region / local mapping without re-adding

## Supported devices

| Generation | Example | Transport | Status |
|---|---|---|---|
| **V2** (`typeIdentifier` ≤ 32 chars) | wall units w/ encrypted dongle | Cloud | **Full** — target, mode, fan, quiet/turbo, current temp |
| **V3** (`typeIdentifier` > 32 chars) | older plaintext dongle | Local | **Experimental** — target temp & power confirmed; mode (cool/heat) and fan are best-effort, calibrated on a single unit |

If your V3 unit reports the wrong mode/fan, please open an issue with a status
frame dump — the byte layout can then be calibrated for more models.

## Installation

### HACS (recommended)

1. HACS → three-dot menu → **Custom repositories**
2. Add `https://github.com/bwitosze/haier-smartair2-cloud-for-homeassistant`, category **Integration**
3. Install **Haier SmartAir2**, then restart Home Assistant

### Manual

Copy `custom_components/haier_smartair2/` into your HA `config/custom_components/`
directory and restart.

## Configuration

Settings → Devices & Services → **Add Integration** → *Haier SmartAir2*:

- **E-mail / Password** — your SmartAir2 account
- **Region** — gateway region (only **Europe** is confirmed; US/Asia are best-guess)
- **Local devices** *(optional)* — `MAC:IP` pairs, comma-separated, for units you
  want controlled over the LAN. Example: `04FA835AE2BD:192.168.1.50`

Devices not listed under *Local devices* (or whose local port refuses a plaintext
session) fall back to cloud control automatically.

You can change region and the local mapping later via **Configure** on the
integration — no need to remove and re-add it. Note: switching a device between
cloud and local may change its `entity_id` (a `_local` suffix can appear), so
re-check any dashboard cards that reference it.

## How it works (short version)

The cloud path reproduces the uSDK gateway handshake: REST login → `master-gw`
request → MQTT 3.1 CONNECT with AES-signed credentials → device registration →
EPP frames tunnelled over MQTT. The local path wraps the same smartair2 frames in
the 80-byte LAN envelope over TCP `56800`. No app, no root, no vendor SDK binary.

## Limitations & notes

- Only **SmartAir2** accounts (`uhome.haieriot.net`, overseas platform). Not hOn,
  not the China cloud.
- The cloud access token is short-lived and refreshed automatically; a device that
  keeps its cloud link intermittently (some older dongles) is more reliable locally.
- If a locally-controlled unit flickers to *unavailable*, check that the SmartAir2
  phone app isn't holding the unit's single local connection at the same time.

## Credits

Built on top of the pioneering reverse-engineering work of **Piotr Stadnicki**
([fastfend](https://github.com/fastfend)), whose `HaierACBridge` and
`homebridge-haieracbridge-platform` first mapped the SmartAir2 cloud, and the
[ESPHome Haier](https://esphome.io/components/climate/haier/) / `paveldn/HaierProtocol`
work that documented the on-wire frame format.

## Disclaimer

This is an **unofficial** integration, not affiliated with, endorsed by, or
supported by Haier. It talks to a private API/protocol reconstructed by reverse
engineering. Use at your own risk. Names and trademarks belong to their owners.

## License

[MIT](LICENSE)
