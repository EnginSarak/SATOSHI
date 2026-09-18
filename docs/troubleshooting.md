# Troubleshooting

**`unknown command: chmod`**: you're inside the interactive mode, which only
knows its own commands. `exit` first, then run shell commands.

**Everything fails with a connection error**: the container name is probably
wrong. Check `docker ps` and set `BTC_CONTAINER` accordingly.

**`addr` and `wallet` fail, everything else works**: Electrs isn't reachable.
Check it's running and that `BTC_ELECTRUM_PORT` matches (50001 plain; 50002 is
usually SSL and won't work here).

**Section rules wrap onto the next line**: your console misreports its width.
Set `BTC_WIDTH` to something that fits.

**`chainstate` takes forever**: expected. `gettxoutsetinfo` walks the whole
UTXO set. Enable `coinstatsindex` in your node config to make it instant.

**`coinbase` shows no text for early blocks**: correct, not a bug. Only block
0 carries a message from Satoshi; miners started tagging blocks years later.

---

**`container '...' not found`**: the client is pointing at a container that
doesn't exist on your machine. Umbrel names it differently across versions
(`bitcoin_bitcoind_1` on older installs, `bitcoin_app_1` on newer ones). Run
`setup` and it will find the right one by itself.

**`docker needs sudo without a password`**: your user isn't in the docker
group. Either add it and log back in:

```bash
sudo usermod -aG docker $USER
```

or run Bitcoin Core directly on the host and pick `host` mode in `setup`.

**No temperature in the status line**: the machine has no readable thermal
sensor. Common outside a Raspberry Pi; everything else still works.
