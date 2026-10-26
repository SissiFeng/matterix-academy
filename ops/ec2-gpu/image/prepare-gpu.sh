#!/usr/bin/env bash
# Prepare the reviewed Ubuntu kernel before uploading private image inputs.
set -euo pipefail
umask 077
[[ "$EUID" == 0 && "$(uname -m)" == x86_64 ]]
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]]
printf 'blacklist nouveau\noptions nouveau modeset=0\n' > /etc/modprobe.d/academy-nouveau.conf
update-initramfs -u
if lsmod | awk '{print $1}' | grep -qx nouveau; then
  printf '%s\n' 'Nouveau is loaded; rebooting to apply the reviewed blacklist before driver installation.'
  sync
  reboot
fi
