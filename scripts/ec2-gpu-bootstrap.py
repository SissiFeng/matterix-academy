"""Extract hashed build-tool requirements from the runtime lock, without resolving packages."""

import argparse
from pathlib import Path

TOOLS = {"uv", "pip", "setuptools", "wheel", "packaging"}


def extract(lock):
    lines = lock.splitlines()
    blocks = []
    found = set()
    for index, line in enumerate(lines):
        name = line.split("==", 1)[0]
        if name not in TOOLS or not line.startswith(name + "=="):
            continue
        block = [line]
        for following in lines[index + 1 :]:
            if not following.lstrip().startswith("--hash=sha256:"):
                break
            block.append(following)
        if len(block) < 2 or name in found:
            raise ValueError("Build tools must occur once with hashes")
        blocks.append("\n".join(block))
        found.add(name)
    if found != TOOLS:
        raise ValueError("Missing hash-locked build tool")
    return "\n".join(blocks) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(extract(args.lock.read_text()))


if __name__ == "__main__":
    main()
