"""Capture public AWS prices and estimate a stopped-between-sessions GPU pilot.

No boto3, credentials, account discovery or resource creation. Public HTTPS only.
"""

import argparse
import gzip
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

BASE = "https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current"
LOCATIONS = {
    "ca-central-1": "Canada (Central)",
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
}
CANDIDATES = ("g6.2xlarge", "g6.4xlarge", "g6e.2xlarge")
IPV4_HOURLY = Decimal("0.005")


def fetch(url):
    with urlopen(url, timeout=30) as response:
        raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError("Public pricing response exceeds the capture bound")
    body = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
    return json.loads(body), hashlib.sha256(body).hexdigest()


def rows(value):
    if isinstance(value, dict):
        if "Instance Type" in value:
            yield value
        else:
            for child in value.values():
                yield from rows(child)
    elif isinstance(value, list):
        for child in value:
            yield from rows(child)


def estimate(hourly, gp3_monthly, hours, volume_gib=300):
    """EBS stays provisioned for a full month; IPv4 is auto-assigned only while on."""
    compute = Decimal(hourly) * Decimal(hours)
    ipv4 = IPV4_HOURLY * Decimal(hours)
    storage = Decimal(gp3_monthly) * volume_gib
    return {
        "running_hours": hours,
        "compute_usd": str(compute.quantize(Decimal("0.01"))),
        "ipv4_usd": str(ipv4.quantize(Decimal("0.01"))),
        "retained_ebs_month_usd": str(storage.quantize(Decimal("0.01"))),
        "subtotal_usd": str((compute + ipv4 + storage).quantize(Decimal("0.01"))),
    }


def capture():
    ebs_url = BASE + "/ebs.json"
    ebs, ebs_hash = fetch(ebs_url)
    evidence = {
        "retrieved_at": datetime.now(UTC).isoformat(),
        "currency": "USD",
        "scope": "Public Linux On-Demand prices; no account, quota or capacity verification",
        "ipv4_hourly_usd": str(IPV4_HOURLY),
        "ipv4_source": "https://aws.amazon.com/vpc/pricing/",
        "volume_gib": 300,
        "exclusions": [
            "Taxes, FX, Marketplace or image-build fees",
            "Snapshots, logs, artifacts and existing control-plane usage",
            "KVS channels, signaling, TURN minutes, internet and inter-region data transfer",
            "NAT or VPC endpoints (not provisioned by this design)",
        ],
        "sources": [{"url": ebs_url, "sha256": ebs_hash, "manifest": ebs["manifest"]}],
        "candidates": [],
    }
    for region, location in LOCATIONS.items():
        url = (
            BASE + "/ec2-ondemand-without-sec-sel/" + quote(location, safe="") + "/Linux/index.json"
        )
        ec2, digest = fetch(url)
        evidence["sources"].append({"url": url, "sha256": digest, "manifest": ec2["manifest"]})
        gp3 = ebs["regions"][location]["Storage General Purpose gp3 GB Mo"]
        found = {
            row["Instance Type"]: row
            for row in rows(ec2)
            if row.get("Location") == location
            and row.get("Operating System") == "Linux"
            and row.get("Pre Installed S/W") == "NA"
            and row["Instance Type"] in CANDIDATES
        }
        for instance in CANDIDATES:
            row = found.get(instance)
            evidence["candidates"].append(
                {
                    "region": region,
                    "instance_type": instance,
                    "listed": row is not None,
                    "price_record": row,
                    "gp3_record": gp3,
                    "estimates": [estimate(row["price"], gp3["price"], h) for h in [8, 40, 730]]
                    if row
                    else [],
                }
            )
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Fetch successfully before replacing a prior capture.
    evidence = capture()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Public price snapshot saved to {args.output}; no AWS account was accessed.")


if __name__ == "__main__":
    main()
