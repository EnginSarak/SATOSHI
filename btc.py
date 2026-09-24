import hashlib
import hmac
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.request

VERSION = "1.0.1"
REPO = os.environ.get("BTC_REPO", "EnginSarak/SATOSHI")
BRANCH = os.environ.get("BTC_BRANCH", "main")
UPDATE_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/btc.py"
UPDATE_CHECK_INTERVAL = 86400

BTC_HOME = os.environ.get("BTC_HOME", os.path.expanduser("~/.bitcoin-core-cli"))
CONFIG_FILE = os.path.join(BTC_HOME, "config.json")
UPDATE_CACHE = os.path.join(BTC_HOME, "update-check.json")


def load_settings():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(settings):
    os.makedirs(BTC_HOME, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass


def setting(env_key, config_key, default):
    value = os.environ.get(env_key)
    if value not in (None, ""):
        return value
    value = SETTINGS.get(config_key)
    if value not in (None, ""):
        return value
    return default


SETTINGS = load_settings()

BITCOIN_MODE = setting("BTC_MODE", "mode", "docker")
BITCOIN_CONTAINER = setting("BTC_CONTAINER", "container", "bitcoin_app_1")
ELECTRUM_HOST = setting("BTC_ELECTRUM_HOST", "electrum_host", "127.0.0.1")
ELECTRUM_PORT = int(setting("BTC_ELECTRUM_PORT", "electrum_port", 50001))

WHITEPAPER_TXID = "54e48e5f5c656b26c3bca14a8c95aa583d07ebe84dde3b7dd4a78f4e4186e713"
WHITEPAPER_HEIGHT = "230009"

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ORANGE = "\033[38;5;208m"
GREEN = "\033[38;5;82m"
CYAN = "\033[38;5;45m"
GREY = "\033[38;5;245m"
WHITE = "\033[38;5;255m"
RED = "\033[38;5;196m"
YELLOW = "\033[38;5;220m"
PINK = "\033[38;5;205m"
FULLBLOCK = "\u2588"

POOLS = {
    "Foundry": "Foundry USA", "AntPool": "AntPool", "F2Pool": "F2Pool",
    "ViaBTC": "ViaBTC", "Binance": "Binance Pool", "SlushPool": "Braiins",
    "Braiins": "Braiins", "MARA": "MARA Pool", "Luxor": "Luxor",
    "SBICrypto": "SBI Crypto", "SpiderPool": "SpiderPool", "Poolin": "Poolin",
    "BTC.com": "BTC.com", "ocean.xyz": "OCEAN", "SecPool": "SecPool",
    "WhitePool": "WhitePool", "bitcoinmerge": "Bitcoin Merge",
}

_docker_prefix = None


def docker_prefix():
    global _docker_prefix
    if _docker_prefix is None:
        try:
            subprocess.run(["docker", "ps"], capture_output=True, check=True, timeout=20)
            _docker_prefix = ["docker"]
        except Exception:
            _docker_prefix = ["sudo", "-n", "docker"]
    return _docker_prefix


def core_raw(args):
    if BITCOIN_MODE == "host":
        cmd = ["bitcoin-cli"] + args
    else:
        cmd = docker_prefix() + ["exec", BITCOIN_CONTAINER, "bitcoin-cli"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise RuntimeError("the node did not answer in time")
    except FileNotFoundError:
        missing = "bitcoin-cli" if BITCOIN_MODE == "host" else "docker"
        raise RuntimeError(f"{missing} not found on this machine")
    if result.returncode != 0:
        err = result.stderr.strip() or "bitcoin-cli returned an error"
        low = err.lower()
        if "no such container" in low or "is not running" in low:
            err = (f"container '{BITCOIN_CONTAINER}' not found \u2014 "
                   f"run 'setup' to detect your node")
        elif "cannot connect to the docker daemon" in low:
            err = "the docker daemon is not reachable \u2014 is it running?"
        elif "sudo" in low and "password" in low:
            err = ("docker needs sudo without a password, or add your user to the "
                   "docker group:  sudo usermod -aG docker $USER")
        raise RuntimeError(err)
    return result.stdout.strip()


def core(args):
    out = core_raw(args)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out


def electrum(method, params=None):
    if params is None:
        params = []
    payload = json.dumps({"id": 0, "method": method, "params": params}) + "\n"
    with socket.create_connection((ELECTRUM_HOST, ELECTRUM_PORT), timeout=10) as s:
        s.sendall(payload.encode())
        buffer = b""
        while b"\n" not in buffer:
            chunk = s.recv(8192)
            if not chunk:
                break
            buffer += chunk
    data = json.loads(buffer.split(b"\n")[0].decode())
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data.get("result")


class Spinner:
    def __init__(self, text):
        self.text = text
        self.done = False
        self.thread = threading.Thread(target=self._spin)

    def _spin(self):
        frames = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
        i = 0
        while not self.done:
            sys.stdout.write(f"\r{GREEN}{frames[i % len(frames)]}{RESET} {DIM}{self.text}{RESET}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1
        sys.stdout.write("\r" + " " * (len(self.text) + 6) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        if sys.stdout.isatty():
            self.thread.start()
        return self

    def __exit__(self, *a):
        self.done = True
        if self.thread.is_alive():
            self.thread.join()


def c(text, color):
    return f"{color}{text}{RESET}"


def term_width():
    override = os.environ.get("BTC_WIDTH")
    if override and override.isdigit():
        return int(override)
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            import fcntl
            import termios
            import struct
            packed = fcntl.ioctl(stream.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
            cols = struct.unpack("HHHH", packed)[1]
            if cols > 0:
                return cols
        except Exception:
            continue
    try:
        cols = int(os.environ.get("COLUMNS", "0"))
        if cols > 0:
            return cols
    except ValueError:
        pass
    return shutil.get_terminal_size((80, 20)).columns


def section(text):
    inner = f" {text} "
    width = max(24, term_width())
    fill = "\u2501" * max(2, width - 2 - len(inner))
    return f"{ORANGE}{BOLD}\u2501\u2501{inner}{fill}{RESET}"


def row(label, value, color=WHITE):
    return f"  {CYAN}{label:<20}{RESET}{color}{value}{RESET}"


def header(text, subtitle=""):
    line = f"{ORANGE}{BOLD}{text}{RESET}"
    if subtitle:
        line += f"{GREY}   \u00b7   {subtitle}{RESET}"
    return line


def bar(pct, width=30):
    fill = int(pct / 100 * width)
    return "\u2588" * fill + "\u2591" * (width - fill)


def sats_line(sats):
    return f"{sats / 1e8:.8f} BTC   {GREY}({sats:,} sat){RESET}"


def human_duration(secs):
    days = secs / 86400
    if days >= 1:
        return f"~{days:.1f} days"
    return f"~{secs / 3600:.1f} hours"


def eta(blocks):
    secs = blocks * 600
    target = time.strftime("%Y-%m-%d", time.gmtime(time.time() + secs))
    return target, human_duration(secs)


def circulating_sats(height):
    total = 0
    subsidy = 50 * 10 ** 8
    blocks_left = height + 1
    while blocks_left > 0 and subsidy > 0:
        n = min(blocks_left, 210000)
        total += n * subsidy
        blocks_left -= n
        subsidy //= 2
    return total


def current_subsidy_sats(height):
    return (50 * 10 ** 8) >> (height // 210000)


def parse_pushes(raw):
    pushes = []
    i = 0
    while i < len(raw):
        op = raw[i]
        i += 1
        if 1 <= op <= 75:
            pushes.append(raw[i:i + op])
            i += op
        elif op == 76 and i < len(raw):
            n = raw[i]
            i += 1
            pushes.append(raw[i:i + n])
            i += n
        else:
            break
    return pushes


def extract_message(raw):
    for p in parse_pushes(raw):
        try:
            s = p.decode("ascii")
        except UnicodeDecodeError:
            continue
        if len(s) >= 10 and all(32 <= ord(ch) < 127 for ch in s):
            return s
    return ""


def coinbase_text(raw):
    runs = re.findall(rb"[\x20-\x7e]{3,}", raw)
    return " ".join(r.decode("ascii", "ignore") for r in runs).strip()


def detect_pool(text):
    for key, name in POOLS.items():
        if key.lower() in text.lower():
            return name
    return None


def block_hash_for(target):
    return core(["getblockhash", target]) if target.isdigit() else target


def coinbase_of(block_hash):
    summary = core(["getblock", block_hash, "1"])
    cb_txid = summary["tx"][0]
    try:
        cb = core(["getrawtransaction", cb_txid, "true", block_hash])
    except Exception:
        full = core(["getblock", block_hash, "2"])
        cb = full["tx"][0]
    raw = bytes.fromhex(cb["vin"][0]["coinbase"])
    reward = sum(v["value"] for v in cb["vout"])
    return summary, raw, reward


def coinbase_message(raw):
    parts = []
    for p in parse_pushes(raw):
        try:
            s = p.decode("ascii")
        except UnicodeDecodeError:
            continue
        if len(s) >= 4 and all(32 <= ord(ch) < 127 for ch in s):
            parts.append(s)
    if parts:
        return " ".join(parts)
    return coinbase_text(raw)


def cmd_dashboard(args):
    with Spinner("reading the chain from your node"):
        chain = core(["getblockchaininfo"])
        net = core(["getnetworkinfo"])
        mem = core(["getmempoolinfo"])
        mining = core(["getmininginfo"])
    version = net["subversion"].strip("/").split(":")[-1]
    print()
    print(header(f"BITCOIN CORE {version}"))
    print()
    print(section("CHAIN"))
    print(row("Network", chain["chain"], GREEN))
    print(row("Block height", f"{chain['blocks']:,}", GREEN))
    print(row("Best block", chain["bestblockhash"], YELLOW))
    print(row("Verification", f"{chain['verificationprogress'] * 100:.4f} %"))
    print(row("Size on disk", f"{chain['size_on_disk'] / 1e9:.2f} GB"))
    print(row("Difficulty", f"{chain['difficulty']:,.0f}"))
    print()
    print(section("NETWORK"))
    print(row("Client", net["subversion"].strip("/")))
    print(row("Connections", f"{net['connections']} peers", GREEN))
    print(row("Hashrate", f"{mining['networkhashps'] / 1e18:.2f} EH/s"))
    print()
    print(section("MEMPOOL"))
    print(row("Unconfirmed tx", f"{mem['size']:,}", GREEN))
    print(row("Memory used", f"{mem['usage'] / 1e6:.1f} MB"))
    print(row("Min relay fee", f"{mem['mempoolminfee'] * 1e5:.1f} sat/vB"))
    print()


def cmd_info(args):
    with Spinner("querying node"):
        chain = core(["getblockchaininfo"])
    print()
    print(header("BLOCKCHAIN INFO"))
    print()
    print(section("STATE"))
    print(row("Network", chain["chain"], GREEN))
    print(row("Blocks", f"{chain['blocks']:,}", GREEN))
    print(row("Headers", f"{chain['headers']:,}"))
    print(row("Best block", chain["bestblockhash"], YELLOW))
    print(row("Median time", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(chain["mediantime"]))))
    print(row("Difficulty", f"{chain['difficulty']:,.0f}"))
    print(row("Chainwork", chain["chainwork"], GREY))
    print(row("Size on disk", f"{chain['size_on_disk'] / 1e9:.2f} GB"))
    print(row("Pruned", str(chain.get("pruned", False))))
    print()


def cmd_supply(args):
    with Spinner("counting every coin ever issued"):
        chain = core(["getblockchaininfo"])
    height = chain["blocks"]
    issued = circulating_sats(height)
    cap = 21_000_000 * 10 ** 8
    pct = issued / cap * 100
    subsidy = current_subsidy_sats(height)
    print()
    print(header("COIN SUPPLY"))
    print()
    print(section("ISSUANCE"))
    print(row("Block height", f"{height:,}", GREEN))
    print(row("Issued", f"{issued / 1e8:,.2f} BTC", ORANGE))
    print(row("Hard cap", "21,000,000 BTC"))
    print(row("Remaining", f"{(cap - issued) / 1e8:,.2f} BTC"))
    print(row("Current reward", f"{subsidy / 1e8:.8f} BTC / block"))
    print()
    print(f"  {ORANGE}{bar(pct)}{RESET}  {GREEN}{pct:.2f} %{RESET}")
    print()


def cmd_halving(args):
    with Spinner("calculating the countdown"):
        chain = core(["getblockchaininfo"])
    height = chain["blocks"]
    epoch = height // 210000
    reward = current_subsidy_sats(height)
    next_height = (epoch + 1) * 210000
    remaining = next_height - height
    date, dur = eta(remaining)
    progress = (height % 210000) / 210000 * 100
    print()
    print(header("THE HALVING"))
    print()
    print(section("COUNTDOWN"))
    print(row("Current reward", f"{reward / 1e8:.8f} BTC", ORANGE))
    print(row("Next reward", f"{reward / 2e8:.8f} BTC", YELLOW))
    print(row("Halving at block", f"{next_height:,}", GREEN))
    print(row("Blocks remaining", f"{remaining:,}", GREEN))
    print(row("Estimated date", f"{date}  ({dur})"))
    print()
    print(f"  {ORANGE}{bar(progress)}{RESET}  {GREEN}{progress:.2f} %{RESET}  {DIM}of this epoch{RESET}")
    print()


def cmd_retarget(args):
    with Spinner("forecasting the difficulty adjustment"):
        chain = core(["getblockchaininfo"])
        height = chain["blocks"]
        into = height % 2016
        start_height = height - into
        start_hash = core(["getblockhash", str(start_height)])
        start_hdr = core(["getblockheader", start_hash])
        tip_hdr = core(["getblockheader", chain["bestblockhash"]])
    remaining = 2016 - into if into else 0
    elapsed = tip_hdr["time"] - start_hdr["time"]
    if into > 0 and elapsed > 0:
        projected = elapsed * 2016 / into
        change = (2016 * 600 / projected - 1) * 100
        change = max(-75.0, min(300.0, change))
    else:
        change = 0.0
    date, dur = eta(remaining)
    arrow = "\u25b2" if change >= 0 else "\u25bc"
    color = GREEN if change >= 0 else RED
    print()
    print(header("DIFFICULTY RETARGET"))
    print()
    print(section("FORECAST"))
    print(row("Current difficulty", f"{chain['difficulty']:,.0f}"))
    print(row("Epoch progress", f"{into} / 2016 blocks", GREEN))
    print(row("Blocks remaining", f"{remaining:,}"))
    print(row("Estimated retarget", f"{date}  ({dur})"))
    print(row("Estimated change", f"{arrow} {change:+.2f} %", color))
    print()


def cmd_node(args):
    with Spinner("reading node identity"):
        net = core(["getnetworkinfo"])
        uptime = core(["uptime"])
    print()
    print(header("NODE"))
    print()
    print(section("IDENTITY"))
    print(row("Client", net["subversion"].strip("/"), GREEN))
    print(row("Protocol", str(net["protocolversion"])))
    print(row("Connections", f"{net['connections']} ({net.get('connections_in', 0)} in / {net.get('connections_out', 0)} out)", GREEN))
    print(row("Relay fee", f"{net['relayfee'] * 1e5:.2f} sat/vB"))
    print(row("Uptime", human_duration(int(uptime))))
    print()
    print(section("REACHABLE"))
    for n in net.get("networks", []):
        state = c("yes", GREEN) if n.get("reachable") else c("no", GREY)
        print(f"  {CYAN}{n['name']:<20}{RESET}{state}")
    print()


def cmd_traffic(args):
    with Spinner("reading network totals"):
        t = core(["getnettotals"])
    print()
    print(header("NETWORK TRAFFIC"))
    print()
    print(section("BANDWIDTH"))
    print(row("Received", f"{t['totalbytesrecv'] / 1e9:.2f} GB", GREEN))
    print(row("Sent", f"{t['totalbytessent'] / 1e9:.2f} GB", GREEN))
    print()


def cmd_mempool(args):
    with Spinner("reading mempool"):
        mem = core(["getmempoolinfo"])
    print()
    print(header("MEMPOOL"))
    print()
    print(section("PENDING"))
    print(row("Transactions", f"{mem['size']:,}", GREEN))
    print(row("Virtual size", f"{mem['bytes'] / 1e6:.2f} MB"))
    print(row("Memory used", f"{mem['usage'] / 1e6:.2f} MB"))
    print(row("Total fees", f"{mem['total_fee']:.8f} BTC", ORANGE))
    print(row("Min relay fee", f"{mem['mempoolminfee'] * 1e5:.2f} sat/vB"))
    print()


def cmd_fees(args):
    print()
    print(header("FEE ESTIMATES"))
    print()
    print(section("CONFIRMATION TARGET"))
    with Spinner("estimating fees"):
        rows = []
        for blocks, label in [(1, "next block"), (3, "~30 min"), (6, "~1 hour"), (144, "~1 day")]:
            try:
                est = core(["estimatesmartfee", str(blocks)])
                rate = est.get("feerate")
                rows.append((label, f"{rate * 1e5:.1f} sat/vB" if rate else "no estimate", GREEN if rate else GREY))
            except Exception:
                rows.append((label, "no estimate", GREY))
    for label, val, color in rows:
        print(row(label, val, color))
    try:
        with Spinner("reading fee histogram"):
            hist = electrum("mempool.get_fee_histogram")
        if hist:
            print()
            print(section("MEMPOOL FEE HISTOGRAM"))
            peak = max(v for _, v in hist) or 1
            for feerate, vsize in hist[:8]:
                length = max(1, int(vsize / peak * 24))
                print(f"  {YELLOW}{feerate:6.1f}{RESET} {GREY}sat/vB{RESET}  {GREEN}{FULLBLOCK * length}{RESET}  {DIM}{vsize / 1e6:.1f} MB{RESET}")
    except Exception:
        pass
    print()


def cmd_peers(args):
    with Spinner("listing peers"):
        peers = core(["getpeerinfo"])
    print()
    print(header("CONNECTED PEERS", f"{len(peers)} total"))
    print()
    print(section("PEERS"))
    for p in peers:
        direction = "out" if not p.get("inbound") else "in "
        ping = (p.get("pingtime", 0) or 0) * 1000
        addr = p.get("addr", "?")
        sub = p.get("subver", "").strip("/")
        print(f"  {GREEN}{direction}{RESET}  {WHITE}{addr:<30}{RESET} {GREY}{ping:6.0f} ms{RESET}  {DIM}{sub}{RESET}")
    print()


def cmd_tip(args):
    with Spinner("fetching the latest block"):
        best = core(["getbestblockhash"])
        summary, raw, reward = coinbase_of(best)
    pool = detect_pool(coinbase_text(raw))
    print()
    print(header(f"LATEST BLOCK #{summary['height']:,}"))
    print()
    print(section("TIP"))
    print(row("Hash", summary["hash"], YELLOW))
    print(row("Time", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(summary["time"]))))
    print(row("Transactions", f"{summary['nTx']:,}", GREEN))
    print(row("Size", f"{summary['size'] / 1e6:.3f} MB"))
    print(row("Reward", f"{reward:.8f} BTC", ORANGE))
    print(row("Mined by", pool or "unknown", GREEN))
    print()


def cmd_blocks(args):
    count = int(args[0]) if args and args[0].isdigit() else 10
    with Spinner(f"loading the last {count} blocks"):
        chain = core(["getblockchaininfo"])
        tip = chain["blocks"]
        rows = []
        for h in range(tip, tip - count, -1):
            bh = core(["getblockhash", str(h)])
            b = core(["getblockheader", bh])
            rows.append((h, b["time"], b["nTx"]))
    print()
    print(header("RECENT BLOCKS", f"last {count}"))
    print()
    print(section("BLOCKS"))
    for h, t, ntx in rows:
        ts = time.strftime("%m-%d %H:%M", time.gmtime(t))
        print(f"  {GREEN}#{h:<9,}{RESET}{GREY}{ts}{RESET}   {WHITE}{ntx:>6,} tx{RESET}")
    print()


def cmd_block(args):
    if not args:
        print(c("  usage: btc block <height|hash>", RED))
        return
    with Spinner("fetching block"):
        h = block_hash_for(args[0])
        block = core(["getblock", h, "1"])
    print()
    print(header(f"BLOCK #{block['height']:,}"))
    print()
    print(section("HEADER"))
    print(row("Hash", block["hash"], YELLOW))
    print(row("Height", f"{block['height']:,}", GREEN))
    print(row("Time", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(block["time"]))))
    print(row("Transactions", f"{block['nTx']:,}", GREEN))
    print(row("Size", f"{block['size'] / 1e6:.3f} MB"))
    print(row("Weight", f"{block['weight']:,} WU"))
    print(row("Difficulty", f"{block['difficulty']:,.0f}"))
    print(row("Merkle root", block["merkleroot"], GREY))
    print(row("Previous", block.get("previousblockhash", "n/a"), GREY))
    print(row("Nonce", f"{block['nonce']:,}"))
    print()


def cmd_header(args):
    if not args:
        print(c("  usage: btc header <height|hash>", RED))
        return
    with Spinner("fetching header"):
        h = block_hash_for(args[0])
        hdr = core(["getblockheader", h])
    print()
    print(header(f"BLOCK HEADER #{hdr['height']:,}"))
    print()
    print(section("HEADER"))
    print(row("Hash", hdr["hash"], YELLOW))
    print(row("Version", hex(hdr["version"])))
    print(row("Time", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(hdr["time"]))))
    print(row("Bits", hdr["bits"]))
    print(row("Nonce", f"{hdr['nonce']:,}"))
    print(row("Merkle root", hdr["merkleroot"], GREY))
    print()


def cmd_hash(args):
    if not args or not args[0].isdigit():
        print(c("  usage: btc hash <height>", RED))
        return
    with Spinner("looking up block hash"):
        h = core(["getblockhash", args[0]])
    print()
    print(header(f"BLOCK HASH #{int(args[0]):,}"))
    print()
    print(f"  {YELLOW}{h}{RESET}")
    print()


def cmd_coinbase(args):
    if not args:
        print(c("  usage: btc coinbase <height|hash>", RED))
        return
    with Spinner("reading the coinbase"):
        h = block_hash_for(args[0])
        summary, raw, reward = coinbase_of(h)
    text = coinbase_message(raw)
    pool = detect_pool(coinbase_text(raw))
    print()
    print(header(f"COINBASE #{summary['height']:,}"))
    print()
    print(section("BLOCK"))
    print(row("Height", f"{summary['height']:,}", GREEN))
    print(row("Time", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(summary["time"]))))
    print(row("Reward", f"{reward:.8f} BTC", ORANGE))
    print(row("Mined by", pool or "unknown", GREEN))
    print()
    print(section("EMBEDDED TEXT"))
    print(f"  {GREEN}{text or '(no readable text)'}{RESET}")
    print()


def cmd_tx(args):
    if not args:
        print(c("  usage: btc tx <txid>", RED))
        return
    with Spinner("decoding transaction"):
        tx = core(["getrawtransaction", args[0], "true"])
    total_out = sum(v["value"] for v in tx["vout"])
    print()
    print(header("TRANSACTION"))
    print()
    print(section("SUMMARY"))
    print(row("TXID", tx["txid"], YELLOW))
    print(row("Inputs", f"{len(tx['vin'])}", GREEN))
    print(row("Outputs", f"{len(tx['vout'])}", GREEN))
    print(row("Total out", f"{total_out:.8f} BTC", ORANGE))
    print(row("Size", f"{tx['size']} bytes"))
    print(row("Virtual size", f"{tx['vsize']} vB"))
    if "confirmations" in tx:
        print(row("Confirmations", f"{tx['confirmations']:,}", GREEN))
    else:
        print(row("Status", "unconfirmed (in mempool)", YELLOW))
    print()
    print(section("OUTPUTS"))
    for i, v in enumerate(tx["vout"]):
        addr = v["scriptPubKey"].get("address", v["scriptPubKey"].get("type", "?"))
        print(f"  {GREY}#{i}{RESET}  {WHITE}{v['value']:.8f} BTC{RESET}  {CYAN}{addr}{RESET}")
    print()


def cmd_utxo(args):
    if not args:
        print(c("  usage: btc utxo <txid:n>  or  btc utxo <txid> <n>", RED))
        return
    if ":" in args[0]:
        txid, n = args[0].split(":")
    elif len(args) >= 2:
        txid, n = args[0], args[1]
    else:
        print(c("  usage: btc utxo <txid:n>", RED))
        return
    with Spinner("checking the UTXO set"):
        res = core(["gettxout", txid, n])
    print()
    print(header("UTXO CHECK"))
    print()
    if not res:
        print(section("RESULT"))
        print(f"  {RED}spent or never existed \u2014 not in the UTXO set{RESET}")
        print()
        return
    spk = res["scriptPubKey"]
    print(section("UNSPENT"))
    print(row("Status", "unspent", GREEN))
    print(row("Value", f"{res['value']:.8f} BTC", ORANGE))
    print(row("Confirmations", f"{res['confirmations']:,}", GREEN))
    print(row("Type", spk.get("type", "?")))
    print(row("Address", spk.get("address", "n/a"), YELLOW))
    print(row("Coinbase", str(res.get("coinbase", False))))
    print()


def cmd_decode(args):
    if not args:
        print(c("  usage: btc decode <raw tx hex>", RED))
        return
    raw = args[0]
    if re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        print(c("\n  that looks like a 64-char hash, not raw transaction hex.", RED))
        print(c("  \u2192 use  tx <txid>       to decode a transaction", GREY))
        print(c("  \u2192 use  coinbase <n>    to read a block's embedded message\n", GREY))
        return
    try:
        with Spinner("decoding raw transaction"):
            tx = core(["decoderawtransaction", raw])
    except Exception:
        print(c("\n  could not decode \u2014 this needs raw transaction hex, not a hash.\n", RED))
        return
    total_out = sum(v["value"] for v in tx["vout"])
    print()
    print(header("DECODED TRANSACTION"))
    print()
    print(section("SUMMARY"))
    print(row("TXID", tx["txid"], YELLOW))
    print(row("Inputs", f"{len(tx['vin'])}", GREEN))
    print(row("Outputs", f"{len(tx['vout'])}", GREEN))
    print(row("Total out", f"{total_out:.8f} BTC", ORANGE))
    print(row("Virtual size", f"{tx['vsize']} vB"))
    print()


def address_scripthash(addr):
    info = core(["validateaddress", addr])
    if not info.get("isvalid"):
        raise RuntimeError("invalid address")
    digest = hashlib.sha256(bytes.fromhex(info["scriptPubKey"])).digest()[::-1]
    return digest.hex()


def cmd_addr(args):
    if not args:
        print(c("  usage: btc addr <address>", RED))
        return
    addr = args[0]
    with Spinner("asking your local electrs"):
        sh = address_scripthash(addr)
        bal = electrum("blockchain.scripthash.get_balance", [sh])
        hist = electrum("blockchain.scripthash.get_history", [sh])
    confirmed = bal["confirmed"]
    unconfirmed = bal["unconfirmed"]
    print()
    print(header("ADDRESS"))
    print()
    print(section("BALANCE"))
    print(row("Address", addr, YELLOW))
    print(row("Confirmed", sats_line(confirmed), GREEN))
    print(row("Unconfirmed", sats_line(unconfirmed)))
    print(row("Total", sats_line(confirmed + unconfirmed), ORANGE))
    print(row("Transactions", f"{len(hist):,}", GREEN))
    print()


def cmd_genesis(args):
    with Spinner("opening block #0"):
        h = core(["getblockhash", "0"])
        block = core(["getblock", h, "2"])
    coinbase_hex = block["tx"][0]["vin"][0]["coinbase"]
    message = extract_message(bytes.fromhex(coinbase_hex))
    out0 = block["tx"][0]["vout"][0]
    spk = out0["scriptPubKey"]
    print()
    print(header("THE GENESIS BLOCK"))
    print()
    print(section("BLOCK 0"))
    print(row("Hash", h, YELLOW))
    print(row("Timestamp", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(block["time"]))))
    print(row("Confirmations", f"{block['confirmations']:,}", GREEN))
    print(row("Nonce", f"{block['nonce']:,}"))
    print(row("Merkle root", block["merkleroot"], GREY))
    print()
    print(section("SATOSHI'S HIDDEN MESSAGE"))
    print(f"  {GREEN}{BOLD}\"{message}\"{RESET}")
    print()
    print(section("50 BTC THAT CAN NEVER BE SPENT"))
    print(row("Reward", f"{out0['value']:.8f} BTC", ORANGE))
    print(row("Address", spk.get("address", "n/a"), YELLOW))
    print()


