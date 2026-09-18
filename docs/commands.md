# Commands

### Chain state

`dashboard` is the default view: height, best block hash, verification
progress, size on disk, difficulty, client version, peers, network hashrate
and mempool size on one screen. `info` goes deeper, with headers vs blocks, median
time, chainwork, pruned state. `supply` computes issuance from the halving
schedule against the 21 M cap. `halving` counts down to the next subsidy cut
with an estimated date. `retarget` forecasts the coming difficulty adjustment
from actual vs expected block times inside the current epoch, clamped to the
consensus ±4× limits. `pulse` gives the chain a heartbeat: time since the
last block, average interval over the last twelve, whether the next one is
overdue. `chainstate` walks the UTXO set for the real count of unspent
outputs and coins in existence, computed by your node rather than estimated.

### Versions and consensus

`versions` lists Bitcoin Core releases, marks the one your node is running, and
says how many are newer. `versions 31.1` fetches that version's release notes
and reflows them for the terminal, so you can read what a release actually
changes before deciding to move.

`signals` answers what soft forks are being signalled, from your own node
rather than a dashboard. It reports the deployments Bitcoin Core knows about
with their activation status, then tallies the raw version bits across recent
blocks:

```
━━ VERSION BITS SEEN IN BLOCKS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  bit 3                     2 / 144    1.4%  █  unknown deployment
```

A bit with no name is a proposal your Bitcoin Core version does not implement
meaning a fork being signalled by miners that your node has no rules for. This is how
you watch a contested proposal like BIP-110 with your own eyes instead of
taking a website's word for it. Default window is 144 blocks, roughly a day;
`signals 2016` covers a full difficulty period.

#### Changing version

The client deliberately does not upgrade or downgrade Bitcoin Core for you.

On UmbrelOS the node is an Umbrel-managed app, so swapping the binary underneath
would be undone by the next app update and can leave the app inconsistent. Use
the Umbrel app store. Downgrading is riskier still: a newer version may have
migrated your datadir into a format the older one cannot read, which can mean a
reindex measured in days on a Raspberry Pi. Read the release notes for the
version you are leaving before going backwards.

### Blocks and transactions

`tip` shows the newest block with size, transaction count, reward and the pool
that mined it. `blocks [n]` lists the last n. `block <n|hash>` and
`header <n|hash>` give the full header: merkle root, nonce, bits, previous
hash. `hash <height>` resolves a height to its hash.

Miners can write arbitrary text into the block they mine. For example the Times headline in block 0. Pools have been signing their blocks
ever since. `coinbase <n>` decodes that text out of any block and identifies
the pool from it:

```
core@bitcoin » coinbase 0

━━ EMBEDDED TEXT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  The Times 03/Jan/2009 Chancellor on brink of second bailout for banks
```

Two different places carry text in a block. `coinbase <n>` reads what the
**miner** wrote: the Times headline in block 0, pool tags like `/Foundry USA/`
today. `messages <n|hash>` reads OP_RETURN outputs, which **anyone** can pay to
put in a block:

```
core@bitcoin » messages 666666

━━ OP_RETURN OUTPUTS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Outputs found       1
  With readable text  1

  bbbbbbbbbb…bbbbbb  70 bytes
    Do not be overcome by evil, but overcome evil with good - Romans 12:21
```

Most OP_RETURN data in recent blocks is protocol data rather than text:
timestamps, token metadata, inscriptions. So the command reports how much it
found and only prints what is actually readable. Add `all` to list the rest.

`tx <txid>` decodes any transaction: inputs, outputs, total value, vsize,
confirmations, and every output with its address and script type.
`utxo <txid:n>` answers whether one specific output is still unspent.
`decode <hex>` does the same for raw hex that was never broadcast.

### Mempool and fees

`mempool` shows what's pending: count, virtual size, memory used, fees
waiting. `fees` combines Core's confirmation-target estimates with a live fee
histogram from your Electrs index.

`projection` groups the waiting mempool into the blocks it will actually
become, with the fee band each one covers:

```
MEMPOOL PROJECTION

━━ PROJECTED BLOCKS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  next block  18–42 sat/vB   1.00 MB  100%
  block +2    9–18 sat/vB    1.00 MB  100%
  block +3    3–9 sat/vB     1.00 MB  100%
  block +4    3–3 sat/vB     0.51 MB   51%

  Depth               4 blocks
  Waiting             3.5 MB
```

