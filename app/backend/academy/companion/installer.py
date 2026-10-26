"""Locally confirmed Flex installation using one reviewed immutable upstream recipe.

No recipe is approved by this module. A catalog-approved artifact must also bind
the exact reviewed recipe digest. Updates, service ownership and rollback remain
local operator actions, separate from browser pairing and physical run authority.
"""

import argparse
import fcntl
import hashlib
import io
import ipaddress
import json
import os
import re
import runpy
import secrets
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from academy.connector_catalog import approved_release
from academy.models import StrictModel

from .config import (
    DIGEST,
    RobotProfile,
    canonical,
    check_private_database,
    digest,
    private_directory,
    read_private,
    validate_url,
    write_private,
)
from .journal import Journal
from .packages import stage_archive
from .protocol import ProtocolEngine

SOURCE_COMMIT = "c4c766a1f860109eaf7d72ce04c714697e34c244"
REVIEWED_FILES = {
    "deploy.sh": "e8768034f498b8bd68f8552d6acfd51eb3cb3c1466550250afba9994a78a1f6b",
    "scripts/artifact_manifest.py": "ecfdb9fb1865c1ff78dea261c70c86896452710abb54f16805e036923ace1580",
    "scripts/install.sh": "de2877bcb3d360591134e388ee1bcddefa7ecb070855cbd908be1e8f36d0b275",
    "scripts/install_connector_service.sh": "e137ec4e9a29c35c1308647b06db467a615c9fac28f5e36ee32b8b9b8ef1d8ea",
    "scripts/start_connector.sh": "4d82dafe4e5a7fa694fac408b0b6ea1a4c7ed21172599201de194fe654205315",
    "scripts/switch_mode.sh": "bd6bedce2b58a1f3e58df19d2ca1fd0b956c09b2c83b1dbd190b06b5e7cf981d",
    "scripts/rollback_connector.sh": "6136df668e0d915235c7473c2831586c73a601166cdcd287a9592ae57f097f8c",
    "config/flex_config.json": "b2acfd723fc7bce9090e1bcd0a5dc05bb5ac78366b424dc299501cdabcd1396c",
    "config/flex_unit_operations.json": "c437ed48b384e70f4b8d3cfa034de66124c2c00224f238edf8981cd9a4ad6637",
    "config/asms_unit_labware_movement.json": "78e68e5e5d7374fcfe9716207d06aff68d048fbd5fa18a9698291af5be31a7de",
    "config/asms_unit_operations.json": "0ddcdbce79364e57bd4f70681654b640af3c4f3ddc4c406d0cd202ebfc5944ae",
}
SERVICES = (
    "opentrons-robot-server",
    "opentrons-status-bar",
    "opentrons-gpio-setup",
    "opentrons-status-leds",
)
CONFIG_FILES = (
    "config/flex_config.json",
    "config/flex_unit_operations.json",
    "config/asms_unit_labware_movement.json",
    "config/asms_unit_operations.json",
)
CONFIG_HASH_CODE = 'import hashlib,sys; h=hashlib.sha256(); [h.update(open(p,"rb").read()) for p in sys.argv[1:]]; print(h.hexdigest())'


def wrapper_source(kind, policy_path):
    entry = (
        [sys.executable, "setup"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "academy.companion.installer"]
    )
    mode = "_python3" if kind == "python3" else "_transport"
    arguments = [mode, str(policy_path)] if kind == "python3" else [mode, kind, str(policy_path)]
    return "#!/bin/sh\nexec " + shlex.join([*entry, *arguments]) + ' "$@"\n'


def run_reviewed_python(policy, arguments):
    """Bundled Python supports only the reviewed deploy hook's two local helpers."""
    workspace = Path(policy["workspace"])
    if arguments[:2] == ["-c", CONFIG_HASH_CODE]:
        expected = [str(workspace / path) for path in CONFIG_FILES]
        if arguments[2:] != expected:
            raise ValueError("Configuration hash helper targets were changed")
        combined = hashlib.sha256()
        for path in CONFIG_FILES:
            value = _read_owned(workspace / path)
            if hashlib.sha256(value).hexdigest() != REVIEWED_FILES[path]:
                raise ValueError("Reviewed configuration changed")
            combined.update(value)
        print(combined.hexdigest())
        return
    script = workspace / "scripts/artifact_manifest.py"
    if (
        len(arguments) < 3
        or arguments[0] != str(script)
        or arguments[1] not in {"verify", "field"}
        or arguments[2] != str(workspace / "dist_arm")
        or hashlib.sha256(_read_owned(script)).hexdigest()
        != REVIEWED_FILES["scripts/artifact_manifest.py"]
    ):
        raise ValueError("Only the exact reviewed artifact verifier may execute")
    previous = sys.argv
    try:
        sys.argv = arguments
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = previous


class InstallerRecipe(StrictModel):
    schema_version: Literal["academy.flex-installer/1"]
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    artifact_sha256: str = Field(pattern=DIGEST)
    files: dict[str, str]
    qualification_report_sha256: str = Field(pattern=DIGEST)
    no_motion_startup_verified: Literal[True]
    service_switch_verified: Literal[True]
    rollback_verified: Literal[True]

    @model_validator(mode="after")
    def reviewed_source(self):
        if self.source_commit != SOURCE_COMMIT or self.files != REVIEWED_FILES:
            raise ValueError("Installer hooks/configuration are not the reviewed source recipe")
        return self

    @property
    def sha256(self):
        return digest(self.model_dump(mode="json"))


