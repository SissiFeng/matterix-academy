#!/usr/bin/env bash
# Runs only inside an explicitly authorized Packer Ubuntu build instance.
set -euo pipefail
umask 077
[[ "$EUID" == 0 && "$(uname -m)" == x86_64 ]]
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]]
if lsmod | awk '{print $1}' | grep -qx nouveau; then
  printf '%s\n' 'Nouveau is still loaded after GPU preparation; refusing payload extraction and driver installation.' >&2
  exit 1
fi
input=/tmp/academy-image-input
[[ -f "$input/release.json" && -f "$input/sources.json" && -f "$input/driver.json" ]]
# Verify every external payload before extraction or execution. No credential input is accepted.
python3 - "$input" "$RELEASE_SHA256" "$MANIFEST_SHA256" <<'PY'
import hashlib,json,pathlib,sys,tarfile
root=pathlib.Path(sys.argv[1]); release=json.loads((root/'release.json').read_text())
def verify(name,expected):
 h=hashlib.sha256()
 with (root/name).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 if h.hexdigest()!=expected:raise SystemExit('Image input checksum mismatch: '+name)
verify('academy.tar.gz',sys.argv[2]);verify('image-manifest.json',sys.argv[3])
assert release['archive_sha256']==sys.argv[2] and release['manifest_sha256']==sys.argv[3]
manifest=json.loads((root/'image-manifest.json').read_text())
assert manifest['academy_commit']==release['academy_commit']
verify('sources.json',manifest['sources_manifest_sha256'])
for name,record in json.loads((root/'sources.json').read_text()).items():
 assert name in ('engine','assets')
 assert record['commit']==manifest['engine_commit' if name=='engine' else 'asset_commit']
 verify(name+'.tar.gz',record['sha256'])
driver=json.loads((root/'driver.json').read_text())
assert driver['version']==manifest['driver_version'] and driver['version']=='595.58.03'
assert driver['sha256']=='8c0d4f967b7932c4ab5714272aee8103392b0a702c92afa555176d36205829f9'
verify('nvidia-driver.run',driver['sha256'])
for name,dest in [('academy','/opt/academy-agent'),('engine','/srv/matterix'),('assets','/srv/matterix-assets')]:
 target=pathlib.Path(dest)
 if target.exists():raise SystemExit('Build requires empty install paths')
 target.mkdir(parents=True)
 with tarfile.open(root/(name+'.tar.gz')) as archive:archive.extractall(target,filter='data')
PY
export DEBIAN_FRONTEND=noninteractive
apt-get update
mapfile -t packages < <(sed '/^#/d;/^[[:space:]]*$/d' /opt/academy-agent/ops/ec2-gpu/image/ubuntu-packages.txt)
apt-get install -y --no-install-recommends "${packages[@]}" "linux-headers-$(uname -r)"
# Requires an operator-supplied NVIDIA installer and independently reviewed SHA256.
if lsmod | awk '{print $1}' | grep -qx nouveau; then
  printf '%s\n' 'Nouveau is still loaded; refusing NVIDIA driver installation.' >&2
  exit 1
fi
sh "$input/nvidia-driver.run" --silent --dkms --no-questions --ui=none --kernel-module-type=open
# Bootstrap only uv from the hash-locked runtime requirements, then use the same lock for install.
python3.12 -m venv /opt/academy-build-tools
python3.12 /opt/academy-agent/scripts/ec2-gpu-bootstrap.py \
  --lock /opt/academy-agent/ops/ec2-gpu/runtime-linux-x86_64.lock --output /tmp/academy-bootstrap.lock
/opt/academy-build-tools/bin/pip install --require-hashes --no-deps -r /tmp/academy-bootstrap.lock
uv=/opt/academy-build-tools/bin/uv
"$uv" venv --python /usr/bin/python3.12 /opt/matterix-isaac
"$uv" pip install --python /opt/matterix-isaac/bin/python --require-hashes --no-deps -r /tmp/academy-bootstrap.lock
# flatdict is sdist-only; its hash is locked and the build uses the pinned tools above.
"$uv" pip install --python /opt/matterix-isaac/bin/python --require-hashes --no-deps --no-build-isolation \
  --index-strategy unsafe-best-match --index https://pypi.nvidia.com --index https://download.pytorch.org/whl/cu128 \
  -r /opt/academy-agent/ops/ec2-gpu/runtime-linux-x86_64.lock