`peers` lists every node you're connected to with direction, ping and client
version. `net` totals bandwidth in and out since the node started.

### Addresses and wallets

`addr <address>` looks up any address against your own Electrs: confirmed and
unconfirmed balance, transaction count. No third party learns which address
you asked about.

`wallet` scans extended public keys. Give it a zpub and it derives addresses
with BIP84, walks both the receive and change chains with a gap limit of 20,
then reports the balance, every used address with its transaction count, and
every UTXO with derivation path and confirmation state. `wallet compact` drops
the per-address breakdown when you only want totals. Several wallets are
merged into one figure.

The key derivation, meaning secp256k1 point maths, BIP32 child derivation and
bech32 encoding, is implemented in the file itself. Nothing is sent anywhere and no
crypto library is needed.

### Node hardware

`system` reads the machine the node runs on: SoC temperature, CPU load,
memory, disk usage and free space. The same values sit in the status header on
every start, colour-coded, so a hot SoC or a filling disk is obvious without
reading the numbers.

### Miner and power

For a Bitaxe or anything else speaking the AxeOS API, `bitaxe` reports
hashrate with 1 m / 10 m / 1 h averages, expected vs actual, efficiency in
J/TH, ASIC and voltage-regulator temperatures, fan speed and RPM, accepted and
rejected shares, session and all-time best difficulty, and uptime.
`bitaxe full` adds core voltage, frequency, per-ASIC hashrate domains, pool
and Wi-Fi details. `bitaxe watch` refreshes it live.

`start mining` and `stop mining` cut and restore power through a smart socket,
so the miner can go off overnight without you walking over to it. `turn`
reports the socket's state and, if it meters, voltage, current, wattage and
cumulative energy. Three ways to connect one, see [smart-plug.md](smart-plug.md).

### Live modes

`watch [sec]` re-renders the dashboard on a timer. `auto [sec]` cycles through
every screen that needs no input, one after another, as an ambient display.
`all` prints those same screens once, top to bottom, when you'd rather scroll
than wait.

`scan` is a live feed of your mempool: it pulls real unconfirmed transactions,
decodes them, and prints input/output counts, value moved, fee rate and
destination while they wait. When a block lands it breaks in with height,
transaction count, pool and reward.

```
• a1b2c3d4e5…f8a9b0  2 in → 2 out  0.01990000 BTC  4.2 sat/vB  → bc1qexampl…d9f2
▸ NEW BLOCK #959,452  19:41:03  3,104 tx  Foundry USA  3.14 BTC
```

`matrix` streams raw mempool transaction IDs if you just want the wall of hex.

### Escape hatch

`rpc <method> [args]` passes anything straight to `bitcoin-cli` and
pretty-prints the JSON. If your node can answer it, you can ask it, whether or
not this client has a screen for it:

```
core@bitcoin » rpc getchaintips
core@bitcoin » rpc getblockstats 840000
```

---

---

# Usage

Two ways to drive it. From your shell:

```bash
btc                 # dashboard
btc halving
btc block 840000
btc index           # every command
```

Or interactively, where you drop the `btc` prefix:

```
$ bitcoin

core@bitcoin » halving
core@bitcoin » block 840000
core@bitcoin » exit
```

Every entry in `index` is numbered and the number alone runs it, which saves a
lot of thumb work over SSH from a phone:

```
core@bitcoin » 4        # same as: halving
```

If the `<placeholder>` notation isn't obvious, `guide` explains it and shows
exactly what to type for every command that takes an argument.

## Command reference

**Chain**: `dashboard` `info` `supply` `halving` `retarget` `node` `system`
`net` `pulse` `chainstate` `versions [x.y]` `signals [n]`

**Blocks**: `tip` `blocks [n]` `block <n|hash>` `header <n|hash>`
`hash <height>` `coinbase <n>` `messages <n|hash>` `genesis`

**Transactions**: `tx <txid>` `utxo <txid:n>` `decode <hex>`

**Network**: `mempool` `fees` `projection` `peers`

**Address**: `addr <address>` `wallet [zpub]` `wallet compact`

**Miner**: `bitaxe` `bitaxe full` `bitaxe watch` `turn` `start mining`
`stop mining`

**Extras**: `scan` `matrix` `rpc <method>` `watch [sec]` `auto [sec]` `all`
`shell` `find <x>` `whitepaper` `logo` `clear` `setup` `doctor` `update` `guide` `index`

`find <x>` takes a height, hash, txid or address and works out which lookup
you meant.

---
