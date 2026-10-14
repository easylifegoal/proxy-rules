#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Install a pinned official rule converter, verifying the compressed asset."""
import argparse
import gzip
import hashlib
import platform
from pathlib import Path
from urllib.request import Request, urlopen

VERSION = "v1.19.32"
ASSETS = {
    ("Linux", "x86_64"): (
        "mihomo-linux-amd64-v1-v1.19.32.gz",
        "306f81e723e60ce6b828899a6fe83e1d00e9ecefb2dc8d4d849312a5bc00efdc",
    ),
    ("Darwin", "arm64"): (
        "mihomo-darwin-arm64-v1.19.32.gz",
        "3312a6780652c622890fd4357c6a853bbf865464fd047ac7b7f52dab8de18652",
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".tools/mihomo"))
    args = parser.parse_args()
    asset, expected = ASSETS[(platform.system(), platform.machine())]
    url = f"https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{asset}"
    with urlopen(Request(url, headers={"User-Agent": "proxy-rules-build"}), timeout=120) as response:
        compressed = response.read(64 * 1024 * 1024 + 1)
    if hashlib.sha256(compressed).hexdigest() != expected:
        raise SystemExit("Mihomo asset SHA-256 mismatch; refusing to execute")
    binary = gzip.decompress(compressed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(binary)
    args.output.chmod(0o700)
    print(f"Installed verified Mihomo {VERSION}: {args.output}")


if __name__ == "__main__":
    main()
