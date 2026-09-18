# Recommended hardware

Not required to run the client. Any machine that can reach a Bitcoin Core
RPC works. This is what the maintainer's own node runs on, listed in case
you're building one from scratch.

| Part | Product | Why |
|---|---|---|
| Board | [Raspberry Pi 5, 8GB](https://www.amazon.de/dp/B0CK2FCG1K) | 4GB is enough for the node itself; 8GB gives headroom for Electrs and other apps |
| Power | [Official Raspberry Pi 5 27W USB-C Power Supply](https://www.amazon.de/dp/B0CM46P7MC) | Underpowered third-party supplies cause random reboots under load |
| Cooling | [Raspberry Pi Active Cooler](https://www.amazon.de/dp/B0CLXZBR5P) | Keeps the SoC out of thermal throttling during initial block download |
| Storage | [Crucial P3 Plus 2TB NVMe SSD](https://www.amazon.de/dp/B0BYW8FLKN) + [SSK USB 3.2 M.2 NVMe/SATA enclosure](https://www.amazon.de/dp/B07MNFH1PX) | Boots the Pi from SSD over USB 3 instead of an SD card. UmbrelOS explicitly recommends this, and it's the difference between a usable node and a slow one |

2TB comfortably fits the blockchain, an Electrs index, and Umbrel's other
apps with room to grow. The SSD connects over USB rather than the internal
M.2 PCIe slot, so no separate HAT is needed. Plug the enclosure into any of
the Pi 5's USB 3 ports and boot from it directly.

## Remote access

[Termius](https://termius.com) is a solid SSH client for iOS and Android.
Paired with a VPN back to the network the Pi is on, where Tailscale is the
simplest option, the same prompt is reachable from anywhere, not just at
home.