"$uv" venv --python /usr/bin/python3.12 /opt/academy-agent/.venv
"$uv" pip install --python /opt/academy-agent/.venv/bin/python --require-hashes --no-deps \
  -r /opt/academy-agent/ops/ec2-gpu/agent-requirements.lock
# Independent Matterix modules are activated from their reviewed source paths by the adapter.
# .pth adds only the Academy backend to its agent environment; no source package is re-resolved.
agent_site=$(/opt/academy-agent/.venv/bin/python -c 'import site; print(site.getsitepackages()[0])')
printf '%s\n' /opt/academy-agent/app/backend > "$agent_site/academy.pth"
/opt/matterix-isaac/bin/python -m pip check
/opt/academy-agent/.venv/bin/python -m pip check 2>/dev/null || "$uv" pip check --python /opt/academy-agent/.venv/bin/python
# Retain the pinned publisher wheel so runtime inventory verifies installed payloads,
# including same-version code drift, rather than trusting package metadata alone.
install -d -m 755 /etc/academy-native/evidence
curl --fail --show-error --location --proto '=https' --proto-redir '=https' \
  --max-time 300 --max-filesize 16777216 \
  https://pypi.nvidia.com/isaaclab/isaaclab-3.0.0b2.post1-py3-none-any.whl \
  --output /etc/academy-native/evidence/isaaclab.whl
chmod 644 /etc/academy-native/evidence/isaaclab.whl
getent group video >/dev/null || groupadd --system video
getent group render >/dev/null || groupadd --system render
useradd --system --home-dir /var/cache/academy-native --shell /usr/sbin/nologin --groups video,render academy-native
install -d -m 755 /etc/academy-native
install -d -o academy-native -g academy-native -m 700 /var/lib/academy-native /var/cache/academy-native /run/academy-native
install -m 644 "$input/image-manifest.json" /etc/academy-native/image-manifest.json
install -m 644 "$input/release.json" /etc/academy-native/release.json
/opt/academy-agent/.venv/bin/python /opt/academy-agent/scripts/ec2-gpu-prepare.py \
  --manifest /etc/academy-native/image-manifest.json --output-dir /etc/academy-native
chmod 644 /etc/academy-native/native-config.json /etc/academy-native/image-manifest.sha256
install -m 644 /opt/academy-agent/ops/ec2-gpu/academy-native.service /etc/systemd/system/academy-native.service
# Persistent dedicated firewall; preserve the base host's other tables.
install -m 644 /opt/academy-agent/ops/ec2-gpu/block-imds.nft /etc/academy-native/block-imds.nft
cat > /etc/systemd/system/academy-imds.service <<'UNIT'
[Unit]
Description=Block unprivileged access to EC2 instance metadata
Before=academy-native.service
After=network-pre.target
[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/academy-native/block-imds.nft
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
mkdir -p /etc/systemd/system/academy-native.service.d
printf '[Unit]\nRequires=academy-imds.service\nAfter=academy-imds.service\n' > /etc/systemd/system/academy-native.service.d/metadata.conf
chmod -R a+rX,go-w /opt/academy-agent /opt/matterix-isaac /srv/matterix /srv/matterix-assets
systemctl daemon-reload
systemctl enable academy-imds.service
systemctl disable academy-native.service
# The reviewed base AMI must already contain SSM; never install a moving snap here.
if ! systemctl is-enabled snap.amazon-ssm-agent.amazon-ssm-agent.service >/dev/null 2>&1 && ! systemctl is-enabled amazon-ssm-agent.service >/dev/null 2>&1; then
  printf '%s\n' 'Reviewed base AMI must include an enabled SSM agent.' >&2
  exit 1
fi
# Native license acceptance is explicit in the reviewed image build configuration.
printf '[Service]\nEnvironment=OMNI_KIT_ACCEPT_EULA=YES\n' > /etc/systemd/system/academy-native.service.d/license.conf
rm -rf "$input" /tmp/academy-bootstrap.lock /opt/academy-build-tools /root/.cache/uv /root/.cache/pip
sync
reboot