def cmd_whitepaper(args):
    out_path = args[0] if args else os.path.expanduser("~/bitcoin-whitepaper.pdf")
    with Spinner("reconstructing the whitepaper from on-chain data"):
        block_hash = core(["getblockhash", WHITEPAPER_HEIGHT])
        tx = core(["getrawtransaction", WHITEPAPER_TXID, "true", block_hash])
        data = b""
        for vout in tx["vout"]:
            asm = vout["scriptPubKey"]["asm"].split()
            if "OP_CHECKMULTISIG" in asm:
                for token in asm[1:-2]:
                    if re.fullmatch(r"[0-9a-fA-F]+", token) and len(token) >= 40:
                        data += bytes.fromhex(token)
        start = data.find(b"%PDF")
        end = data.find(b"%%EOF")
        pdf = data[start:end + 5] if start >= 0 and end >= 0 else b""
    print()
    print(header("THE BITCOIN WHITEPAPER"))
    print()
    print(section("EXTRACTION"))
    print(row("Source tx", WHITEPAPER_TXID[:32] + "\u2026", YELLOW))
    print(row("In block", f"#{int(WHITEPAPER_HEIGHT):,}", GREEN))
    if pdf.startswith(b"%PDF"):
        with open(out_path, "wb") as f:
            f.write(pdf)
        print(row("Recovered", f"{len(pdf):,} bytes", GREEN))
        print(row("Saved to", out_path, ORANGE))
        print()
    else:
        print(f"  {RED}could not reconstruct the PDF from this node{RESET}")
    print()