class InstallerRequest(StrictModel):
    operation_id: UUID
    installation_id: UUID
    instrument: Literal["flex", "ot2"]
    platform: Literal["macos", "linux"]
    ssh_host: str
    known_hosts: str
    identity_file: str
    robot_url: str
    profile: RobotProfile
    sila_certificate_file: str | None = None

    @model_validator(mode="after")
    def local_target(self):
        address = ipaddress.ip_address(self.ssh_host)
        if (
            address.version != 4
            or not address.is_private
            or address.is_loopback
            or address.is_link_local
        ):
            raise ValueError("Installer requires an explicit private IPv4 robot address")
        if str(address) != self.ssh_host:
            raise ValueError("Use a canonical IPv4 address")
        self.robot_url = validate_url(self.robot_url, robot=True)
        from urllib.parse import urlsplit

        target = urlsplit(self.robot_url)
        if target.hostname != self.ssh_host or target.port != 31950:
            raise ValueError(
                "HTTP identity and strict SSH must target the same robot on port 31950"
            )
        if self.instrument != "flex" or self.profile.instrument != "flex":
            raise ValueError(
                "OT-2 has no qualified transactional installer/runtime identity contract"
            )
        return self


def run_process(argv, *, input=b"", cwd=None, env=None, timeout=900):
    # The adapter never retries subprocesses. In particular a failed SSH response
    # may follow a successful remote mutation.
    return subprocess.run(
        argv,
        input=input,
        cwd=cwd,
        env=env,
        timeout=timeout,
        check=True,
        capture_output=True,
    ).stdout


def _read_owned(path: Path, *, secret=False):
    if secret:
        return read_private(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o022
            or info.st_size > 4_000_000
        ):
            raise ValueError("Host trust file must be user-owned and not writable by others")
        return os.read(fd, 4_000_001)
    finally:
        os.close(fd)


