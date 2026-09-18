# Configuration

`btc setup` writes all of this for you. This section is for people who'd
rather edit files, or who want to override something per-shell.

Settings live in `~/.bitcoin-core-cli/config.json`:

```json
{
  "mode": "docker",
  "container": "bitcoin_app_1",
  "electrum_host": "127.0.0.1",
  "electrum_port": 50001,
  "miner_host": "192.168.1.50"
}
```

Set `"mode": "host"` if Bitcoin Core runs directly rather than in a container;
`container` is then ignored and `bitcoin-cli` is called on the machine itself.

Environment variables override the file, which is handy for one-off tests:

```bash
export BTC_MODE=host
export BTC_CONTAINER=bitcoin_app_1
export BTC_ELECTRUM_HOST=127.0.0.1
export BTC_ELECTRUM_PORT=50001
export BITAXE_HOST=192.168.1.50
```

If your console misreports its width and the section rules wrap, pin it:

```bash
export BTC_WIDTH=55
```

## Wallets (watch-only)

`btc setup` asks for these and validates them. To do it by hand, create
`~/.bitcoin-core-cli/wallets.txt`, one wallet per line:

```
Cold    zpub6r...your-own-key-here...
Hot     zpub6q...another-key...
```

```bash
chmod 600 ~/.bitcoin-core-cli/wallets.txt
```

A zpub is watch-only and cannot spend anything. It does expose your whole
balance and address history to whoever reads it, so treat the file as
sensitive. Native segwit (`zpub`) only for now.

## Miner

`btc setup` asks for the IP and verifies the miner answers before saving it.
By hand, add `"miner_host"` to `config.json`, or export it per-shell:

```bash
export BITAXE_HOST=192.168.1.50
```

---