def _recent_hashes():
    tip = core(["getblockcount"])
    hashes = []
    for h in range(tip, max(0, tip - 20), -1):
        hashes.append(core(["getblockhash", str(h)]))
    return hashes


def cmd_matrix(args):
    shades = [GREEN, "\033[38;5;40m", "\033[38;5;28m"]
    try:
        pool = core(["getrawmempool"])
        random.shuffle(pool)
        idx = 0
        while True:
            if idx >= len(pool):
                pool = core(["getrawmempool"])
                random.shuffle(pool)
                idx = 0
            if not pool:
                for h in _recent_hashes():
                    sys.stdout.write(f"{random.choice(shades)}{h}{RESET}\n")
                    sys.stdout.flush()
                    time.sleep(0.05)
                time.sleep(1)
                continue
            sys.stdout.write(f"{random.choice(shades)}{pool[idx]}{RESET}\n")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.05)
    except KeyboardInterrupt:
        sys.stdout.write(f"\n{GREY}stream closed.{RESET}\n")


def cmd_scan(args):
    mempool_cache = []
    cache_time = 0
    cache_ttl = 15
    last_height = None
    try:
        while True:
            try:
                height = core(["getblockcount"])
            except Exception:
                height = last_height

            if height is not None and last_height is not None and height != last_height:
                try:
                    best = core(["getbestblockhash"])
                    summary, raw, reward = coinbase_of(best)
                    pool_name = detect_pool(coinbase_text(raw))
                    ts = time.strftime("%H:%M:%S", time.gmtime(summary["time"]))
                    print(
                        f"{ORANGE}{BOLD}\u25b8 NEW BLOCK{RESET} {YELLOW}#{summary['height']:,}{RESET}  "
                        f"{GREY}{ts}{RESET}  {WHITE}{summary['nTx']:,} tx{RESET}  "
                        f"{GREEN}{pool_name or 'unknown'}{RESET}  {ORANGE}{reward:.8f} BTC{RESET}"
                    )
                except Exception:
                    pass
            last_height = height if height is not None else last_height

            now = time.time()
            if now - cache_time > cache_ttl or not mempool_cache:
                try:
                    mempool_cache = core(["getrawmempool"])
                except Exception:
                    mempool_cache = []
                cache_time = now

            if mempool_cache:
                txid = random.choice(mempool_cache)
                try:
                    tx = core(["getrawtransaction", txid, "true"])
                    total_out = sum(v["value"] for v in tx["vout"])
                    n_in = len(tx["vin"])
                    n_out = len(tx["vout"])
                    first_addr = None
                    for v in tx["vout"]:
                        a = v["scriptPubKey"].get("address")
                        if a:
                            first_addr = a
                            break
                    feerate_str = ""
                    try:
                        entry = core(["getmempoolentry", txid])
                        vsize = entry.get("vsize") or tx.get("vsize") or 1
                        fee_btc = entry.get("fees", {}).get("base", 0)
                        if vsize and fee_btc:
                            feerate_str = f"{fee_btc * 1e8 / vsize:.1f} sat/vB"
                    except Exception:
                        pass
                    line = (
                        f"{GREEN}\u2022{RESET} {YELLOW}{short_id(txid)}{RESET}  "
                        f"{GREY}{n_in} in \u2192 {n_out} out{RESET}  "
                        f"{ORANGE}{total_out:.8f} BTC{RESET}"
                    )
                    if feerate_str:
                        line += f"  {CYAN}{feerate_str}{RESET}"
                    if first_addr:
                        line += f"  {GREY}\u2192 {short_id(first_addr)}{RESET}"
                    print(line)
                except Exception:
                    pass

            time.sleep(1.3)
    except KeyboardInterrupt:
        print(f"\n{GREY}scan stopped.{RESET}")


def cmd_watch(args):
    interval = int(args[0]) if args and args[0].isdigit() else 5
    try:
        while True:
            sys.stdout.write("\033[2J\033[H")
            cmd_dashboard([])
            print(f"  {DIM}{GREY}live \u00b7 refresh {interval}s \u00b7 ctrl-c to exit{RESET}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print()


AUTO_SCREENS = [
    "dashboard", "info", "supply", "halving", "retarget", "node", "net",
    "pulse", "tip", "blocks", "mempool", "fees", "projection", "peers",
]


def cmd_auto(args):
    interval = int(args[0]) if args and args[0].isdigit() else 8
    idx = 0
    try:
        while True:
            sys.stdout.write("\033[2J\033[H")
            name = AUTO_SCREENS[idx % len(AUTO_SCREENS)]
            fn = COMMANDS.get(name)
            try:
                fn([])
            except Exception as e:
                print(c(f"  \u2715 {e}", RED))
            print(f"  {DIM}{GREY}auto \u00b7 {name} \u00b7 next in {interval}s \u00b7 ctrl-c to stop{RESET}")
            time.sleep(interval)
            idx += 1
    except KeyboardInterrupt:
        print()


def cmd_all(args):
    for name in AUTO_SCREENS:
        fn = COMMANDS.get(name)
        try:
            fn([])
        except Exception as e:
            print(c(f"  \u2715 {name}: {e}", RED))


def cmd_find(args):
    if not args:
        print(c("  usage: btc find <height | block hash | txid | address>", RED))
        return
    q = args[0]
    if q.isdigit():
        cmd_block([q])
        return
    if re.fullmatch(r"[0-9a-fA-F]{64}", q):
        try:
            core(["getblockheader", q])
            cmd_block([q])
        except Exception:
            cmd_tx([q])
        return
    cmd_addr([q])


P = 2 ** 256 - 2 ** 32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G = (Gx, Gy)


def inv(a):
    return pow(a, P - 2, P)


def point_add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    x1, y1 = p
    x2, y2 = q
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p == q:
        m = (3 * x1 * x1) * inv(2 * y1) % P
    else:
        m = (y2 - y1) * inv(x2 - x1) % P
    x3 = (m * m - x1 - x2) % P
    y3 = (m * (x1 - x3) - y1) % P
    return (x3, y3)


def scalar_mul(k, p):
    r = None
    while k:
        if k & 1:
            r = point_add(r, p)
        p = point_add(p, p)
        k >>= 1
    return r


def decompress(pubkey):
    prefix = pubkey[0]
    x = int.from_bytes(pubkey[1:], "big")
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if y % 2 != (prefix & 1):
        y = P - y
    return (x, y)


def compress(point):
    x, y = point
    return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s):
    num = 0
    for ch in s:
        num = num * 58 + B58.index(ch)
    size = (num.bit_length() + 7) // 8
    full = num.to_bytes(size, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + full


def b58check_decode(s):
    raw = b58decode(s)
    data, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4] != checksum:
        raise ValueError("bad checksum")
    return data


def ripemd160(data):
    try:
        return hashlib.new("ripemd160", data).digest()
    except Exception:
        return _ripemd160(data)


def _ripemd160(message):
    def rol(x, n):
        return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF
    rl = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
          7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
          3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12,
          1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2,
          4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13]
    rr = [5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12,
          6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2,
          15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13,
          8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14,
          12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11]
    sl = [11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8,
          7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12,
          11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5,
          11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12,
          9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6]
    sr = [8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6,
          9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11,
          9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5,
          15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8,
          8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11]
    kl = [0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E]
    kr = [0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000]
    h0, h1, h2, h3, h4 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0
    msglen = len(message)
    message += b"\x80"
    while len(message) % 64 != 56:
        message += b"\x00"
    message += (msglen * 8).to_bytes(8, "little")
    for chunk in range(0, len(message), 64):
        X = [int.from_bytes(message[chunk + i * 4:chunk + i * 4 + 4], "little") for i in range(16)]
        al, bl, cl, dl, el = h0, h1, h2, h3, h4
        ar, br, cr, dr, er = h0, h1, h2, h3, h4
        for j in range(80):
            rnd = j // 16
            if rnd == 0:
                fl = bl ^ cl ^ dl
            elif rnd == 1:
                fl = (bl & cl) | (~bl & dl)
            elif rnd == 2:
                fl = (bl | ~cl) ^ dl
            elif rnd == 3:
                fl = (bl & dl) | (cl & ~dl)
            else:
                fl = bl ^ (cl | ~dl)
            t = (rol((al + fl + X[rl[j]] + kl[rnd]) & 0xFFFFFFFF, sl[j]) + el) & 0xFFFFFFFF
            al, el, dl, cl, bl = el, dl, rol(cl, 10), bl, t
            rnd2 = j // 16
            if rnd2 == 0:
                fr = br ^ (cr | ~dr)
            elif rnd2 == 1:
                fr = (br & dr) | (cr & ~dr)
            elif rnd2 == 2:
                fr = (br | ~cr) ^ dr
            elif rnd2 == 3:
                fr = (br & cr) | (~br & dr)
            else:
                fr = br ^ cr ^ dr
            t = (rol((ar + fr + X[rr[j]] + kr[rnd2]) & 0xFFFFFFFF, sr[j]) + er) & 0xFFFFFFFF
            ar, er, dr, cr, br = er, dr, rol(cr, 10), br, t
        t = (h1 + cl + dr) & 0xFFFFFFFF
        h1 = (h2 + dl + er) & 0xFFFFFFFF
        h2 = (h3 + el + ar) & 0xFFFFFFFF
        h3 = (h4 + al + br) & 0xFFFFFFFF
        h4 = (h0 + bl + cr) & 0xFFFFFFFF
        h0 = t
    return b"".join(h.to_bytes(4, "little") for h in (h0, h1, h2, h3, h4))


def hash160(data):
    return ripemd160(hashlib.sha256(data).digest())


CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def bech32_polymod(values):
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def bech32_create_checksum(hrp, data):
    values = bech32_hrp_expand(hrp) + data
    polymod = bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def bech32_encode(hrp, data):
    combined = data + bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join(CHARSET[d] for d in combined)


def convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def p2wpkh_address(pubkey, hrp="bc"):
    prog = hash160(pubkey)
    data = [0] + convertbits(prog, 8, 5)
    return bech32_encode(hrp, data)


def scripthash_for(pubkey):
    prog = hash160(pubkey)
    spk = b"\x00\x14" + prog
    return hashlib.sha256(spk).digest()[::-1].hex()


ZPUB_VERSION = bytes.fromhex("04b24746")
XPUB_VERSION = bytes.fromhex("0488b21e")


def parse_extended_key(s):
    data = b58check_decode(s)
    version = data[:4]
    chaincode = data[13:45]
    pubkey = data[45:78]
    return version, chaincode, pubkey


def ckd_pub(pubkey, chaincode, index):
    data = pubkey + index.to_bytes(4, "big")
    I = hmac.new(chaincode, data, hashlib.sha512).digest()
    IL, IR = I[:32], I[32:]
    il = int.from_bytes(IL, "big")
    if il >= N:
        raise ValueError("invalid child")
    point = point_add(scalar_mul(il, G), decompress(pubkey))
    return compress(point), IR


def derive_address(account_pub, account_cc, chain, index, hrp="bc"):
    cpub, ccc = ckd_pub(account_pub, account_cc, chain)
    leaf, _ = ckd_pub(cpub, ccc, index)
    return p2wpkh_address(leaf, hrp), scripthash_for(leaf)


WALLET_FILE = os.environ.get("BTC_WALLETS", os.path.join(BTC_HOME, "wallets.txt"))
GAP_LIMIT = 20


class ElectrumClient:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=15)
        self.buf = b""
        self.counter = 0

    def call(self, method, params):
        self.counter += 1
        req = json.dumps({"id": self.counter, "method": method, "params": params}) + "\n"
        self.sock.sendall(req.encode())
        while b"\n" not in self.buf:
            chunk = self.sock.recv(8192)
            if not chunk:
                break
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        data = json.loads(line.decode())
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data.get("result")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def load_wallets(args):
    if args:
        return [(f"Wallet {i + 1}", z) for i, z in enumerate(args)]
    if os.path.exists(WALLET_FILE):
        wallets = []
        for raw in open(WALLET_FILE, encoding="utf-8"):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            zpub = parts[-1]
            name = " ".join(parts[:-1]) or f"Wallet {len(wallets) + 1}"
            wallets.append((name, zpub))
        return wallets
    return []


def scan_wallet(client, zpub):
    version, cc, pub = parse_extended_key(zpub)
    if version != ZPUB_VERSION:
        raise RuntimeError("not a zpub (native segwit) key")
    confirmed = 0
    unconfirmed = 0
    addresses = []
    utxo_list = []
    for chain in (0, 1):
        cpub, ccc = ckd_pub(pub, cc, chain)
        empty = 0
        idx = 0
        while empty < GAP_LIMIT and idx < 2000:
            leaf, _ = ckd_pub(cpub, ccc, idx)
            addr = p2wpkh_address(leaf)
            spk = b"\x00\x14" + hash160(leaf)
            sh = hashlib.sha256(spk).digest()[::-1].hex()
            hist = client.call("blockchain.scripthash.get_history", [sh])
            if hist:
                empty = 0
                addr_balance = 0
                for u in client.call("blockchain.scripthash.listunspent", [sh]):
                    is_confirmed = u.get("height", 0) > 0
                    if is_confirmed:
                        confirmed += u["value"]
                    else:
                        unconfirmed += u["value"]
                    addr_balance += u["value"]
                    utxo_list.append({
                        "txid": u["tx_hash"],
                        "vout": u["tx_pos"],
                        "value": u["value"],
                        "confirmed": is_confirmed,
                        "height": u.get("height", 0),
                        "address": addr,
                        "path": f"{chain}/{idx}",
                    })
                addresses.append({
                    "path": f"{chain}/{idx}",
                    "address": addr,
                    "tx_count": len(hist),
                    "balance": addr_balance,
                })
            else:
                empty += 1
            idx += 1
    return {
        "confirmed": confirmed,
        "unconfirmed": unconfirmed,
        "utxos": len(utxo_list),
        "used": len(addresses),
        "addresses": addresses,
        "utxo_list": utxo_list,
    }


def short_id(s, head=10, tail=6):
    if len(s) <= head + tail + 1:
        return s
    return f"{s[:head]}\u2026{s[-tail:]}"