def artifact_inventory(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Prepared artifact contains a symlink")
        if path.is_dir():
            continue
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError("Prepared artifact is not a private regular file")
            hasher = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
            result[str(path.relative_to(directory))] = hasher.hexdigest()
    return result


def ssh_argv(kind, args, policy):
    """Every SSH/SCP subprocess is restricted to the frozen local target and keys."""
    target = "root@" + policy["host"]
    options = [
        "-F",
        "/dev/null",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "UserKnownHostsFile=" + policy["known_hosts"],
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "IdentityAgent=none",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ProxyCommand=none",
        "-o",
        "ProxyJump=none",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "ConnectTimeout=10",
        "-i",
        policy["identity_file"],
    ]
    if kind == "ssh":
        if not args or args[0] != target:
            raise ValueError("The reviewed hook attempted an unexpected SSH target/options")
        return ["/usr/bin/ssh", *options, *args]
    if kind != "scp":
        raise ValueError("Unknown SSH transport")
    args = list(args)
    legacy = [args.pop(0)] if args and args[0] == "-O" else []
    if len(args) < 2 or any(value.startswith("-") for value in args):
        raise ValueError("The reviewed hook attempted unsupported SCP options")
    remote = args[-1]
    if not remote.startswith(target + ":") or not re.fullmatch(
        r"(?:/root/unitelabs-flex-upload-[A-Za-z0-9._-]+/(?:[A-Za-z0-9._-]+)?|/data/start_connector.sh)",
        remote[len(target) + 1 :],
    ):
        raise ValueError("SCP destination is outside the reviewed installation paths")
    workspace = Path(policy["workspace"]).resolve()
    for source in args[:-1]:
        resolved = Path(source).resolve(strict=True)
        if not resolved.is_relative_to(workspace) or not resolved.is_file():
            raise ValueError("SCP source is outside the verified snapshot")
    return ["/usr/bin/scp", *options, *legacy, *args]


# Only fixed read-only observations are executed here. No shell configuration is sourced.
READ_STATUS = r"""
import json, os, re, stat, subprocess, urllib.request
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError('Identity redirects are forbidden')
def get(path):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    request=urllib.request.Request('http://127.0.0.1:31950'+path,headers={'Opentrons-Version':'3'})
    with opener.open(request, timeout=10) as r:
        return json.load(r)
def active(name):
    return subprocess.run(['systemctl','is-active','--quiet',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0
health=get('/health'); runs=get('/runs?pageLength=1')
links=runs.get('links')
if not isinstance(links,dict) or 'current' not in links: raise ValueError('Missing authoritative current-run link')
idle=links['current'] is None
env='/var/lib/unitelabs-opentrons-flex/run-mutation.env'
valid=False
if os.path.exists(env):
    s=os.lstat(env)
    if stat.S_ISREG(s.st_mode) and s.st_uid==0 and not s.st_mode&0o077:
        lines=open(env).read(4096).splitlines()
        values=dict(line.split('=',1) for line in lines if '=' in line)
        valid=(len(lines)==2 and set(values)=={'UNITELABS_RUN_MUTATION_TOKEN','UNITELABS_RUN_MUTATION_ACTOR'} and
          re.fullmatch(r'[A-Za-z0-9_-]{43,128}',values['UNITELABS_RUN_MUTATION_TOKEN']) is not None and
          re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',values['UNITELABS_RUN_MUTATION_ACTOR']) is not None)
active_path='/var/sila2_flex'; previous='/var/lib/unitelabs-opentrons-flex/previous-release'
kind='versioned' if os.path.islink(active_path) else 'legacy' if os.path.isdir(active_path) else 'missing'
print(json.dumps({'health':health,'idle':idle,
 'services':{name:active(name) for name in ['sila2-connector','opentrons-robot-server','opentrons-status-bar','opentrons-gpio-setup','opentrons-status-leds']},
 'credential_exists':os.path.lexists(env),'credential_valid':valid,
 'operation_lock_exists':os.path.lexists('/var/lib/unitelabs-opentrons-flex/operation.lock'),
 'active_release_kind':kind,'active_release':os.path.realpath(active_path) if kind!='missing' else None,
 'previous_release':open(previous).read(1024).strip() if os.path.isfile(previous) else None,
 'previous_release_exists':os.path.isfile(previous)}))
"""

CREATE_CREDENTIAL = r"""
import json, os, re, stat, tempfile
data=json.load(__import__('sys').stdin)
if set(data)!={'actor','secret'} or not re.fullmatch(r'academy-[a-f0-9-]{36}',data['actor']) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}',data['secret']): raise ValueError('Invalid credential envelope')
directory='/var/lib/unitelabs-opentrons-flex'; target=directory+'/run-mutation.env'
if os.path.islink(directory): raise ValueError('State directory cannot be a symlink')
os.makedirs(directory,mode=0o700,exist_ok=True)
if os.stat(directory).st_uid!=0 or os.stat(directory).st_mode&0o022: raise ValueError('Untrusted state directory')
fd,path=tempfile.mkstemp(prefix='.academy-credential-',dir=directory)
try:
    os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as stream:
        stream.write('UNITELABS_RUN_MUTATION_TOKEN='+data['secret']+'\nUNITELABS_RUN_MUTATION_ACTOR='+data['actor']+'\n')
        stream.flush(); os.fsync(stream.fileno())
    os.link(path,target) # Atomic create-only; a pre-existing credential is never replaced.
    parent=os.open(directory,os.O_RDONLY); os.fsync(parent); os.close(parent)
finally:
    os.unlink(path)
print('{"created":true}')
"""


class InstallJournal:
    def __init__(self, state):
        self.state = private_directory(state)
        self.fd = os.open(state / "installer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            path = state / "installer.sqlite3"
            if path.exists() or path.is_symlink():
                check_private_database(path)
            else:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS installs (id TEXT PRIMARY KEY, request TEXT NOT NULL, phase TEXT NOT NULL, receipt TEXT, resolution TEXT)"
            )
            self.db.commit()
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        self.db.close()
        os.close(self.fd)

    def get(self, operation_id):
        row = self.db.execute("SELECT * FROM installs WHERE id=?", (str(operation_id),)).fetchone()
        return dict(row) if row else None

    def begin(self, operation_id, request, *, rollback_of=None, resolving_ids=()):
        old = self.get(operation_id)
        if old:
            if old["request"] != canonical(request).decode():
                raise ValueError("Operation identity changed")
            if old["receipt"] is None:
                raise RuntimeError(
                    "Prior install response is unknown; inspect, then explicitly roll back"
                )
            return json.loads(old["receipt"])
        unresolved = self.db.execute(
            "SELECT id FROM installs WHERE resolution IS NULL AND (receipt IS NULL OR json_extract(receipt,'$.status')='unknown')"
        ).fetchall()
        allowed = {rollback_of, *(str(value) for value in resolving_ids)}
        if any(row["id"] not in allowed for row in unresolved):
            raise RuntimeError("Unresolved installation blocks a new operation")
        with self.db:
            self.db.execute(
                "INSERT INTO installs(id,request,phase) VALUES(?,?,'prepared')",
                (str(operation_id), canonical(request).decode()),
            )
        return None

    def phase(self, operation_id, phase):
        with self.db:
            self.db.execute(
                "UPDATE installs SET phase=? WHERE id=? AND receipt IS NULL",
                (phase, str(operation_id)),
            )

    def finish(self, operation_id, receipt):
        row = self.get(operation_id)
        encoded = canonical(receipt).decode()
        if row["receipt"] is not None and row["receipt"] != encoded:
            raise ValueError("Install receipts are immutable")
        with self.db:
            self.db.execute(
                "UPDATE installs SET receipt=?,phase='terminal' WHERE id=?",
                (encoded, str(operation_id)),
            )
        return receipt

    def resolve(self, operation_id, original_id, receipt, *, related_id=None):
        """One transaction records recovery and resolves the original, never its history."""
        encoded = canonical(receipt).decode()
        row, original = self.get(operation_id), self.get(original_id)
        if not row or not original or row["receipt"] not in (None, encoded):
            raise ValueError("Recovery receipt conflicts with the immutable journal")
        if original["resolution"] not in (None, encoded):
            raise ValueError("This installation already has a different resolution")
        related = self.get(related_id) if related_id else None
        if related_id and (not related or related["resolution"] not in (None, encoded)):
            raise ValueError("Related recovery has a different resolution")
        with self.db:
            self.db.execute(
                "UPDATE installs SET receipt=?,phase='terminal' WHERE id=?",
                (encoded, str(operation_id)),
            )
            self.db.execute(
                "UPDATE installs SET resolution=? WHERE id=?", (encoded, str(original_id))
            )
            if related_id:
                self.db.execute(
                    "UPDATE installs SET resolution=? WHERE id=?", (encoded, str(related_id))
                )
        return receipt


class Installer:
    def __init__(
        self, state_dir: Path, *, runner=run_process, observer=None, catalog=approved_release
    ):
        if os.name != "posix":
            raise ValueError(
                "This installer requires macOS/Linux file protection and process locks"
            )
        self.journal = InstallJournal(state_dir)
        self.runner, self.observer, self.catalog = runner, observer, catalog

    def close(self):
        self.journal.close()

    def _snapshot(self, repository, recipe, destination):
        archive = self.runner(
            [
                "/usr/bin/git",
                "-C",
                str(repository),
                "archive",
                "--format=tar",
                recipe.source_commit,
                *recipe.files,
            ],
            timeout=30,
        )
        if len(archive) > 5_000_000:
            raise ValueError("Reviewed source snapshot is oversized")
        destination.mkdir(mode=0o700)
        seen = set()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar:
                if member.isdir() and member.name.rstrip("/") in {"scripts", "config"}:
                    continue
                if not member.isfile() or member.name not in recipe.files or member.name in seen:
                    raise ValueError("Snapshot contains an unreviewed source file")
                seen.add(member.name)
                source = tar.extractfile(member)
                if source is None or member.size > 1_000_000:
                    raise ValueError("Invalid source member")
                content = source.read()
                if hashlib.sha256(content).hexdigest() != recipe.files[member.name]:
                    raise ValueError("Reviewed source checksum mismatch")
                path = destination / member.name
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(0o600)
        if seen != set(recipe.files):
            raise ValueError("Reviewed source snapshot is incomplete")

    def _policy(self, request, directory, workspace):
        known = _read_owned(Path(request.known_hosts))
        identity = _read_owned(Path(request.identity_file), secret=True)
        for name, value in (("known_hosts", known), ("identity", identity)):
            path = directory / name
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
        policy = {
            "host": request.ssh_host,
            "known_hosts": str(directory / "known_hosts"),
            "identity_file": str(directory / "identity"),
            "workspace": str(workspace),
        }
        write_private(directory / "ssh-policy.json", policy)
        wrappers = directory / "bin"
        wrappers.mkdir(mode=0o700)
        for kind in ("ssh", "scp", "python3"):
            (wrappers / kind).write_text(wrapper_source(kind, directory / "ssh-policy.json"))
            (wrappers / kind).chmod(0o700)
        env = {
            "PATH": f"{wrappers}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(directory),
            "LC_ALL": "C",
        }
        return (
            policy,
            env,
            {
                "known_hosts_sha256": hashlib.sha256(known).hexdigest(),
                "identity_sha256": hashlib.sha256(identity).hexdigest(),
            },
        )

    def _ssh(self, policy, script, *, input=b""):
        return self.runner(
            ssh_argv(
                "ssh", ["root@" + policy["host"], "python3 -c " + shlex.quote(script)], policy
            ),
            input=input,
            timeout=60,
        )

    def _verify_prepared(self, request, saved, directory):
        workspace = directory / "source"
        policy = json.loads(read_private(directory / "ssh-policy.json"))
        expected = {
            "host": request.ssh_host,
            "known_hosts": str(directory / "known_hosts"),
            "identity_file": str(directory / "identity"),
            "workspace": str(workspace),
        }
        if policy != expected:
            raise ValueError("Prepared SSH target or trust paths changed")
        for name, key in (("known_hosts", "known_hosts_sha256"), ("identity", "identity_sha256")):
            if hashlib.sha256(read_private(directory / name)).hexdigest() != saved[key]:
                raise ValueError("Prepared SSH host trust or identity changed")
        recipe = InstallerRecipe.model_validate(saved["recipe"])
        for name, expected_hash in recipe.files.items():
            if hashlib.sha256(_read_owned(workspace / name)).hexdigest() != expected_hash:
                raise ValueError("Prepared installer recipe changed")
        for kind in ("ssh", "scp", "python3"):
            if _read_owned(directory / "bin" / kind).decode() != wrapper_source(
                kind, directory / "ssh-policy.json"
            ):
                raise ValueError("Prepared transport wrapper changed")
        if artifact_inventory(workspace / "dist_arm") != saved["artifact_inventory"]:
            raise ValueError("Prepared runtime artifact changed")
        if (workspace / "config/flex_config.local.json").exists():
            raise ValueError("Unreviewed local configuration override is forbidden")
        return policy

    @staticmethod
    def _pointers(report):
        kind, active = report.get("active_release_kind"), report.get("active_release")
        previous = report.get("previous_release")
        managed = r"/var/lib/unitelabs-opentrons-flex/releases/[A-Za-z0-9._-]+"
        legacy = "/var/lib/unitelabs-opentrons-flex/legacy-pre-versioned-release"
        if (
            kind not in {"versioned", "legacy", "missing"}
            or kind == "versioned"
            and not (
                isinstance(active, str) and (re.fullmatch(managed, active) or active == legacy)
            )
            or kind == "legacy"
            and active != "/var/sila2_flex"
            or kind == "missing"
            and active is not None
            or previous is not None
            and not (
                isinstance(previous, str)
                and (re.fullmatch("release:" + managed, previous) or previous == "legacy:" + legacy)
            )
            or report.get("previous_release_exists") is not (previous is not None)
        ):
            raise ValueError("Observed release pointers are invalid or incomplete")
        return {"active_release_kind": kind, "active_release": active, "previous_release": previous}

    @staticmethod
    def _deployed_pointers(saved):
        initial = saved["initial_pointers"]
        previous = initial["previous_release"]
        if initial["active_release_kind"] == "legacy":
            previous = "legacy:/var/lib/unitelabs-opentrons-flex/legacy-pre-versioned-release"
        elif (
            initial["active_release_kind"] == "versioned"
            and initial["active_release"] != saved["expected_active_release"]
        ):
            prefix = (
                "legacy:"
                if initial["active_release"].endswith("/legacy-pre-versioned-release")
                else "release:"
            )
            previous = prefix + initial["active_release"]
        return {
            "active_release_kind": "versioned",
            "active_release": saved["expected_active_release"],
            "previous_release": previous,
        }

    def _recovery_action(self, saved, report):
        pointers = self._pointers(report)
        initial, deployed = saved["initial_pointers"], self._deployed_pointers(saved)
        if pointers == initial:
            return "stock-reconciled"
        if pointers != deployed:
            raise ValueError("Release pointers changed outside this recorded installation")
        if (
            initial["active_release_kind"] == "missing"
            or initial["active_release"] == deployed["active_release"]
        ):
            return "stock-reconciled"
        return "previous-release-restored"

    def _observe(self, request, policy, mode):
        if self.observer:
            report = self.observer(request, mode)
        else:
            report = json.loads(self._ssh(policy, READ_STATUS))
        health, services = report["health"], report["services"]
        if (health.get("robot_serial"), health.get("robot_model"), health.get("fw_version")) != (
            request.profile.serial,
            "OT-3 Standard",
            request.profile.firmware,
        ):
            raise ValueError("Observed robot identity differs from local installation request")
        if report.get("idle") is not True or report.get("operation_lock_exists") is not False:
            raise ValueError("Robot is not observably idle; installation cannot interrupt a run")
        if mode == "stock":
            if services.get("sila2-connector") or not services.get("opentrons-robot-server"):
                raise ValueError(
                    "Start in verified stock mode; switching a live connector requires separate operator action"
                )
        elif mode == "connector" and (
            not services.get("sila2-connector") or any(services.get(name) for name in SERVICES)
        ):
            raise ValueError("Exclusive connector hardware ownership was not established")
        if mode == "connector" and not self.observer:
            certificate = (
                read_private(Path(request.sila_certificate_file))
                if request.sila_certificate_file
                else None
            )
            engine = ProtocolEngine(request.robot_url, request.profile, certificate=certificate)
            try:
                engine.probe()
                engine._assert_idle()
            finally:
                engine.close()
        return report

    def install(
        self,
        request: InstallerRequest,
        recipe: InstallerRecipe,
        source_repo: Path,
        archive: Path,
        *,
        approve,
    ):
        request.profile.assert_current()
        release = self.catalog("flex", request.platform)
        if (
            not release
            or release.get("status") != "approved"
            or release.get("instrument") != request.instrument
            or release.get("platform") != request.platform
            or release.get("execution_transport") != "opentrons-protocol-engine"
            or request.profile.firmware not in release.get("supported_firmware", [])
            or release.get("installer_recipe_sha256") != recipe.sha256
            or release.get("source_commit") != recipe.source_commit
            or release.get("artifact_sha256") != recipe.artifact_sha256
            or any(
                release.get(name) != getattr(request.profile, name)
                for name in (
                    "source_commit",
                    "release_id",
                    "artifact_sha256",
                    "runtime_contract_id",
                    "runtime_release_id",
                    "runtime_bundle_sha256",
                )
            )
        ):
            raise ValueError("No catalog-approved exact installer recipe and release are available")
        identity = {
            "request": request.model_dump(mode="json"),
            "recipe": recipe.model_dump(mode="json"),
            "recipe_sha256": recipe.sha256,
            "profile_sha256": request.profile.sha256,
        }
        old = self.journal.get(request.operation_id)
        if old:
            saved = json.loads(old["request"])
            if any(saved.get(key) != value for key, value in identity.items()):
                raise ValueError("Previously attempted install binding changed")
            if old["receipt"]:
                return json.loads(old["receipt"])
            raise RuntimeError("Previous install outcome is unknown; no automatic replay")
        directory = self.journal.state / str(request.operation_id)
        # The exclusive installer lock and absent journal row prove this is only
        # local preflight staging. A recorded attempt is never discarded/replayed.
        if directory.exists() or directory.is_symlink():
            shutil.rmtree(directory)
        directory.mkdir(mode=0o700)
        try:
            workspace = directory / "source"
            self._snapshot(source_repo, recipe, workspace)
            stage_archive(archive, recipe.artifact_sha256, workspace / "dist_arm")
            config = json.loads((workspace / "config/flex_config.json").read_text())
            server = config.get("sila_server", {})
            if (
                server.get("uuid"),
                server.get("port"),
                server.get("tls"),
                config.get("use_simulator"),
                config.get("with_robot_server"),
            ) != (
                str(request.profile.sila_server_uuid),
                request.profile.sila_port,
                request.profile.sila_tls,
                False,
                True,
            ):
                raise ValueError(
                    "Reviewed install configuration does not match the local live profile"
                )
            policy, env, trust = self._policy(request, directory, workspace)
            identity.update(trust)
            identity["artifact_inventory"] = artifact_inventory(workspace / "dist_arm")
            manifest = json.loads(_read_owned(workspace / "dist_arm/runtime-manifest.json"))
            if manifest.get("releaseId") != request.profile.runtime_release_id or not re.fullmatch(
                r"[A-Za-z0-9._-]+", manifest.get("releaseId", "")
            ):
                raise ValueError(
                    "Staged runtime release identity differs from the approved profile"
                )
            config_hash = hashlib.sha256(
                b"".join(_read_owned(workspace / name) for name in CONFIG_FILES)
            ).hexdigest()
            identity["expected_active_release"] = (
                "/var/lib/unitelabs-opentrons-flex/releases/"
                + manifest["releaseId"]
                + "-cfg"
                + config_hash[:12]
            )
            initial = self._observe(request, policy, "stock")
            identity["initial_pointers"] = self._pointers(initial)
            if initial.get("credential_exists") and not initial.get("credential_valid"):
                raise ValueError(
                    "Existing mutation credential is invalid; it will never be overwritten"
                )
            if not approve(
                {
                    "action": "install-and-switch-to-connector",
                    "serial": request.profile.serial,
                    "host": request.ssh_host,
                    "recipe_sha256": recipe.sha256,
                    "bootstrap_credential": not initial.get("credential_exists"),
                }
            ):
                return {
                    "status": "declined",
                    "operation_id": str(request.operation_id),
                    "mutation_attempted": False,
                }
            self.journal.begin(request.operation_id, identity)
        finally:
            # Consult the durable row even if begin() committed and then failed.
            if self.journal.get(request.operation_id) is None:
                shutil.rmtree(directory)
        try:
            self._verify_prepared(request, identity, directory)
            fresh = self._observe(request, policy, "stock")
            if self._pointers(fresh) != identity["initial_pointers"]:
                raise ValueError("Robot release changed while awaiting local confirmation")
            if fresh.get("credential_exists") and not fresh.get("credential_valid"):
                raise ValueError("Existing mutation credential changed or is invalid")
            if not fresh.get("credential_exists"):
                credential = {
                    "actor": "academy-" + str(request.installation_id),
                    "secret": secrets.token_urlsafe(32),
                }
                write_private(directory / "mutation-credential.json", credential)
                self.journal.phase(request.operation_id, "credential-create-attempted")
                self._ssh(policy, CREATE_CREDENTIAL, input=canonical(credential))
                if not self._observe(request, policy, "stock").get("credential_valid"):
                    raise ValueError("Credential creation was not confirmed")
            for phase, relative, arguments in (
                ("deploy-attempted", "deploy.sh", [request.ssh_host, "dist_arm"]),
                (
                    "service-switch-attempted",
                    "scripts/install_connector_service.sh",
                    [request.ssh_host],
                ),
            ):
                self._verify_prepared(request, identity, directory)
                fresh = self._observe(request, policy, "stock")
                expected_pointers = (
                    identity["initial_pointers"]
                    if phase == "deploy-attempted"
                    else self._deployed_pointers(identity)
                )
                if self._pointers(fresh) != expected_pointers or not fresh.get("credential_valid"):
                    raise ValueError(
                        "Release or credential changed before the next installation step"
                    )
                self.journal.phase(request.operation_id, phase)
                self.runner(
                    ["/bin/sh", str(workspace / relative), *arguments],
                    cwd=workspace,
                    env=env,
                    timeout=900,
                )
            observed = self._observe(request, policy, "connector")
            if self._pointers(observed) != self._deployed_pointers(identity):
                raise ValueError("Installed release pointers do not match the approved attempt")
            receipt = {
                "status": "completed",
                "operation_id": str(request.operation_id),
                "request_sha256": digest(identity),
                "recipe_sha256": recipe.sha256,
                "profile_sha256": request.profile.sha256,
                "serial": request.profile.serial,
                "observed_sha256": digest(observed),
                "completed_at": time.time(),
                "physical_workflow_executed": False,
            }
        except BaseException as exc:
            receipt = {
                "status": "unknown",
                "operation_id": str(request.operation_id),
                "request_sha256": digest(identity),
                "error_type": type(exc).__name__,
                "automatic_replay_allowed": False,
                "recorded_at": time.time(),
            }
            self.journal.finish(request.operation_id, receipt)
            raise RuntimeError(
                "Installation outcome is unknown; inspect and explicitly roll back"
            ) from None
        return self.journal.finish(request.operation_id, receipt)

    def rollback(self, original_operation_id: UUID, rollback_id: UUID, *, approve):
        original = self.journal.get(original_operation_id)
        if not original:
            raise ValueError("No original installation record")
        if original["resolution"]:
            result = json.loads(original["resolution"])
            if result["operation_id"] != str(rollback_id):
                raise ValueError(
                    "This installation is already resolved; rollback cannot be repeated"
                )
            return result
        saved = json.loads(original["request"])
        request = InstallerRequest.model_validate(saved["request"])
        directory = self.journal.state / str(original_operation_id)
        identity = {
            "rollback_of": str(original_operation_id),
            "original_request_sha256": digest(saved),
        }
        old = self.journal.get(rollback_id)
        if old:
            if old["request"] != canonical(identity).decode():
                raise ValueError("Recovery identity changed")
            if old["receipt"]:
                result = json.loads(old["receipt"])
                if result["status"] == "completed":
                    return self.journal.resolve(rollback_id, original_operation_id, result)
                return result
            raise RuntimeError("Previous recovery outcome is unknown; no automatic replay")
        policy = self._verify_prepared(request, saved, directory)
        before = self._observe(request, policy, "rollback-preflight")
        action = self._recovery_action(saved, before)
        if not approve(
            {
                "action": "rollback-to-previous-release-and-stock-services",
                "recovery_action": action,
                "serial": request.profile.serial,
                "host": request.ssh_host,
                "original_operation_id": str(original_operation_id),
            }
        ):
            return {"status": "declined", "mutation_attempted": False}
        self.journal.begin(rollback_id, identity, rollback_of=str(original_operation_id))
        try:
            # Revalidate after an unbounded local prompt. Recovery never interrupts a run.
            policy = self._verify_prepared(request, saved, directory)
            status = self._observe(request, policy, "rollback-preflight")
            if self._recovery_action(saved, status) != action or self._pointers(
                status
            ) != self._pointers(before):
                raise ValueError("Robot release changed during recovery confirmation")
            workspace = directory / "source"
            env = {
                "PATH": f"{directory / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": str(directory),
                "LC_ALL": "C",
            }
            relative = None
            arguments = [request.ssh_host]
            if action == "previous-release-restored":
                relative, phase = "scripts/rollback_connector.sh", "rollback-attempted"
            elif status["services"].get("sila2-connector") or not status["services"].get(
                "opentrons-robot-server"
            ):
                relative, phase = "scripts/switch_mode.sh", "stock-switch-attempted"
                arguments.append("opentrons")
                action = "stock-services-restored"
            if relative:
                self.journal.phase(rollback_id, phase)
                self.runner(
                    ["/bin/sh", str(workspace / relative), *arguments],
                    cwd=workspace,
                    env=env,
                    timeout=900,
                )
            observed = self._observe(request, policy, "stock")
            after_pointers = self._pointers(observed)
            if action == "previous-release-restored":
                target = self._deployed_pointers(saved)["previous_release"].split(":", 1)[1]
                expected = {
                    "active_release_kind": "versioned",
                    "active_release": target,
                    "previous_release": "release:" + saved["expected_active_release"],
                }
                if after_pointers != expected:
                    raise ValueError(
                        "Rollback did not restore this attempt's bound previous release"
                    )
            elif after_pointers != self._pointers(status):
                raise ValueError("Stock recovery unexpectedly changed release pointers")
            receipt = {
                "status": "completed",
                "operation_id": str(rollback_id),
                "rollback_of": str(original_operation_id),
                "recovery_action": action,
                "observed_sha256": digest(observed),
                "completed_at": time.time(),
                "replay_authorized": False,
            }
            return self.journal.resolve(rollback_id, original_operation_id, receipt)
        except BaseException as exc:
            self.journal.finish(
                rollback_id,
                {
                    "status": "unknown",
                    "operation_id": str(rollback_id),
                    "rollback_of": str(original_operation_id),
                    "error_type": type(exc).__name__,
                    "automatic_replay_allowed": False,
                },
            )
            raise RuntimeError("Rollback outcome is unknown; no automatic replay") from None

    def reconcile(
        self, original_operation_id: UUID, recovery_id: UUID, resolution_id: UUID, *, approve
    ):
        """Explicit read-only recovery after a lost rollback response; never rerun its hook."""
        original, recovery = self.journal.get(original_operation_id), self.journal.get(recovery_id)
        if not original or not recovery:
            raise ValueError("Original installation and recovery records are required")
        if original["resolution"]:
            receipt = json.loads(original["resolution"])
            if receipt["operation_id"] != str(resolution_id):
                raise ValueError("This installation is already resolved")
            return receipt
        saved = json.loads(original["request"])
        expected_recovery = {
            "rollback_of": str(original_operation_id),
            "original_request_sha256": digest(saved),
        }
        if json.loads(recovery["request"]) != expected_recovery or (
            recovery["receipt"] and json.loads(recovery["receipt"])["status"] != "unknown"
        ):
            raise ValueError("Only this installation's unknown recovery can be reconciled")
        request = InstallerRequest.model_validate(saved["request"])
        directory = self.journal.state / str(original_operation_id)

        def observe_stock():
            policy = self._verify_prepared(request, saved, directory)
            report = self._observe(request, policy, "stock")
            pointers = self._pointers(report)
            allowed = [saved["initial_pointers"], self._deployed_pointers(saved)]
            previous = self._deployed_pointers(saved)["previous_release"]
            if previous and saved["initial_pointers"]["active_release_kind"] != "missing":
                allowed.append(
                    {
                        "active_release_kind": "versioned",
                        "active_release": previous.split(":", 1)[1],
                        "previous_release": "release:" + saved["expected_active_release"],
                    }
                )
            if pointers not in allowed:
                raise ValueError("Observed stock release belongs to another operation")
            return report

        before = observe_stock()
        if not approve(
            {
                "action": "reconcile-unknown-recovery-without-replay",
                "serial": request.profile.serial,
                "host": request.ssh_host,
                "original_operation_id": str(original_operation_id),
                "recovery_id": str(recovery_id),
            }
        ):
            return {"status": "declined", "mutation_attempted": False}
        after = observe_stock()
        if self._pointers(before) != self._pointers(after):
            raise ValueError("Release changed during read-only reconciliation")
        identity = {
            "reconciles_installation": str(original_operation_id),
            "reconciles_recovery": str(recovery_id),
            "original_request_sha256": digest(saved),
        }
        prepared = self.journal.get(resolution_id)
        if prepared and prepared["receipt"] is None:
            # This phase has no remote mutation. Reuse only the exact prepared
            # read-only identity after fresh observations and local approval.
            if (
                prepared["phase"] != "prepared"
                or prepared["request"] != canonical(identity).decode()
            ):
                raise ValueError("Prepared reconciliation identity changed")
            existing = None
        else:
            existing = self.journal.begin(
                resolution_id, identity, resolving_ids=(original_operation_id, recovery_id)
            )
        if existing:
            return existing
        receipt = {
            "status": "completed",
            "operation_id": str(resolution_id),
            "rollback_of": str(original_operation_id),
            "reconciled_recovery_id": str(recovery_id),
            "recovery_action": "read-only-stock-reconciliation",
            "observed_sha256": digest(after),
            "completed_at": time.time(),
            "replay_authorized": False,
            "mutation_attempted": False,
        }
        return self.journal.resolve(
            resolution_id, original_operation_id, receipt, related_id=recovery_id
        )


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_python3":
        _, policy_path, *arguments = argv
        run_reviewed_python(json.loads(read_private(Path(policy_path))), arguments)
        return
    if argv and argv[0] == "_transport":
        _, kind, policy_path, *arguments = argv
        policy = json.loads(read_private(Path(policy_path)))
        command = ssh_argv(kind, arguments, policy)
        os.execv(command[0], command)
    parser = argparse.ArgumentParser(
        description="Locally supervised, reviewed Flex connector installer"
    )
    commands = parser.add_subparsers(dest="action", required=True)
    schema = commands.add_parser("schema", help="Print configuration schema without robot access")
    schema.add_argument("model", choices=("request", "recipe"))
    install = commands.add_parser("install")
    for name in ("request", "recipe", "source-repo", "archive"):
        install.add_argument("--" + name, type=Path, required=True)
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--operation-id", type=UUID, required=True)
    rollback.add_argument("--rollback-id", type=UUID, required=True)
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--operation-id", type=UUID, required=True)
    reconcile.add_argument("--recovery-id", type=UUID, required=True)
    reconcile.add_argument("--resolution-id", type=UUID, required=True)
    args = parser.parse_args(argv)
    if args.action == "schema":
        model = InstallerRequest if args.model == "request" else InstallerRecipe
        print(json.dumps(model.model_json_schema(), indent=2))
        return
    if not sys.stdin.isatty():
        raise ValueError("Installation and service switching require a local operator terminal")
    os.umask(0o077)

    def confirm(summary):
        print(json.dumps(summary, indent=2))
        print(
            "This changes robot software and hardware service ownership. It does not run a workflow."
        )
        verb = {"install": "INSTALL", "rollback": "ROLLBACK", "reconcile": "RECONCILE"}[args.action]
        return input(f"Type {verb} to confirm this specific action: ").strip() == verb

    # A fixed production journal prevents a new folder from silently bypassing
    # an unresolved attempt. The class accepts a path for isolated software tests.
    state = private_directory(Path.home() / ".local/share/academy-companion")
    # Installation and workflow execution share one local process lock. A waiting
    # companion cannot begin a run between an idle observation and a service switch.
    with Journal(state) as run_journal:
        if run_journal.unfinished() or run_journal.unresolved():
            raise RuntimeError(
                "Reconcile the prior physical workflow before changing robot software"
            )
        installer = Installer(state / "installer")
        try:
            if args.action == "install":
                result = installer.install(
                    InstallerRequest.model_validate_json(read_private(args.request)),
                    InstallerRecipe.model_validate_json(read_private(args.recipe)),
                    args.source_repo,
                    args.archive,
                    approve=confirm,
                )
            elif args.action == "rollback":
                result = installer.rollback(args.operation_id, args.rollback_id, approve=confirm)
            else:
                result = installer.reconcile(
                    args.operation_id, args.recovery_id, args.resolution_id, approve=confirm
                )
            print(json.dumps(result, indent=2))
        finally:
            installer.close()


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(
            f"Installer stopped ({type(exc).__name__}); inspect the private journal. No automatic retry.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
