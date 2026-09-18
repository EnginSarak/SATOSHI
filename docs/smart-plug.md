# Smart plug

`btc setup` walks through this interactively, offers to test the socket by
switching it off and back on, and writes the file for you. What follows is the
same thing done by hand.

Sockets differ wildly, so there are three ways to wire one up. Create
`~/.bitcoin-core-cli/plug.json` and use whichever matches your hardware.

```bash
chmod 600 ~/.bitcoin-core-cli/plug.json
```

## Type `http`: Shelly, Tasmota, ESPHome, anything with a REST endpoint

Easiest option if your socket has local HTTP control. No dependencies.

```json
{
  "name": "Miner",
  "type": "http",
  "on_url":     "http://192.168.1.60/relay/0?turn=on",
  "off_url":    "http://192.168.1.60/relay/0?turn=off",
  "status_url": "http://192.168.1.60/status"
}
```

Shelly Gen2 (Plus/Pro) uses different paths:

```json
{
  "name": "Miner",
  "type": "http",
  "on_url":     "http://192.168.1.60/rpc/Switch.Set?id=0&on=true",
  "off_url":    "http://192.168.1.60/rpc/Switch.Set?id=0&on=false",
  "status_url": "http://192.168.1.60/rpc/Switch.GetStatus?id=0"
}
```

Tasmota:

```json
{
  "name": "Miner",
  "type": "http",
  "on_url":     "http://192.168.1.60/cm?cmnd=Power%20On",
  "off_url":    "http://192.168.1.60/cm?cmnd=Power%20Off",
  "status_url": "http://192.168.1.60/cm?cmnd=Power"
}
```

`status_url` is optional. Leave it out and switching still works, you just
lose the state read-back. The parser understands the usual JSON shapes
(`ison`, `output`, `POWER`, `relay`, nested `result`) and plain `on` / `off`
text, and picks up `power` or `apower` for wattage when present.

## Type `command`: everything else

If you can switch the socket from a shell, you can switch it from here. Covers
TP-Link Kasa, Home Assistant, MQTT, `curl` with auth headers, or your own
script.

```json
{
  "name": "Miner",
  "type": "command",
  "on_cmd":     "kasa --host 192.168.1.60 on",
  "off_cmd":    "kasa --host 192.168.1.60 off",
  "status_cmd": "kasa --host 192.168.1.60 state | grep -q 'Device state: ON' && echo on || echo off"
}
```

Home Assistant over its REST API:

```json
{
  "name": "Miner",
  "type": "command",
  "on_cmd":  "curl -s -X POST -H 'Authorization: Bearer TOKEN' -H 'Content-Type: application/json' -d '{\"entity_id\":\"switch.miner\"}' http://192.168.1.10:8123/api/services/switch/turn_on",
  "off_cmd": "curl -s -X POST -H 'Authorization: Bearer TOKEN' -H 'Content-Type: application/json' -d '{\"entity_id\":\"switch.miner\"}' http://192.168.1.10:8123/api/services/switch/turn_off"
}
```

`status_cmd` should print `on` or `off` on stdout. Optional.

## Type `tuya`: the cheap no-name sockets

Most sub-€10 plugs sold under Smart Life / Tuya branding run Tuya firmware.
They can be driven locally, but only after you extract a **local key**, and
Tuya makes you walk through their developer portal once to get it. Annoying,
but one-off, and nothing touches the cloud afterwards.

```bash
python3 -m pip install tinytuya --break-system-packages
```

Then the portal:

1. Sign up at [iot.tuya.com](https://iot.tuya.com). Choose **Skip this step**
   if it asks for an account type.
2. **Cloud → Development → Create Cloud Project**. Development Method
   **Smart Home**, Data Center **whichever region your phone app account is
   registered in** (Central Europe for most of the EU). Getting this wrong is
   the number one reason the wizard finds no devices.
3. Open the project, go to **Service API**, authorize **IoT Core** and
   **Authorization Token Management**. The free tier is enough.
4. On **Overview**, copy the **Access ID** and **Access Secret**.
5. **Devices → Link Tuya App Account → Add App Account**, then scan the QR
   code with the Smart Life app (Me tab → scan icon, top right).

The console is close to unusable on a phone. Use a desktop browser.

Then on the node:

```bash
python3 -m tinytuya wizard
```

Feed it the Access ID, the Access Secret, region `eu` (or yours), and type
`scan` when it asks for a device ID. Answer yes to the DP mappings and yes to
polling local devices. It writes `devices.json` containing each socket's `id`,
`key`, `ip` and protocol `version`.

Copy those four into `~/.bitcoin-core-cli/plug.json`:

```json
{
  "name": "Miner",
  "type": "tuya",
  "id": "01234567890abcdef012",
  "key": "aBcDeFgHiJkLmNoP",
  "ip": "192.168.1.60",
  "version": "3.3"
}
```

Delete `devices.json` and `tinytuya.json` afterwards, they hold the keys to
every Tuya device on your account.

Two things worth knowing before you spend an evening on this:

- Some newer firmware speaks protocol 3.4/3.5 and refuses local control
  outright. If the wizard's local poll fails, yours is one of them. Use the
  `command` type against Tuya's cloud API, or buy a Shelly.
- Re-pairing the socket in the app **rotates the local key**. If switching
  suddenly stops working, that's why. Re-run the wizard.

## Using it

```
core@bitcoin » turn            # state, voltage, current, watts
core@bitcoin » stop mining     # cut power
core@bitcoin » start mining    # restore
```

Power readings only appear if the socket actually meters. Most Tuya and Shelly
plugs do, some don't.

---