def cmd_wallet(args):
    compact = False
    if args and args[0].lower() == "compact":
        compact = True
        args = args[1:]
    wallets = load_wallets(args)
    if not wallets:
        print(c(f"\n  no wallets found. pass a zpub as argument, or add one per line to {WALLET_FILE}\n", RED))
        return
    results = []
    with Spinner("scanning your wallets via electrs"):
        client = ElectrumClient(ELECTRUM_HOST, ELECTRUM_PORT)
        try:
            for name, zpub in wallets:
                try:
                    results.append((name, scan_wallet(client, zpub)))
                except Exception as e:
                    results.append((name, {"error": str(e)}))
        finally:
            client.close()
    print()
    print(header("WALLET"))
    total_c = total_u = total_utxo = 0
    for name, r in results:
        print()
        print(section(name.upper()))
        if "error" in r:
            print(c(f"  {r['error']}", RED))
            continue
        bal = r["confirmed"] + r["unconfirmed"]
        print(row("Confirmed", sats_line(r["confirmed"]), GREEN))
        if r["unconfirmed"]:
            print(row("Unconfirmed", sats_line(r["unconfirmed"]), YELLOW))
        print(row("Balance", sats_line(bal), ORANGE))
        print(row("UTXOs", f"{r['utxos']:,}", GREEN))
        print(row("Addresses", f"{r['used']:,} used"))
        total_c += r["confirmed"]
        total_u += r["unconfirmed"]
        total_utxo += r["utxos"]

        if compact:
            continue

        if r["addresses"]:
            print()
            print(f"  {GREY}ADDRESSES{RESET}")
            for a in r["addresses"]:
                print(
                    f"  {CYAN}{a['path']:<7}{RESET}"
                    f"{WHITE}{a['address']:<44}{RESET}"
                    f"{GREY}{a['tx_count']:>3} tx{RESET}  "
                    f"{ORANGE}{a['balance'] / 1e8:.8f} BTC{RESET}"
                )

        if r["utxo_list"]:
            print()
            print(f"  {GREY}UTXOS{RESET}")
            for u in r["utxo_list"]:
                status = c("confirmed", GREEN) if u["confirmed"] else c("unconfirmed", YELLOW)
                print(
                    f"  {YELLOW}{short_id(u['txid'])}{RESET}{GREY}:{u['vout']}{RESET}  "
                    f"{CYAN}{u['path']:<6}{RESET}"
                    f"{ORANGE}{u['value'] / 1e8:.8f} BTC{RESET}  {status}"
                )
    print()
    print(section("TOTAL"))
    print(row("Confirmed", sats_line(total_c), GREEN))
    if total_u:
        print(row("Unconfirmed", sats_line(total_u), YELLOW))
    print(row("Balance", sats_line(total_c + total_u), ORANGE))
    print(row("UTXOs", f"{total_utxo:,}", GREEN))
    print()


BANNER = [
    ('    __    _ __             _     ', '                      '),
    ('   / /_  (_) /__________  (_)___ ', '  _________  ________ '),
    ('  / __ \\/ / __/ ___/ __ \\/ / __ \\', ' / ___/ __ \\/ ___/ _ \\'),
    (' / /_/ / / /_/ /__/ /_/ / / / / /', '/ /__/ /_/ / /  /  __/'),
    ('/_.___/_/\\__/\\___/\\____/_/_/ /_/ ', '\\___/\\____/_/   \\___/ '),
]


def read_cpu_temp():
    paths = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/devices/virtual/thermal/thermal_zone0/temp",
    ]
    for p in paths:
        try:
            with open(p) as f:
                raw = int(f.read().strip())
            return raw / 1000.0 if raw > 1000 else float(raw)
        except Exception:
            continue
    return None


def read_cpu_load():
    try:
        with open("/proc/loadavg") as f:
            load1 = float(f.read().split()[0])
        cores = os.cpu_count() or 1
        return min(100.0, load1 / cores * 100.0)
    except Exception:
        return None


def read_memory():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    info[parts[0]] = int(parts[1].strip().split()[0])
        total = info.get("MemTotal", 0) * 1024
        avail = info.get("MemAvailable", info.get("MemFree", 0)) * 1024
        used = total - avail
        return used, total
    except Exception:
        return None, None


def read_disk():
    for path in (os.path.expanduser("~"), "/"):
        try:
            usage = shutil.disk_usage(path)
            return usage.used, usage.total
        except Exception:
            continue
    return None, None


def print_status_parts(parts):
    if not parts:
        return
    sep = f"{GREY} \u00b7 {RESET}"
    width = max(20, term_width() - 2)
    line = ""
    line_len = 0
    for part in parts:
        plain_len = len(re.sub(r"\033\[[0-9;]*m", "", part))
        add = plain_len + (3 if line else 0)
        if line and line_len + add > width:
            print("  " + line)
            line = part
            line_len = plain_len
        else:
            line = line + sep + part if line else part
            line_len += add
    if line:
        print("  " + line)


def print_node_stats():
    temp = read_cpu_temp()
    load = read_cpu_load()
    mem_used, mem_total = read_memory()
    disk_used, disk_total = read_disk()

    parts = []
    if temp is not None:
        tcol = RED if temp >= 75 else (YELLOW if temp >= 65 else GREEN)
        parts.append(f"{GREY}temp{RESET} {tcol}{temp:.0f}\u00b0C{RESET}")
    if load is not None:
        lcol = RED if load >= 85 else (YELLOW if load >= 60 else GREEN)
        parts.append(f"{GREY}cpu{RESET} {lcol}{load:.0f}%{RESET}")
    if mem_total:
        pct = mem_used / mem_total * 100
        mcol = RED if pct >= 90 else (YELLOW if pct >= 75 else CYAN)
        parts.append(f"{GREY}ram{RESET} {mcol}{mem_used / 1e9:.1f}/{mem_total / 1e9:.1f} GB{RESET}")
    if disk_total:
        pct = disk_used / disk_total * 100
        dcol = RED if pct >= 90 else (YELLOW if pct >= 80 else CYAN)
        parts.append(f"{GREY}disk{RESET} {dcol}{disk_used / 1e12:.2f}/{disk_total / 1e12:.2f} TB{RESET}")

    print_status_parts(parts)


def print_chain_status():
    parts = []
    try:
        info = core(["getblockchaininfo"])
        progress = info.get("verificationprogress", 0) * 100
        height = info.get("blocks", 0)
        headers = info.get("headers", height)
        synced = progress >= 99.999 and height >= headers
        scol = GREEN if synced else YELLOW
        label = "synced" if synced else "syncing"
        parts.append(f"{GREY}chain{RESET} {scol}{label} {progress:.2f}%{RESET}")
        parts.append(f"{GREY}block{RESET} {WHITE}{height:,}{RESET}")
    except Exception:
        pass
    try:
        net = core(["getnetworkinfo"])
        conns = net.get("connections", 0)
        ccol = GREEN if conns >= 8 else (YELLOW if conns >= 3 else RED)
        parts.append(f"{GREY}peers{RESET} {ccol}{conns}{RESET}")
    except Exception:
        pass
    try:
        mp = core(["getmempoolinfo"])
        parts.append(f"{GREY}mempool{RESET} {CYAN}{mp.get('size', 0):,} tx{RESET}")
    except Exception:
        pass
    try:
        totals = core(["getnettotals"])
        down = totals.get("totalbytesrecv", 0) / 1e9
        up = totals.get("totalbytessent", 0) / 1e9
        parts.append(f"{GREY}traffic{RESET} {CYAN}\u2193{down:.1f} \u2191{up:.1f} GB{RESET}")
    except Exception:
        pass
    try:
        secs = int(core(["uptime"]))
        d, rem = divmod(secs, 86400)
        h, _ = divmod(rem, 3600)
        up_str = f"{d}d {h}h" if d else f"{h}h"
        parts.append(f"{GREY}up{RESET} {WHITE}{up_str}{RESET}")
    except Exception:
        pass
    print_status_parts(parts)


def cmd_nodestats(args):
    temp = read_cpu_temp()
    load = read_cpu_load()
    mem_used, mem_total = read_memory()
    disk_used, disk_total = read_disk()
    print()
    print(header("NODE"))
    print()
    print(section("SYSTEM"))
    if temp is not None:
        tcol = RED if temp >= 75 else (YELLOW if temp >= 65 else GREEN)
        print(row("Temperature", f"{temp:.1f} \u00b0C", tcol))
    if load is not None:
        lcol = RED if load >= 85 else (YELLOW if load >= 60 else GREEN)
        print(row("CPU load", f"{load:.0f} %", lcol))
    if mem_total:
        pct = mem_used / mem_total * 100
        print(row("Memory", f"{mem_used / 1e9:.2f} / {mem_total / 1e9:.2f} GB  ({pct:.0f} %)", CYAN))
    if disk_total:
        pct = disk_used / disk_total * 100
        free = disk_total - disk_used
        print(row("Storage", f"{disk_used / 1e12:.2f} / {disk_total / 1e12:.2f} TB  ({pct:.0f} %)", CYAN))
        print(row("Free", f"{free / 1e12:.2f} TB"))
    print(row("Cores", f"{os.cpu_count()}"))
    print()


IN_SHELL = False


def print_banner():
    for bitcoin_seg, core_seg in BANNER:
        print(f"{ORANGE}{BOLD}{bitcoin_seg}{RESET} {GREEN}{BOLD}{core_seg}{RESET}")


def cmd_logo(args):
    print()
    print_banner()
    print()


def print_shell_header():
    print()
    print_banner()
    try:
        net = core(["getnetworkinfo"])
        version = net["subversion"].strip("/").split(":")[-1]
        print(f"  {GREY}bitcoin core {version}{RESET}")
    except Exception:
        pass
    try:
        print_node_stats()
    except Exception:
        pass
    try:
        print_chain_status()
    except Exception:
        pass
    try:
        newer = update_notice()
    except Exception:
        newer = None
    if newer:
        print(f"  {GREEN}update available{RESET} {GREY}\u2014 {VERSION} \u2192 {newer}, type{RESET} "
              f"{GREEN}update{RESET}{GREY} to install{RESET}")
    print(f"  {DIM}{GREY}index for commands \u00b7 exit to leave{RESET}\n")


def cmd_clear(args):
    sys.stdout.write("\033[2J\033[H")
    print_shell_header()


