"""Local CLI: no secret flags, no startup motion, no background hardware authority."""

import argparse
import getpass
import importlib.metadata
import json
import os
import secrets
import sys
from pathlib import Path
from uuid import uuid4

import httpx

from .client import AcademyClient, Credentials, run_supervised
from .config import LocalConfig, private_directory, read_private, write_private
from .journal import Journal
from .packages import stage_archive
from .protocol import ProtocolEngine


def operator_approval(command) -> bool:
    if not sys.stdin.isatty():
        raise RuntimeError("Physical execution requires a local operator terminal")
    print(f"\nPhysical execution requested: {command.instrument.upper()} serial {command.serial}")
    print(f"Workflow: {command.plan.title}\nSaved plan SHA256: {command.plan_hash}")
    print(json.dumps(command.plan.model_dump(mode="json"), indent=2))
    print("Verify the exact physical deck, liquids, fresh tips, calibration and a clear workspace.")
    phrase = f"RUN {command.serial} {command.plan_hash[:12]}"
    return input(f"Type '{phrase}' to allow this one run, or Enter to decline: ").strip() == phrase


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "setup":
        from .installer import main as installer_main

        return installer_main(argv[1:])
    if os.name != "posix":
        raise SystemExit(
            "This release requires macOS/Linux private file permissions and process locks"
        )
    parser = argparse.ArgumentParser(description="Academy locally supervised connector companion")
    parser.add_argument(
        "--state-dir", type=Path, default=Path.home() / ".local/share/academy-companion"
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("setup", help="Reviewed local robot installation and rollback")
    sub.add_parser(
        "doctor", help="Check this computer's bundled dependencies without contacting a robot"
    )
    for name in ("pair", "probe", "run"):
        cmd = sub.add_parser(name)
        cmd.add_argument(
            "--config", type=Path, required=True, help="Private mode 0600 local configuration"
        )
        if name == "pair":
            cmd.add_argument(
                "--code-file", type=Path, help="Optional private mode 0600 pairing code file"
            )
        if name == "run":
            cmd.add_argument("--once", action="store_true", help="Claim at most one new command")
    stage = sub.add_parser("stage")
    stage.add_argument("--archive", type=Path, required=True)
    stage.add_argument("--sha256", required=True)
    stage.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.action == "doctor":
        import grpc

        version = importlib.metadata.version("grpcio")
        if version != "1.81.1" or grpc.__version__ != version:
            raise RuntimeError("Pinned SiLA dependency is unavailable")
        print(
            json.dumps(
                {
                    "runtime_ready": True,
                    "grpcio": version,
                    "robot_contacted": False,
                    "hardware_qualified": False,
                }
            )
        )
        return 0
    if args.action == "stage":
        print(stage_archive(args.archive, args.sha256, args.destination))
        return 0
    config = LocalConfig.model_validate_json(read_private(args.config))
    state = private_directory(args.state_dir)
    credential_path = state / "credentials.json"
    with Journal(state) as journal:
        if args.action == "pair" and not credential_path.exists():
            write_private(
                credential_path,
                {
                    "installation_id": str(uuid4()),
                    "secret": secrets.token_urlsafe(32),
                    "academy_url": config.academy_url,
                },
            )
        credentials = Credentials.model_validate_json(read_private(credential_path))
        client = AcademyClient(config, credentials)
        certificate = (
            read_private(Path(config.sila_certificate_file))
            if config.sila_certificate_file
            else None
        )
        engine = ProtocolEngine(config.robot_url, config.profile, certificate=certificate)
        try:
            if args.action == "pair":
                # A lost pair response is reconciled with the same persisted secret first.
                try:
                    client.request("GET", "/companion/me")
                    print("This installation is already paired.")
                    return 0
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {401, 403, 404}:
                        raise
                code = (
                    read_private(args.code_file).decode().strip()
                    if args.code_file
                    else getpass.getpass("Pairing code from Academy: ").strip()
                )
                client.pair(code)
                print("Paired. Hardware is not authorized by pairing.")
            elif args.action == "probe":
                engine.probe()
                client.probe(config.profile)
                print(
                    "Read-only identity and pipette probe matched. Qualification is a separate operator step."
                )
            else:
                if not sys.stdin.isatty():
                    raise RuntimeError("Use an interactive local terminal for supervised execution")
                run_supervised(
                    client,
                    engine,
                    journal,
                    config.profile,
                    approve=operator_approval,
                    once=args.once,
                )

        finally:
            engine.close()
            client.close()
    return 0


def cli(argv=None):
    """Packaged and module entry point with the same credential-safe errors."""
    try:
        return main(argv)
    except (Exception, KeyboardInterrupt) as exc:
        # Never serialize exceptions containing Authorization headers or pairing codes.
        print(
            f"Companion stopped ({type(exc).__name__}). Inspect local state; no command will be replayed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