def cmd_shell(args):
    global IN_SHELL
    print_shell_header()
    IN_SHELL = True
    try:
        background_update_check()
    except Exception:
        pass
    if not os.path.exists(CONFIG_FILE):
        print(f"  {YELLOW}first run{RESET} {GREY}\u2014 type{RESET} {GREEN}setup{RESET} "
              f"{GREY}to connect your node, or just start typing{RESET}\n")
    else:
        try:
            cmd_all([])
        except Exception:
            pass
    try:
        while True:
            try:
                line = input(f"{GREEN}core{WHITE}@{ORANGE}bitcoin{RESET} {GREY}\u00bb{RESET} ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            line = line.strip()
            if not line:
                continue
            if line.isdigit():
                key = NUMBERED_COMMANDS.get(int(line))
                if key is None:
                    print(c(f"  no command at number {line}", RED))
                    continue
                handler = COMMANDS[key]
                try:
                    handler([])
                except Exception as e:
                    print(c(f"\n  \u2715 {e}\n", RED))
                continue
            parts = line.split()
            name = parts[0].lower()
            if name in ("exit", "quit", "q"):
                break
            handler = COMMANDS.get(name)
            if handler is None or handler is cmd_shell:
                print(c(f"  unknown command: {name}", RED))
                continue
            try:
                handler(parts[1:])
            except Exception as e:
                print(c(f"\n  \u2715 {e}\n", RED))
    finally:
        IN_SHELL = False


def render_json(obj, indent=0):
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = list(obj.items())
        lines = ["{"]
        for i, (k, v) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            lines.append(f"{pad}  {CYAN}\"{k}\"{RESET}: {render_json(v, indent + 1)}{comma}")
        lines.append(pad + "}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return "[]"
        lines = ["["]
        for i, v in enumerate(obj):
            comma = "," if i < len(obj) - 1 else ""
            lines.append(f"{pad}  {render_json(v, indent + 1)}{comma}")
        lines.append(pad + "]")
        return "\n".join(lines)
    if isinstance(obj, bool):
        return f"{ORANGE}{str(obj).lower()}{RESET}"
    if obj is None:
        return f"{ORANGE}null{RESET}"
    if isinstance(obj, str):
        return f"{GREEN}\"{obj}\"{RESET}"
    return f"{YELLOW}{obj}{RESET}"


def cmd_rpc(args):
    if not args:
        print(c("  usage: btc rpc <method> [args...]   e.g. rpc getchaintips", RED))
        return
    with Spinner(f"calling {args[0]}"):
        result = core(list(args))
    print()
    print(header(f"RPC \u00b7 {args[0]}"))
    print()
    if isinstance(result, (dict, list)):
        rendered = render_json(result)
    else:
        rendered = f"{WHITE}{result}{RESET}"
    lines = rendered.split("\n")
    limit = 200
    for line in lines[:limit]:
        print("  " + line)
    if len(lines) > limit:
        print(c(f"  \u2026 {len(lines) - limit} more lines", GREY))
    print()


def cmd_projection(args):
    with Spinner("reading the mempool"):
        hist = electrum("mempool.get_fee_histogram")
    if not hist:
        print(c("\n  mempool is empty\n", RED))
        return
    block_vbytes = 1_000_000
    blocks = []
    cur_vsize = 0
    cur_min = None
    cur_max = None
    total_vsize = 0
    for feerate, vsize in hist:
        total_vsize += vsize
        remaining = vsize
        while remaining > 0:
            space = block_vbytes - cur_vsize
            take = min(space, remaining)
            cur_vsize += take
            remaining -= take
            cur_min = feerate if cur_min is None else min(cur_min, feerate)
            cur_max = feerate if cur_max is None else max(cur_max, feerate)
            if cur_vsize >= block_vbytes:
                blocks.append((cur_max, cur_min, cur_vsize))
                cur_vsize = 0
                cur_min = None
                cur_max = None
    if cur_vsize > 0:
        blocks.append((cur_max, cur_min, cur_vsize))
    print()
    print(header("MEMPOOL PROJECTION"))
    print()
    print(section("PROJECTED BLOCKS"))
    for i, (hi, lo, vs) in enumerate(blocks[:10]):
        label = "next block" if i == 0 else f"block +{i + 1}"
        fill = vs / block_vbytes * 100
        print(
            f"  {CYAN}{label:<12}{RESET}"
            f"{YELLOW}{lo:.0f}\u2013{hi:.0f}{RESET} {GREY}sat/vB{RESET}   "
            f"{ORANGE}{vs / 1e6:.2f} MB{RESET}  {DIM}{GREY}{fill:.0f}%{RESET}"
        )
    print()
    print(row("Depth", f"{len(blocks)} blocks", GREEN))
    print(row("Waiting", f"{total_vsize / 1e6:.1f} MB", ORANGE))
    print()


def cmd_pulse(args):
    n = 12
    with Spinner("measuring block intervals"):
        h = core(["getbestblockhash"])
        times = []
        height = None
        for _ in range(n + 1):
            hdr = core(["getblockheader", h])
            if height is None:
                height = hdr["height"]
            times.append(hdr["time"])
            prev = hdr.get("previousblockhash")
            if not prev:
                break
            h = prev
    now = time.time()
    since = now - times[0]
    intervals = [times[i] - times[i + 1] for i in range(len(times) - 1)]
    avg = sum(intervals) / len(intervals) if intervals else 600
    expected = time.strftime("%H:%M", time.localtime(times[0] + avg))
    overdue = since > avg
    print()
    print(header("CHAIN PULSE"))
    print()
    print(section("BLOCK TIMING"))
    print(row("Tip height", f"{height:,}", GREEN))
    print(row("Last block", f"{human_since(since)} ago", YELLOW if overdue else WHITE))
    print(row("Average interval", f"{avg / 60:.1f} min", WHITE))
    print(row("Expected next", f"~{expected}" + (f"  {RED}(overdue){RESET}" if overdue else "")))
    print()


def human_since(secs):
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs // 3600}h {(secs % 3600) // 60}m"


def cmd_chainstate(args):
    with Spinner("scanning the entire UTXO set (this can take a while)"):
        info = core(["gettxoutsetinfo"])
    print()
    print(header("UTXO SET"))
    print()
    print(section("CHAINSTATE"))
    print(row("Block height", f"{info['height']:,}", GREEN))
    print(row("UTXOs", f"{info['txouts']:,}", GREEN))
    if "transactions" in info:
        print(row("Tx with UTXOs", f"{info['transactions']:,}"))
    print(row("Coins in existence", f"{info['total_amount']:,.8f} BTC", ORANGE))
    if "disk_size" in info:
        print(row("Chainstate size", f"{info['disk_size'] / 1e9:.2f} GB"))
    print(row("Best block", info["bestblock"], YELLOW))
    print()


def cmd_guide(args):
    print()
    print(header("GUIDE"))
    print()
    print(section("HOW TO READ THE COMMANDS"))
    print(f"  {YELLOW}<value>{RESET}   {GREY}a placeholder \u2014 replace it, do NOT type the < > brackets{RESET}")
    print(f"  {YELLOW}[value]{RESET}   {GREY}optional \u2014 you can leave it out{RESET}")
    print(f"  {YELLOW}a | b{RESET}     {GREY}either option works{RESET}")
    print()
    print(f"  {CYAN}n{RESET}         {GREY}a block height (a number){RESET}       {DIM}800000{RESET}")
    print(f"  {CYAN}hash{RESET}      {GREY}a 64-character block hash{RESET}      {DIM}00000000839a...{RESET}")
    print(f"  {CYAN}txid{RESET}      {GREY}a transaction id (64 chars){RESET}    {DIM}4a5e1e4baab8...{RESET}")
    print(f"  {CYAN}address{RESET}   {GREY}a bitcoin address{RESET}             {DIM}bc1qar0srrr7x...{RESET}")
    print(f"  {CYAN}zpub{RESET}      {GREY}an extended public key{RESET}        {DIM}zpub6rFR7y4Q2...{RESET}")
    print(f"  {CYAN}method{RESET}    {GREY}any bitcoin-cli command name{RESET}   {DIM}getchaintips{RESET}")
    print()
    print(f"  {DIM}{GREY}so \"block <n|hash>\" means: type either  block 170  or  block 00000000...{RESET}")
    print()
    print(section("COMMANDS THAT NEED SOMETHING TYPED"))
    entries = [
        ("blocks [n]", "list the last n blocks", "blocks 20"),
        ("block <n|hash>", "full details of one block", "block 170"),
        ("header <n|hash>", "just the block header", "header 800000"),
        ("hash <n>", "get the hash of a block height", "hash 210000"),
        ("coinbase <n|hash>", "the message + miner of a block", "coinbase 0"),
        ("tx <txid>", "decode a transaction", "tx 4a5e1e4baab8"),
        ("utxo <txid:n>", "is an output still unspent", "utxo 4a5e1e:0"),
        ("decode <hex>", "decode raw transaction hex", "decode 0100000001..."),
        ("addr <address>", "balance of an address", "addr bc1qar0srrr7x"),
        ("wallet [zpub]", "scan a wallet (or saved ones)", "wallet zpub6rFR7"),
        ("find <x>", "auto-detects height, hash, txid or address", "find 170"),
        ("rpc <method>", "call any node command directly", "rpc getchaintips"),
        ("watch [sec]", "live dashboard, refresh every n sec", "watch 10"),
        ("auto [sec]", "cycle all screens, n sec each", "auto 5"),
    ]
    for cmd_disp, desc, example in entries:
        print(f"  {GREEN}{cmd_disp:<20}{RESET}{GREY}{desc}{RESET}")
        print(f"  {' ':<20}{DIM}{CYAN}type:{RESET} {DIM}{example}{RESET}")
    print()
    print(section("EVERYTHING ELSE"))
    print(f"  {GREY}These need no input \u2014 just type the name:{RESET}")
    print(f"  {DIM}dashboard  info  supply  halving  retarget  node  net  pulse{RESET}")
    print(f"  {DIM}chainstate  tip  genesis  mempool  fees  projection  peers{RESET}")
    print(f"  {DIM}whitepaper  matrix  scan  logo  help  guide{RESET}")
    print()


BITAXE_HOST = str(setting("BITAXE_HOST", "miner_host", "")).strip()


def bitaxe_info():
    url = f"http://{BITAXE_HOST}/api/system/info"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read().decode())


def bitaxe_fetch():
    if not BITAXE_HOST:
        print(c("\n  no miner configured", RED))
        print(c("  set its address first:  export BITAXE_HOST=<ip>", GREY))
        print(c("  add that line to ~/.bashrc to make it permanent\n", GREY))
        return None
    try:
        with Spinner(f"reaching miner at {BITAXE_HOST}"):
            return bitaxe_info()
    except Exception:
        print(c(f"\n  could not reach miner at {BITAXE_HOST}", RED))
        print(c("  set a different address with:  export BITAXE_HOST=<ip>\n", GREY))
        return None


def fmt_hashrate(ghs):
    if ghs is None:
        return "n/a"
    if ghs >= 1000:
        return f"{ghs / 1000:.2f} TH/s"
    return f"{ghs:.1f} GH/s"


def fmt_diff(d):
    if d is None:
        return "n/a"
    if isinstance(d, str):
        return d
    for suffix, div in [("T", 1e12), ("G", 1e9), ("M", 1e6), ("K", 1e3)]:
        if d >= div:
            return f"{d / div:.2f}{suffix}"
    return f"{d:.0f}"


def fmt_uptime(secs):
    secs = int(secs)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def bitaxe_efficiency(info):
    power = info.get("power")
    hr = info.get("hashRate")
    if not power or not hr:
        return None
    return power * 1000 / hr


def render_bitaxe_compact(info):
    print()
    print(header("BITAXE", info.get("hostname", "")))
    print()
    print(section("MINER"))
    print(row("Model", f"{info.get('ASICModel', '?')} \u00b7 board {info.get('boardVersion', '?')}", GREEN))
    print(row("Hashrate", fmt_hashrate(info.get("hashRate")), GREEN))
    print(row("Expected", fmt_hashrate(info.get("expectedHashrate"))))
    eff = bitaxe_efficiency(info)
    print(row("Efficiency", f"{eff:.2f} J/TH" if eff else "n/a"))
    temp = info.get("temp")
    print(row("ASIC temp", f"{temp:.1f} \u00b0C" if temp is not None else "n/a",
              RED if (temp or 0) >= 70 else WHITE))
    print(row("VR temp", f"{info.get('vrTemp')} \u00b0C" if info.get("vrTemp") is not None else "n/a"))
    power = info.get("power")
    print(row("Power", f"{power:.1f} W" if power is not None else "n/a", ORANGE))
    fs = info.get("fanspeed")
    print(row("Fan", f"{fs:.0f}% \u00b7 {info.get('fanrpm', 0):,} rpm" if fs is not None else "n/a"))
    print(row("Shares", f"{info.get('sharesAccepted', 0):,} accepted / {info.get('sharesRejected', 0)} rejected", GREEN))
    print(row("Best diff", f"{fmt_diff(info.get('bestSessionDiff'))} session \u00b7 {fmt_diff(info.get('bestDiff'))} all-time", YELLOW))
    print(row("Uptime", fmt_uptime(info.get("uptimeSeconds", 0))))
    print()


def cmd_bitaxe(args):
    if args:
        sub = args[0].lower()
        if sub == "full":
            return bitaxe_full(args[1:])
        if sub == "watch":
            return bitaxe_watch(args[1:])
    info = bitaxe_fetch()
    if info is None:
        return
    render_bitaxe_compact(info)


def bitaxe_full(args):
    info = bitaxe_fetch()
    if info is None:
        return
    print()
    print(header("BITAXE", info.get("hostname", "")))
    print()
    print(section("HARDWARE"))
    print(row("ASIC", info.get("ASICModel", "?"), GREEN))
    print(row("Board version", info.get("boardVersion", "?")))
    print(row("Firmware", info.get("axeOSVersion", info.get("version", "?"))))
    print(row("Hostname", info.get("hostname", "?")))
    print(row("IP", info.get("ipv4", "?"), YELLOW))
    print(row("Display", info.get("display", "?")))
    print()
    print(section("HASHRATE"))
    print(row("Current", fmt_hashrate(info.get("hashRate")), GREEN))
    print(row("1 minute", fmt_hashrate(info.get("hashRate_1m"))))
    print(row("10 minutes", fmt_hashrate(info.get("hashRate_10m"))))
    print(row("1 hour", fmt_hashrate(info.get("hashRate_1h"))))
    print(row("Expected", fmt_hashrate(info.get("expectedHashrate"))))
    ep = info.get("errorPercentage")
    print(row("Error", f"{ep:.2f} %" if ep is not None else "n/a"))
    monitor = info.get("hashrateMonitor", {})
    asics = monitor.get("asics", []) if isinstance(monitor, dict) else []
    if asics and asics[0].get("domains"):
        doms = asics[0]["domains"]
        print(row("Domains", "  ".join(f"{d:.0f}" for d in doms) + "  GH/s", CYAN))
    print()
    print(section("HEAT"))
    temp = info.get("temp")
    print(row("ASIC temp", f"{temp:.1f} \u00b0C" if temp is not None else "n/a",
              RED if (temp or 0) >= 70 else GREEN))
    print(row("VR temp", f"{info.get('vrTemp')} \u00b0C" if info.get("vrTemp") is not None else "n/a"))
    print(row("Target temp", f"{info.get('temptarget', '?')} \u00b0C"))
    print()
    print(section("POWER"))
    power = info.get("power")
    print(row("Power", f"{power:.2f} W" if power is not None else "n/a", ORANGE))
    print(row("Max power", f"{info.get('maxPower', '?')} W"))
    v = info.get("voltage")
    print(row("Input voltage", f"{v / 1000:.2f} V" if v is not None else "n/a"))
    cur = info.get("current")
    print(row("Current", f"{cur / 1000:.2f} A" if cur is not None else "n/a"))
    print(row("Core voltage", f"{info.get('coreVoltageActual', '?')} mV measured \u00b7 {info.get('coreVoltage', '?')} mV set"))
    print(row("Frequency", f"{info.get('frequency', '?')} MHz"))
    eff = bitaxe_efficiency(info)
    print(row("Efficiency", f"{eff:.2f} J/TH" if eff else "n/a"))
    print()
    print(section("FAN"))
    fs = info.get("fanspeed")
    print(row("Speed", f"{fs:.1f} %" if fs is not None else "n/a", GREEN))
    print(row("RPM", f"{info.get('fanrpm', 0):,}"))
    print(row("Mode", "automatic" if info.get("autofanspeed") else "manual"))
    print()
    print(section("SHARES"))
    print(row("Accepted", f"{info.get('sharesAccepted', 0):,}", GREEN))
    print(row("Rejected", f"{info.get('sharesRejected', 0):,}"))
    print(row("Session best", fmt_diff(info.get("bestSessionDiff")), YELLOW))
    print(row("All-time best", fmt_diff(info.get("bestDiff")), YELLOW))
    print(row("Pool difficulty", f"{info.get('poolDifficulty', '?')}"))
    print()
    print(section("POOL"))
    print(row("URL", f"{info.get('stratumURL', '?')}:{info.get('stratumPort', '?')}", GREEN))
    print(row("User", info.get("stratumUser", "?")))
    print()
    print(section("NETWORK"))
    print(row("Wi-Fi", info.get("ssid", "?")))
    print(row("Signal", f"{info.get('wifiRSSI', '?')} dBm"))
    print(row("Status", info.get("wifiStatus", "?"), GREEN))
    print(row("Uptime", fmt_uptime(info.get("uptimeSeconds", 0))))
    print()
    print(section("CHAIN (as seen by the miner)"))
    print(row("Block height", f"{info.get('blockHeight', '?'):,}" if isinstance(info.get("blockHeight"), int) else "?", GREEN))
    nd = info.get("networkDifficulty")
    print(row("Network difficulty", fmt_diff(nd) if nd else "n/a"))
    print()


def bitaxe_watch(args):
    interval = int(args[0]) if args and args[0].isdigit() else 5
    try:
        while True:
            info = None
            try:
                info = bitaxe_info()
            except Exception:
                pass
            sys.stdout.write("\033[2J\033[H")
            if info is None:
                print(c(f"\n  could not reach miner at {BITAXE_HOST or '(not configured)'}\n", RED))
            else:
                render_bitaxe_compact(info)
            print(f"  {DIM}{GREY}live \u00b7 refresh {interval}s \u00b7 ctrl-c to exit{RESET}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print()


def cmd_bitaxe_full(args):
    bitaxe_full(list(args))


def cmd_bitaxe_watch(args):
    bitaxe_watch(list(args))


try:
    import tinytuya
except ImportError:
    tinytuya = None

PLUG_CONFIG_FILE = os.environ.get("BTC_PLUG_CONFIG", os.path.join(BTC_HOME, "plug.json"))


def load_plug_config():
    if not os.path.exists(PLUG_CONFIG_FILE):
        return None
    with open(PLUG_CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def _tuya_device(cfg):
    if tinytuya is None:
        raise RuntimeError(
            "tinytuya is not installed \u2014 run: python3 -m pip install tinytuya --break-system-packages"
        )
    for field in ("id", "ip", "key"):
        if not cfg.get(field):
            raise RuntimeError(f"plug config is missing '{field}'")
    d = tinytuya.OutletDevice(cfg["id"], cfg["ip"], cfg["key"], version=float(cfg.get("version", 3.3)))
    d.set_socketPersistent(True)
    return d


def _http_call(url, timeout=8):
    req = urllib.request.Request(url, headers={"Accept": "*/*", "User-Agent": "bitcoin-core-cli"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(errors="replace")


def _run_command(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result.stdout.strip()


def plug_switch(cfg, state):
    kind = cfg.get("type", "tuya").lower()
    if kind == "tuya":
        d = _tuya_device(cfg)
        try:
            result = d.turn_on() if state else d.turn_off()
            if isinstance(result, dict) and result.get("Error"):
                raise RuntimeError(result["Error"])
        finally:
            try:
                d.close()
            except Exception:
                pass
        return
    if kind == "http":
        url = cfg.get("on_url" if state else "off_url")
        if not url:
            raise RuntimeError(f"plug config is missing '{'on_url' if state else 'off_url'}'")
        _http_call(url)
        return
    if kind == "command":
        cmd = cfg.get("on_cmd" if state else "off_cmd")
        if not cmd:
            raise RuntimeError(f"plug config is missing '{'on_cmd' if state else 'off_cmd'}'")
        _run_command(cmd)
        return
    raise RuntimeError(f"unknown plug type '{kind}' \u2014 use tuya, http or command")


def plug_status(cfg):
    kind = cfg.get("type", "tuya").lower()
    if kind == "tuya":
        d = _tuya_device(cfg)
        try:
            status = d.status()
            if isinstance(status, dict) and status.get("Error"):
                raise RuntimeError(status["Error"])
        finally:
            try:
                d.close()
            except Exception:
                pass
        dps = status.get("dps", {})
        return {
            "on": bool(dps.get("1", False)),
            "voltage": dps.get("20") / 10 if dps.get("20") is not None else None,
            "current": dps.get("18") / 1000 if dps.get("18") is not None else None,
            "power": dps.get("19") / 10 if dps.get("19") is not None else None,
            "energy": dps.get("17") / 1000 if dps.get("17") is not None else None,
        }
    if kind == "http":
        url = cfg.get("status_url")
        if not url:
            return None
        raw = _http_call(url)
        try:
            data = json.loads(raw)
        except ValueError:
            low = raw.strip().lower()
            return {"on": low in ("on", "1", "true")}
        return {"on": _guess_on(data), "power": _guess_number(data, ("power", "apower", "watts"))}
    if kind == "command":
        cmd = cfg.get("status_cmd")
        if not cmd:
            return None
        out = _run_command(cmd).strip().lower()
        return {"on": out in ("on", "1", "true", "yes")}
    raise RuntimeError(f"unknown plug type '{kind}' \u2014 use tuya, http or command")


def _guess_on(data):
    if isinstance(data, dict):
        for key in ("ison", "output", "on", "state", "POWER", "relay"):
            if key in data:
                val = data[key]
                if isinstance(val, bool):
                    return val
                if isinstance(val, str):
                    return val.lower() in ("on", "1", "true")
                if isinstance(val, (int, float)):
                    return bool(val)
        for val in data.values():
            if isinstance(val, dict):
                found = _guess_on(val)
                if found is not None:
                    return found
    return None


def _guess_number(data, keys):
    if isinstance(data, dict):
        for key in keys:
            if key in data and isinstance(data[key], (int, float)):
                return float(data[key])
        for val in data.values():
            if isinstance(val, dict):
                found = _guess_number(val, keys)
                if found is not None:
                    return found
    return None


def cmd_plug(args):
    sub = args[0].lower() if args else "status"
    cfg = load_plug_config()
    if cfg and cfg.get("type", "tuya").lower() == "tuya" and tinytuya is None:
        if offer_install("tinytuya", "Tuya smart plugs"):
            return
    if cfg is None:
        print(c("\n  no plug configured", RED))
        print(c(f"  create {PLUG_CONFIG_FILE}", GREY))
        print(c("  see the README for tuya, http and command examples\n", GREY))
        return
    name = cfg.get("name", "plug")
    try:
        if sub in ("on", "off"):
            state = sub == "on"
            with Spinner(f"switching {name} {sub}"):
                plug_switch(cfg, state)
            print()
            print(header("MINER PLUG", name))
            print()
            print(row("State", "ON" if state else "OFF", GREEN if state else RED))
            print()
            return
        with Spinner(f"reading {name}"):
            status = plug_status(cfg)
        print()
        print(header("MINER PLUG", name))
        print()
        print(section("STATE"))
        if not status:
            print(c("  this plug type reports no status \u2014 switching still works", GREY))
            print()
            return
        on = status.get("on")
        if on is None:
            print(row("Power state", "unknown", GREY))
        else:
            print(row("Power state", "ON" if on else "OFF", GREEN if on else RED))
        if cfg.get("ip"):
            print(row("IP", cfg["ip"], YELLOW))
        if status.get("voltage") is not None:
            print(row("Voltage", f"{status['voltage']:.1f} V"))
        if status.get("current") is not None:
            print(row("Current", f"{status['current']:.3f} A"))
        if status.get("power") is not None:
            print(row("Power draw", f"{status['power']:.1f} W", ORANGE))
        if status.get("energy") is not None:
            print(row("Energy total", f"{status['energy']:.3f} kWh"))
        print()
    except Exception as e:
        print(c(f"\n  \u2715 {e}\n", RED))

def wz_step(n, total, title):
    print()
    print(section(f"{n} / {total}   {title}"))
    print()


def wz_ok(text):
    print(f"  {GREEN}\u2713{RESET} {text}")


def wz_warn(text):
    print(f"  {YELLOW}!{RESET} {text}")


def wz_fail(text):
    print(f"  {RED}\u2715{RESET} {text}")


def wz_note(text):
    print(f"  {GREY}{text}{RESET}")


def wz_ask(prompt, default=""):
    hint = f" {GREY}[{default}]{RESET}" if default else ""
    try:
        answer = input(f"  {CYAN}{prompt}{RESET}{hint} ").strip()
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt
    return answer or default


def wz_yes(prompt, default=True):
    suffix = "Y/n" if default else "y/N"
    answer = wz_ask(f"{prompt} ({suffix})").lower()
    if not answer:
        return default
    return answer.startswith("y")


def probe_core(mode, container):
    saved_mode, saved_container = globals()["BITCOIN_MODE"], globals()["BITCOIN_CONTAINER"]
    globals()["BITCOIN_MODE"], globals()["BITCOIN_CONTAINER"] = mode, container
    try:
        info = core(["getblockchaininfo"])
        net = core(["getnetworkinfo"])
        return {
            "blocks": info.get("blocks"),
            "chain": info.get("chain"),
            "version": net.get("subversion", "").strip("/"),
        }
    except Exception:
        return None
    finally:
        globals()["BITCOIN_MODE"], globals()["BITCOIN_CONTAINER"] = saved_mode, saved_container


def list_bitcoin_containers():
    names = []
    for prefix in (["docker"], ["sudo", "-n", "docker"]):
        try:
            out = subprocess.run(prefix + ["ps", "--format", "{{.Names}}"],
                                 capture_output=True, text=True, timeout=20)
            if out.returncode == 0:
                names = [n.strip() for n in out.stdout.split("\n") if n.strip()]
                break
        except Exception:
            continue

    # containers that clearly cannot answer bitcoin-cli
    skip = ("tor", "app_proxy", "i2pd", "electrs", "nginx", "redis", "proxy")

    def score(name):
        low = name.lower()
        if any(s in low for s in skip):
            return 3
        if "bitcoind" in low:
            return 0
        if "bitcoin" in low:
            return 1
        return 2

    return sorted(names, key=lambda n: (score(n), n))


def wizard_core(settings):
    wz_step(1, 5, "BITCOIN CORE")
    wz_note("looking for your node")
    print()

    candidates = list_bitcoin_containers()
    for name in candidates[:8]:
        found = probe_core("docker", name)
        if found:
            wz_ok(f"found {WHITE}{name}{RESET} (docker)")
            wz_ok(f"{found['version']} \u00b7 {found['chain']} \u00b7 block {found['blocks']:,}")
            settings["mode"] = "docker"
            settings["container"] = name
            return True

    found = probe_core("host", "")
    if found:
        wz_ok("found bitcoin-cli on this machine")
        wz_ok(f"{found['version']} \u00b7 {found['chain']} \u00b7 block {found['blocks']:,}")
        settings["mode"] = "host"
        return True

    wz_fail("could not reach a node automatically")
    print()
    if candidates:
        wz_note("containers running right now:")
        for name in candidates[:10]:
            wz_note(f"  {name}")
        print()
    wz_note("if your node runs in docker, enter its container name")
    wz_note("if bitcoin-cli works in this shell, type: host")
    print()
    for _ in range(3):
        answer = wz_ask("container name or 'host' (blank to skip):")
        if not answer:
            wz_warn("skipped \u2014 most commands will not work until this is set")
            return False
        mode = "host" if answer.lower() == "host" else "docker"
        found = probe_core(mode, answer)
        if found:
            wz_ok(f"{found['version']} \u00b7 {found['chain']} \u00b7 block {found['blocks']:,}")
            settings["mode"] = mode
            if mode == "docker":
                settings["container"] = answer
            return True
        wz_fail("no answer from that \u2014 try again")
    wz_warn("skipped")
    return False


def probe_electrum(host, port):
    try:
        sock = socket.create_connection((host, int(port)), timeout=5)
        payload = json.dumps({"id": 0, "method": "server.version",
                              "params": ["bitcoin-core-cli", "1.4"]}) + "\n"
        sock.sendall(payload.encode())
        sock.settimeout(5)
        data = sock.recv(4096).decode(errors="replace")
        sock.close()
        parsed = json.loads(data.strip().split("\n")[0])
        return parsed.get("result")
    except Exception:
        return None


def wizard_electrum(settings):
    wz_step(2, 5, "ELECTRS   (optional)")
    wz_note("needed for address lookups, wallet scans and the fee histogram")
    wz_note("skip it and everything else still works")
    print()

    host = settings.get("electrum_host", "127.0.0.1")
    port = settings.get("electrum_port", 50001)
    result = probe_electrum(host, port)
    if result:
        name = result[0] if isinstance(result, list) and result else "electrs"
        wz_ok(f"found {WHITE}{name}{RESET} at {host}:{port}")
        settings["electrum_host"] = host
        settings["electrum_port"] = int(port)
        return True

    wz_warn(f"nothing answering at {host}:{port}")
    print()
    if not wz_yes("enter a different address?", default=False):
        wz_note("skipped \u2014 run setup again once electrs is up")
        return False
    for _ in range(3):
        host = wz_ask("electrs host:", "127.0.0.1")
        port = wz_ask("electrs port:", "50001")
        if not str(port).isdigit():
            wz_fail("port must be a number")
            continue
        result = probe_electrum(host, port)
        if result:
            wz_ok(f"connected to {host}:{port}")
            settings["electrum_host"] = host
            settings["electrum_port"] = int(port)
            return True
        wz_fail("no answer \u2014 port 50002 is usually SSL and will not work here")
    wz_note("skipped")
    return False


def wizard_wallets(settings):
    wz_step(3, 5, "WALLETS   (optional)")
    wz_note("watch-only. paste a zpub and the client shows its balance,")
    wz_note("addresses and UTXOs using your own index. keys never leave the machine.")
    print()

    if os.path.exists(WALLET_FILE):
        wz_ok(f"already have {WALLET_FILE}")
        if not wz_yes("add another wallet?", default=False):
            return True
    elif not wz_yes("add a wallet now?", default=False):
        wz_note("skipped \u2014 add one later with: btc setup")
        return False

    added = 0
    while True:
        key = wz_ask("zpub (blank to finish):")
        if not key:
            break
        if not key.startswith("zpub"):
            wz_fail("that is not a zpub \u2014 native segwit keys only")
            continue
        try:
            parse_extended_key(key)
        except Exception:
            wz_fail("could not parse that key")
            continue
        label = wz_ask("name for it:", "Wallet")
        os.makedirs(BTC_HOME, exist_ok=True)
        with open(WALLET_FILE, "a", encoding="utf-8") as f:
            f.write(f"{label.replace(' ', '_')}    {key}\n")
        try:
            os.chmod(WALLET_FILE, 0o600)
        except Exception:
            pass
        added += 1
        wz_ok(f"saved as {label}")
    if added:
        wz_note(f"{WALLET_FILE} \u00b7 chmod 600 applied")
    return bool(added)


def wizard_miner(settings):
    wz_step(4, 5, "MINER   (optional)")
    wz_note("for a Bitaxe or anything else running AxeOS")
    wz_note("you need its IP address \u2014 check your router or the miner's display")
    print()

    current = settings.get("miner_host", "")
    if current:
        wz_ok(f"currently set to {current}")
        if not wz_yes("change it?", default=False):
            return True
    elif not wz_yes("set up a miner now?", default=False):
        wz_note("skipped \u2014 add one later with: btc setup")
        return False

    for _ in range(3):
        host = wz_ask("miner IP (blank to skip):", current)
        if not host:
            wz_note("skipped")
            return False
        saved = globals()["BITAXE_HOST"]
        globals()["BITAXE_HOST"] = host
        try:
            info = bitaxe_info()
            model = info.get("ASICModel", "miner")
            rate = info.get("hashRate") or 0
            wz_ok(f"found {WHITE}{model}{RESET} at {host}")
            wz_ok(f"{fmt_hashrate(rate)} \u00b7 {info.get('temp', '?')} \u00b0C")
            settings["miner_host"] = host
            return True
        except Exception:
            wz_fail(f"nothing answering at {host}")
        finally:
            globals()["BITAXE_HOST"] = saved
    wz_note("skipped")
    return False


def wizard_plug(settings):
    wz_step(5, 5, "SMART PLUG   (optional)")
    wz_note("lets you cut power to the miner with: stop mining")
    wz_note("three ways to connect one \u2014 pick what matches your socket")
    print()

    if os.path.exists(PLUG_CONFIG_FILE):
        wz_ok(f"already configured in {PLUG_CONFIG_FILE}")
        if not wz_yes("replace it?", default=False):
            return True
    elif not wz_yes("set up a smart plug now?", default=False):
        wz_note("skipped \u2014 add one later with: btc setup")
        return False

    print()
    wz_note("  1  http      Shelly, Tasmota, ESPHome \u2014 anything with a local URL")
    wz_note("  2  command   any socket you can switch from a shell (Kasa, Home Assistant)")
    wz_note("  3  tuya      cheap Smart Life / Tuya plugs \u2014 needs a one-off setup")
    print()
    choice = wz_ask("type (1-3, blank to skip):")
    if choice not in ("1", "2", "3"):
        wz_note("skipped")
        return False

    name = wz_ask("name for the socket:", "Miner")
    cfg = {"name": name}

    if choice == "1":
        cfg["type"] = "http"
        wz_note("the URLs your socket uses \u2014 see the README for Shelly/Tasmota examples")
        cfg["on_url"] = wz_ask("URL that switches it ON:")
        cfg["off_url"] = wz_ask("URL that switches it OFF:")
        status = wz_ask("URL that reports state (blank if none):")
        if status:
            cfg["status_url"] = status
        if not cfg["on_url"] or not cfg["off_url"]:
            wz_fail("need both an on and an off URL \u2014 skipped")
            return False

    elif choice == "2":
        cfg["type"] = "command"
        wz_note("shell commands that switch your socket")
        cfg["on_cmd"] = wz_ask("command to switch ON:")
        cfg["off_cmd"] = wz_ask("command to switch OFF:")
        status = wz_ask("command printing on/off (blank if none):")
        if status:
            cfg["status_cmd"] = status
        if not cfg["on_cmd"] or not cfg["off_cmd"]:
            wz_fail("need both an on and an off command \u2014 skipped")
            return False

    else:
        cfg["type"] = "tuya"
        print()
        if tinytuya is None:
            if offer_install("tinytuya", "Tuya smart plugs"):
                wz_note("restart the client, then run setup again to finish this step")
            return False
        wz_ok("tinytuya is installed")
        print()
        wz_note("tuya plugs need a local key, which you get once from their portal.")
        wz_note("the README walks through it. short version:")
        wz_note("  1. sign up at iot.tuya.com, create a Smart Home cloud project")
        wz_note("  2. authorize IoT Core + Authorization Token Management")
        wz_note("  3. link your Smart Life app by scanning the QR code")
        wz_note("  4. run:  python3 -m tinytuya wizard")
        wz_note("that writes devices.json with id, key, ip and version")
        print()
        if not wz_yes("do you have those four values ready?", default=False):
            wz_note("skipped \u2014 come back with: btc setup")
            return False
        cfg["id"] = wz_ask("device id:")
        cfg["key"] = wz_ask("local key:")
        cfg["ip"] = wz_ask("ip address:")
        cfg["version"] = wz_ask("protocol version:", "3.3")
        if not (cfg["id"] and cfg["key"] and cfg["ip"]):
            wz_fail("id, key and ip are all required \u2014 skipped")
            return False

    os.makedirs(BTC_HOME, exist_ok=True)
    with open(PLUG_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    try:
        os.chmod(PLUG_CONFIG_FILE, 0o600)
    except Exception:
        pass
    wz_ok(f"saved to {PLUG_CONFIG_FILE} (chmod 600)")

    print()
    if wz_yes("test it now? this will switch the socket off and back on", default=False):
        try:
            with Spinner("switching off"):
                plug_switch(cfg, False)
            wz_ok("off")
            time.sleep(2)
            with Spinner("switching on"):
                plug_switch(cfg, True)
            wz_ok("on \u2014 working")
        except Exception as e:
            wz_fail(f"{e}")
            wz_note("check the values and run setup again")
    return True


def cmd_setup(args):
    settings = dict(SETTINGS)
    print()
    print(header("SETUP"))
    print()
    wz_note("this connects the client to your node and hardware.")
    wz_note("everything after step 2 is optional and can be done later.")
    wz_note("re-run any time with:  btc setup")

    try:
        wizard_core(settings)
        wizard_electrum(settings)
        save_settings(settings)
        wizard_wallets(settings)
        wizard_miner(settings)
        save_settings(settings)
        wizard_plug(settings)
    except KeyboardInterrupt:
        print()
        print()
        wz_warn("cancelled \u2014 nothing further was saved")
        save_settings(settings)
        print()
        return

    save_settings(settings)

    print()
    print(section("DONE"))
    print()
    print(row("Node", settings.get("container") or settings.get("mode", "?"), GREEN))
    print(row("Electrs", f"{settings.get('electrum_host', '-')}:{settings.get('electrum_port', '-')}"
              if settings.get("electrum_host") else "not set"))
    print(row("Miner", settings.get("miner_host") or "not set"))
    print(row("Smart plug", "configured" if os.path.exists(PLUG_CONFIG_FILE) else "not set"))
    print(row("Wallets", "configured" if os.path.exists(WALLET_FILE) else "not set"))
    print()
    wz_note(f"settings saved to {CONFIG_FILE}")
    print()
    print(f"  {GREY}try:{RESET}  {GREEN}dashboard{RESET}   {GREY}or{RESET}   {GREEN}index{RESET} {GREY}for every command{RESET}")
    print()


def version_tuple(text):
    parts = []
    for chunk in str(text).strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def fetch_remote_version(timeout=6):
    req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": "bitcoin-core-cli"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        head = resp.read(4096).decode(errors="replace")
    match = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', head, re.M)
    if not match:
        raise RuntimeError("could not read the version from the repository")
    return match.group(1)


def read_update_cache():
    try:
        with open(UPDATE_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_update_cache(data):
    try:
        os.makedirs(BTC_HOME, exist_ok=True)
        with open(UPDATE_CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def background_update_check():
    cache = read_update_cache()
    if time.time() - cache.get("checked", 0) < UPDATE_CHECK_INTERVAL:
        return

    def worker():
        entry = {"checked": time.time()}
        try:
            entry["latest"] = fetch_remote_version()
        except Exception as e:
            entry["error"] = str(e)[:120]
        write_update_cache(entry)

    t = threading.Thread(target=worker, daemon=True)
    t.start()


def update_notice():
    cache = read_update_cache()
    latest = cache.get("latest")
    if not latest:
        return None
    if version_tuple(latest) > version_tuple(VERSION):
        return latest
    return None


def install_dir():
    return os.path.dirname(os.path.abspath(__file__))


def cmd_update(args):
    print()
    print(header("UPDATE"))
    print()
    print(row("Installed", VERSION, WHITE))

    try:
        with Spinner("checking the repository"):
            latest = fetch_remote_version()
    except Exception as e:
        msg = str(e)
        print(c(f"\n  could not reach the repository \u2014 {msg}", RED))
        if "404" in msg or "403" in msg:
            print(c("  a private repository needs a token; make it public or update manually", GREY))
        print()
        return

    write_update_cache({"checked": time.time(), "latest": latest})
    print(row("Latest", latest, GREEN if version_tuple(latest) > version_tuple(VERSION) else WHITE))
    print()

    if version_tuple(latest) <= version_tuple(VERSION):
        print(c("  already up to date", GREEN))
        print()
        return

    target = os.path.join(install_dir(), "btc.py")
    git_dir = os.path.join(install_dir(), ".git")

    if not wz_yes(f"update to {latest}?", default=True):
        print(c("\n  cancelled\n", GREY))
        return

    try:
        if os.path.isdir(git_dir):
            with Spinner("git pull"):
                result = subprocess.run(["git", "-C", install_dir(), "pull", "--ff-only"],
                                        capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout).strip()[:200])
        else:
            with Spinner("downloading"):
                req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": "bitcoin-core-cli"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = resp.read()
            if b"VERSION" not in payload[:4096] or len(payload) < 10000:
                raise RuntimeError("downloaded file looks wrong, keeping the current one")
            backup = target + ".bak"
            shutil.copy2(target, backup)
            with open(target, "wb") as f:
                f.write(payload)
            print(c(f"  previous version kept at {os.path.basename(backup)}", GREY))
    except Exception as e:
        print(c(f"\n  \u2715 update failed: {e}\n", RED))
        return

    write_update_cache({"checked": time.time(), "latest": latest})
    print()
    print(c(f"  \u2713 updated to {latest}", GREEN))
    print(c("  restart the client to load it", GREY))
    print()


DEPENDENCIES = [
    {
        "module": "tinytuya",
        "package": "tinytuya",
        "needed_for": "Tuya smart plugs",
        "required": False,
    },
]


def pip_install(package):
    for args in (
        [sys.executable, "-m", "pip", "install", package, "--break-system-packages"],
        [sys.executable, "-m", "pip", "install", package],
        [sys.executable, "-m", "pip", "install", package, "--user"],
    ):
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                return True, ""
            last = (result.stderr or result.stdout).strip()
        except Exception as e:
            last = str(e)
    return False, last[-300:] if last else "pip failed"


def offer_install(package, reason):
    print()
    print(c(f"  {package} is not installed \u2014 needed for {reason}", YELLOW))
    try:
        answer = input(f"  {CYAN}install it now? (Y/n){RESET} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if answer and not answer.startswith("y"):
        print(c(f"  skipped \u2014 install later with: python3 -m pip install {package} --break-system-packages\n", GREY))
        return False
    with Spinner(f"installing {package}"):
        ok, err = pip_install(package)
    if ok:
        print(c(f"  \u2713 {package} installed \u2014 restart the client to use it\n", GREEN))
        return True
    print(c(f"  \u2715 install failed: {err}", RED))
    print(c(f"  try manually: python3 -m pip install {package} --break-system-packages\n", GREY))
    return False


def cmd_doctor(args):
    print()
    print(header("DOCTOR"))
    print()
    print(section("ENVIRONMENT"))
    pyv = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 8)
    print(row("Python", pyv + ("" if py_ok else "  (3.8+ required)"), GREEN if py_ok else RED))
    print(row("Client version", VERSION, WHITE))
    print(row("Install path", install_dir(), GREY))
    print(row("Config", BTC_HOME, GREY))

    print()
    print(section("NODE"))
    try:
        info = core(["getblockchaininfo"])
        net = core(["getnetworkinfo"])
        print(row("Bitcoin Core", net.get("subversion", "?").strip("/"), GREEN))
        print(row("Chain", f"{info.get('chain')} \u00b7 block {info.get('blocks', 0):,}", WHITE))
        mode = "host" if BITCOIN_MODE == "host" else f"docker \u00b7 {BITCOIN_CONTAINER}"
        print(row("Reached via", mode, GREY))
    except Exception as e:
        print(row("Bitcoin Core", "unreachable", RED))
        print(c(f"    {str(e)[:120]}", GREY))
        print(c("    run 'setup' to point the client at your node", GREY))

    print()
    print(section("ELECTRS"))
    try:
        with Spinner("testing electrs"):
            result = probe_electrum(ELECTRUM_HOST, ELECTRUM_PORT)
        if result:
            name = result[0] if isinstance(result, list) and result else "electrs"
            print(row("Electrs", f"{name} at {ELECTRUM_HOST}:{ELECTRUM_PORT}", GREEN))
        else:
            print(row("Electrs", f"no answer at {ELECTRUM_HOST}:{ELECTRUM_PORT}", YELLOW))
            print(c("    only address and wallet lookups need this", GREY))
    except Exception:
        print(row("Electrs", "not reachable", YELLOW))

    print()
    print(section("OPTIONAL PACKAGES"))
    missing = []
    for dep in DEPENDENCIES:
        try:
            __import__(dep["module"])
            print(row(dep["module"], "installed", GREEN))
        except ImportError:
            print(row(dep["module"], f"missing \u2014 {dep['needed_for']}", YELLOW))
            missing.append(dep)

    print()
    print(section("HARDWARE"))
    print(row("Miner", BITAXE_HOST or "not configured", GREEN if BITAXE_HOST else GREY))
    plug = load_plug_config()
    print(row("Smart plug", f"{plug.get('type', '?')} \u00b7 {plug.get('name', '')}" if plug else "not configured",
              GREEN if plug else GREY))

    print()
    print(section("UPDATES"))
    try:
        with Spinner("checking for updates"):
            latest = fetch_remote_version()
        write_update_cache({"checked": time.time(), "latest": latest})
        if version_tuple(latest) > version_tuple(VERSION):
            print(row("Latest", f"{latest}  \u2014 run 'update'", GREEN))
        else:
            print(row("Latest", f"{latest}  (up to date)", WHITE))
    except Exception as e:
        print(row("Latest", "could not check", GREY))
        if "404" in str(e) or "403" in str(e):
            print(c("    the repository is private or unreachable", GREY))
    print()

    for dep in missing:
        offer_install(dep["package"], dep["needed_for"])


def decode_op_return(hex_script):
    try:
        raw = bytes.fromhex(hex_script)
    except ValueError:
        return None
    if not raw or raw[0] != 0x6a:
        return None
    body = raw[1:]
    chunks = []
    i = 0
    while i < len(body):
        op = body[i]
        i += 1
        if 1 <= op <= 75:
            chunks.append(body[i:i + op])
            i += op
        elif op == 0x4c and i < len(body):
            n = body[i]
            i += 1
            chunks.append(body[i:i + n])
            i += n
        elif op == 0x4d and i + 1 < len(body):
            n = int.from_bytes(body[i:i + 2], "little")
            i += 2
            chunks.append(body[i:i + n])
            i += n
        else:
            break
    if not chunks:
        chunks = [body]
    return b"".join(chunks)


def readable_text(data, minimum=8):
    if not data:
        return None
    runs = re.findall(rb"[\x20-\x7e]{%d,}" % minimum, data)
    if not runs:
        return None
    best = max(runs, key=len).decode("ascii", "ignore").strip()
    printable = sum(1 for b in data if 32 <= b < 127)
    if len(best) < minimum or printable / len(data) < 0.6:
        return None
    return best


def block_messages(target):
    block_hash = block_hash_for(target)
    block = core(["getblock", block_hash, "2"])
    found = []
    for tx in block.get("tx", []):
        txid = tx.get("txid", "")
        for vout in tx.get("vout", []):
            spk = vout.get("scriptPubKey", {})
            if spk.get("type") != "nulldata":
                continue
            data = decode_op_return(spk.get("hex", ""))
            if data is None:
                continue
            found.append({
                "txid": txid,
                "bytes": len(data),
                "text": readable_text(data),
                "hex": data.hex(),
            })
    return block, found


def cmd_messages(args):
    if not args:
        print(c("  usage: btc messages <height|hash>", RED))
        return
    show_all = len(args) > 1 and args[1].lower() in ("all", "raw")
    with Spinner("scanning the block for embedded data"):
        block, found = block_messages(args[0])

    height = block.get("height", "?")
    print()
    print(header(f"MESSAGES IN BLOCK #{height:,}" if isinstance(height, int)
                 else f"MESSAGES IN BLOCK {height}"))
    print()

    try:
        summary, raw, reward = coinbase_of(block["hash"])
        miner_text = coinbase_message(raw)
        pool = detect_pool(coinbase_text(raw))
        print(section("WRITTEN BY THE MINER"))
        print(f"  {GREEN}{miner_text or '(no readable text)'}{RESET}")
        if pool:
            print(row("Pool", pool, GREY))
        print()
    except Exception:
        pass

    readable = [f for f in found if f["text"]]
    print(section("OP_RETURN OUTPUTS"))
    if not found:
        print(c("  no OP_RETURN data in this block", GREY))
        print()
        return
    print(row("Outputs found", f"{len(found):,}", WHITE))
    print(row("With readable text", f"{len(readable):,}", GREEN if readable else GREY))
    print()

    shown = found if show_all else readable
    if not shown:
        print(c("  none of it is readable text \u2014 protocol data, not messages", GREY))
        print(c(f"  'messages {args[0]} all' lists them anyway", DIM + GREY))
        print()
        return

    for entry in shown[:40]:
        print(f"  {YELLOW}{short_id(entry['txid'])}{RESET}  {GREY}{entry['bytes']} bytes{RESET}")
        if entry["text"]:
            body = entry["text"]
            width = max(30, term_width() - 6)
            while body:
                print(f"    {GREEN}{body[:width]}{RESET}")
                body = body[width:]
        else:
            preview = entry["hex"][:60]
            print(f"    {GREY}{preview}\u2026{RESET}")
        print()
    if len(shown) > 40:
        print(c(f"  \u2026 {len(shown) - 40} more", GREY))
        print()


CORE_RELEASES_API = "https://api.github.com/repos/bitcoin/bitcoin/releases?per_page=40"
CORE_NOTES_URL = "https://raw.githubusercontent.com/bitcoin/bitcoin/master/doc/release-notes/release-notes-{v}.md"


def http_json(url, timeout=12):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "bitcoin-core-cli",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_text(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "bitcoin-core-cli"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(errors="replace")


def running_core_version():
    try:
        net = core(["getnetworkinfo"])
        return net["subversion"].strip("/").split(":")[-1]
    except Exception:
        return None


def core_releases():
    data = http_json(CORE_RELEASES_API)
    out = []
    for r in data:
        tag = r.get("tag_name", "")
        if not tag.startswith("v"):
            continue
        out.append({
            "version": tag[1:],
            "date": (r.get("published_at") or "")[:10],
            "prerelease": bool(r.get("prerelease")),
        })
    out.sort(key=lambda x: version_tuple(x["version"]), reverse=True)
    return out


def cmd_versions(args):
    if args and not args[0].isdigit() and any(ch.isdigit() for ch in args[0]):
        return show_release_notes(args[0])

    running = running_core_version()
    try:
        with Spinner("fetching the release list"):
            releases = core_releases()
    except Exception as e:
        print(c(f"\n  could not reach github \u2014 {str(e)[:90]}\n", RED))
        return

    print()
    print(header("BITCOIN CORE RELEASES"))
    print()
    print(section("YOUR NODE"))
    print(row("Running", running or "unknown", GREEN))
    if running:
        newer = [r for r in releases
                 if not r["prerelease"] and version_tuple(r["version"]) > version_tuple(running)]
        if newer:
            print(row("Newer available", f"{len(newer)} \u00b7 latest is {newer[0]['version']}", YELLOW))
        else:
            print(row("Status", "up to date", GREEN))
    print()

    print(section("RELEASES"))
    shown = 0
    for r in releases:
        if r["prerelease"]:
            continue
        v = r["version"]
        if running and version_tuple(v) == version_tuple(running):
            mark, col = "\u25b6 running", GREEN
        elif running and version_tuple(v) > version_tuple(running):
            mark, col = "newer", YELLOW
        else:
            mark, col = "", GREY
        print(f"  {col}{v:<10}{RESET}{GREY}{r['date']}{RESET}  {col}{mark}{RESET}")
        shown += 1
        if shown >= 20:
            break
    print()
    print(f"  {GREY}versions <x.y>   read the release notes for that version{RESET}")
    print()


def show_release_notes(version):
    version = version.lstrip("v")
    try:
        with Spinner(f"fetching release notes for {version}"):
            text = http_text(CORE_NOTES_URL.format(v=version))
    except Exception as e:
        msg = str(e)
        print(c(f"\n  no release notes found for {version}", RED))
        if "404" in msg:
            print(c("  check the version number \u2014 'versions' lists them", GREY))
        print()
        return

    running = running_core_version()
    print()
    print(header(f"RELEASE NOTES \u00b7 {version}"))
    if running:
        cmp_ = version_tuple(version)
        cur = version_tuple(running)
        if cmp_ > cur:
            print(c(f"  newer than the {running} you are running", YELLOW))
        elif cmp_ < cur:
            print(c(f"  older than the {running} you are running", GREY))
        else:
            print(c("  this is what you are running", GREEN))
    print()

    width = max(40, term_width() - 4)
    skip_sections = ("credits", "thanks to everyone")
    lines = text.replace("\r", "").split("\n")

    def flush(buf):
        if not buf:
            return
        joined = " ".join(x.strip() for x in buf)
        bullet = joined.startswith("- ")
        colour = GREY if bullet else WHITE
        for n, part in enumerate(textwrap.wrap(joined, width=width - 2,
                                               break_long_words=False,
                                               break_on_hyphens=False)):
            pad = "" if n == 0 or not bullet else "  "
            print(f"  {colour}{pad}{part}{RESET}")
        print()

    para = []
    i = 0
    printed = 0
    while i < len(lines) and printed < 200:
        line = lines[i].rstrip()
        nxt = lines[i + 1].rstrip() if i + 1 < len(lines) else ""
        if nxt and set(nxt) in ({"="}, {"-"}) and len(nxt) >= 3 and line:
            title = line.strip()
            if title.lower().startswith(skip_sections):
                break
            flush(para); para = []
            print(section(title.upper()))
            print()
            i += 2
            continue
        if not line.strip():
            flush(para); para = []
        elif line.lstrip().startswith(("- ", "* ")) or line.startswith("  "):
            flush(para); para = [line]
            printed += 1
        else:
            para.append(line)
            printed += 1
        i += 1
    flush(para)
    print(f"  {GREY}full notes: https://bitcoincore.org/en/releases/{version}/{RESET}")
    print()


def cmd_signals(args):
    window = int(args[0]) if args and args[0].isdigit() else 144
    window = max(10, min(window, 2016))

    print()
    print(header("SOFT FORK SIGNALLING", f"last {window} blocks"))
    print()

    try:
        info = core(["getblockchaininfo"])
    except Exception as e:
        print(c(f"  {e}\n", RED))
        return

    forks = info.get("softforks", {})
    known_bits = {}
    active = []
    pending = []
    for name, data in forks.items():
        if not isinstance(data, dict):
            continue
        status = data.get("active")
        bip9 = data.get("bip9") or {}
        bit = bip9.get("bit")
        if bit is not None:
            known_bits[bit] = name
        if status:
            active.append(name)
        elif bip9:
            pending.append((name, bip9))

    print(section("KNOWN TO YOUR NODE"))
    if active:
        print(row("Active", ", ".join(sorted(active)), GREEN))
    for name, bip9 in pending:
        st = bip9.get("status", "?")
        stats = bip9.get("statistics") or {}
        detail = f"{st}"
        if stats.get("count") is not None and stats.get("elapsed"):
            pct = stats["count"] / stats["elapsed"] * 100
            detail += f" \u00b7 {stats['count']}/{stats['elapsed']} ({pct:.1f}%)"
        print(row(name, detail, YELLOW))
    if not active and not pending:
        print(c("  nothing pending", GREY))
    print()

    with Spinner(f"reading {window} block headers"):
        tally = {}
        counted = 0
        try:
            h = core(["getbestblockhash"])
            for _ in range(window):
                hdr = core(["getblockheader", h])
                ver = hdr.get("version", 0)
                if (ver & 0xE0000000) == 0x20000000:
                    for bit in range(29):
                        if ver & (1 << bit):
                            tally[bit] = tally.get(bit, 0) + 1
                counted += 1
                h = hdr.get("previousblockhash")
                if not h:
                    break
        except Exception as e:
            print(c(f"  {e}\n", RED))
            return

    print(section("VERSION BITS SEEN IN BLOCKS"))
    if not tally:
        print(c(f"  no bits set across {counted} blocks \u2014 nothing being signalled", GREY))
        print()
        return
    for bit in sorted(tally, key=lambda b: -tally[b]):
        count = tally[bit]
        pct = count / counted * 100
        name = known_bits.get(bit)
        label = f"bit {bit}" + (f"  {name}" if name else "")
        bar = FULLBLOCK * max(1, int(pct / 5))
        note = "" if name else f"  {GREY}unknown deployment{RESET}"
        col = GREEN if pct >= 50 else (YELLOW if pct >= 5 else GREY)
        print(f"  {CYAN}{label:<22}{RESET}{col}{count:>5} / {counted}  {pct:>5.1f}%  {bar}{RESET}{note}")
    print()
    print(f"  {GREY}a bit with no name is a proposal your node does not implement{RESET}")
    print()


HELP_SECTIONS = [
    ("CHAIN", [
        ("dashboard", "live node dashboard \u2014 height, peers, hashrate, mempool", "dashboard"),
        ("info", "detailed blockchain state", "info"),
        ("supply", "coins issued so far vs the 21,000,000 cap", "supply"),
        ("halving", "countdown to the next halving", "halving"),
        ("retarget", "difficulty adjustment forecast", "retarget"),
        ("node", "node identity, version, uptime, connections", "node"),
        ("system", "node hardware \u2014 temperature, CPU, memory, storage", "system"),
        ("net", "total network traffic in / out", "net"),
        ("pulse", "block timing \u2014 time since last block, average, overdue", "pulse"),
        ("chainstate", "UTXO set size + total coins in existence (slow scan)", "chainstate"),
        ("versions [x.y]", "Bitcoin Core releases, what you run, release notes", "versions"),
        ("signals [n]", "soft forks being signalled in recent blocks", "signals"),
    ]),
    ("BLOCKS", [
        ("tip", "the latest block + who mined it", "tip"),
        ("blocks [n]", "the last n blocks (default 10)", "blocks"),
        ("block <n|hash>", "full details of any block", "block"),
        ("header <n|hash>", "raw block header", "header"),
        ("hash <height>", "block hash at a given height", "hash"),
        ("coinbase <n>", "who mined a block + its embedded message", "coinbase"),
        ("genesis", "block #0 and Satoshi's hidden message", "genesis"),
        ("messages <n|hash>", "text people embedded in a block (OP_RETURN)", "messages"),
    ]),
    ("TRANSACTIONS", [
        ("tx <txid>", "decode any transaction", "tx"),
        ("utxo <txid:n>", "check if an output is still unspent", "utxo"),
        ("decode <hex>", "decode a raw transaction hex", "decode"),
    ]),
    ("NETWORK", [
        ("mempool", "unconfirmed transactions", "mempool"),
        ("fees", "fee estimates + live mempool fee histogram", "fees"),
        ("projection", "the waiting mempool as projected blocks + fee bands", "projection"),
        ("peers", "every node you're connected to", "peers"),
    ]),
    ("ADDRESS", [
        ("addr <address>", "balance + tx count via your local Electrs", "addr"),
        ("wallet [zpub...]", "scan your zpub wallets \u2014 full address + UTXO breakdown", "wallet"),
        ("wallet compact", "same scan, summary only (no address/UTXO list)", "walletcompact"),
    ]),
    ("MINER", [
        ("bitaxe", "your Bitaxe miner \u2014 key stats", "bitaxe"),
        ("bitaxe full", "every value the miner exposes", "bitaxefull"),
        ("bitaxe watch", "live miner dashboard (ctrl-c to stop)", "bitaxewatch"),
        ("turn", "smart plug status \u2014 power, voltage, current", "turn"),
        ("start mining", "switches the plug on", "start"),
        ("stop mining", "switches the plug off", "stop"),
    ]),
    ("EXTRAS", [
        ("whitepaper", "extract the Bitcoin whitepaper stored on-chain", "whitepaper"),
        ("matrix", "stream live mempool transaction IDs (ctrl-c to stop)", "matrix"),
        ("scan", "live feed of decoded transactions + new blocks (ctrl-c to stop)", "scan"),
        ("rpc <method>", "call any bitcoin-cli method, pretty-printed", "rpc"),
        ("watch [sec]", "auto-refreshing dashboard", "watch"),
        ("auto [sec]", "cycles through every no-input screen automatically (ctrl-c to stop)", "auto"),
        ("all", "prints every screen once, top to bottom, to scroll through", "all"),
        ("shell", "interactive mode \u2014 run commands without 'btc' (exit to leave)", "shell"),
        ("logo", "show the bitcoin banner", "logo"),
        ("clear", "wipe the screen and redraw the banner", "clear"),
        ("find <x>", "smart lookup \u2014 height, hash, txid or address", "find"),
        ("setup", "guided setup \u2014 node, electrs, wallets, miner, plug", "setup"),
        ("doctor", "check node, electrs, packages and hardware", "doctor"),
        ("update", "check for a new version and install it", "update"),
        ("guide", "explains every command + what to type (start here)", "guide"),
        ("index", "this list of all commands", "help"),
    ]),
]

NUMBERED_COMMANDS = {}
_n = 1
for _title, _items in HELP_SECTIONS:
    for _name, _desc, _key in _items:
        NUMBERED_COMMANDS[_n] = _key
        _n += 1


def cmd_help(args):
    print()
    n = 1
    for title, items in HELP_SECTIONS:
        print()
        print(section(title))
        for name, desc, _key in items:
            label = name if IN_SHELL else f"btc {name}"
            print(f"  {GREY}{n:>2}{RESET}  {GREEN}{label:<22}{RESET}{GREY}{desc}{RESET}")
            n += 1
    print()


def cmd_plug_on(args):
    cmd_plug(["on"] + list(args))


def cmd_plug_off(args):
    cmd_plug(["off"] + list(args))


def cmd_wallet_compact(args):
    cmd_wallet(["compact"] + list(args))


COMMANDS = {
    "": cmd_dashboard,
    "dashboard": cmd_dashboard,
    "btc": cmd_dashboard,
    "shell": cmd_shell,
    "repl": cmd_shell,
    "logo": cmd_logo,
    "banner": cmd_logo,
    "clear": cmd_clear,
    "cls": cmd_clear,
    "versions": cmd_versions,
    "releases": cmd_versions,
    "signals": cmd_signals,
    "signalling": cmd_signals,
    "info": cmd_info,
    "supply": cmd_supply,
    "halving": cmd_halving,
    "retarget": cmd_retarget,
    "difficulty": cmd_retarget,
    "node": cmd_node,
    "system": cmd_nodestats,
    "net": cmd_traffic,
    "traffic": cmd_traffic,
    "mempool": cmd_mempool,
    "mem": cmd_mempool,
    "fees": cmd_fees,
    "peers": cmd_peers,
    "tip": cmd_tip,
    "blocks": cmd_blocks,
    "block": cmd_block,
    "header": cmd_header,
    "hash": cmd_hash,
    "coinbase": cmd_coinbase,
    "genesis": cmd_genesis,
    "messages": cmd_messages,
    "opreturn": cmd_messages,
    "tx": cmd_tx,
    "utxo": cmd_utxo,
    "decode": cmd_decode,
    "addr": cmd_addr,
    "wallet": cmd_wallet,
    "walletcompact": cmd_wallet_compact,
    "address": cmd_addr,
    "whitepaper": cmd_whitepaper,
    "matrix": cmd_matrix,
    "scan": cmd_scan,
    "rpc": cmd_rpc,
    "projection": cmd_projection,
    "blocks-projection": cmd_projection,
    "pulse": cmd_pulse,
    "chainstate": cmd_chainstate,
    "utxos": cmd_chainstate,
    "watch": cmd_watch,
    "auto": cmd_auto,
    "all": cmd_all,
    "everything": cmd_all,
    "cycle": cmd_auto,
    "tour": cmd_auto,
    "find": cmd_find,
    "help": cmd_help,
    "index": cmd_help,
    "setup": cmd_setup,
    "wizard": cmd_setup,
    "config": cmd_setup,
    "update": cmd_update,
    "upgrade": cmd_update,
    "doctor": cmd_doctor,
    "check": cmd_doctor,
    "bitaxe": cmd_bitaxe,
    "miner": cmd_bitaxe,
    "bitaxefull": cmd_bitaxe_full,
    "bitaxewatch": cmd_bitaxe_watch,
    "turn": cmd_plug,
    "start": cmd_plug_on,
    "stop": cmd_plug_off,
    "guide": cmd_guide,
    "manual": cmd_guide,
    "lexicon": cmd_guide,
    "commands": cmd_help,
    "menu": cmd_help,
    "-h": cmd_help,
    "--help": cmd_help,
    "?": cmd_help,
}


def main():
    argv = sys.argv[1:]
    cmd = argv[0] if argv else ""
    handler = COMMANDS.get(cmd)
    if handler is None:
        print(c(f"\n  unknown command: {cmd}", RED))
        cmd_help([])
        return
    try:
        handler(argv[1:])
    except Exception as e:
        print(c(f"\n  \u2715 {e}\n", RED))


if __name__ == "__main__":
    main()
