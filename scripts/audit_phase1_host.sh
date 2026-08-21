#!/bin/sh
set -eu

echo 'Host identity and operating system'
hostname
uname -a
if [ -r /etc/os-release ]; then
  sed -n '1,12p' /etc/os-release
fi

echo 'Capacity'
df -h / /ops 2>/dev/null || df -h /
free -h 2>/dev/null || true

echo 'Container runtime'
docker version --format 'server={{.Server.Version}}' 2>/dev/null || true
docker compose version 2>/dev/null || true
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true

echo 'Listening sockets'
ss -lntu 2>/dev/null || true

echo 'Firewall status'
if command -v ufw >/dev/null 2>&1; then
  sudo -n ufw status verbose 2>/dev/null || ufw status verbose 2>/dev/null || true
fi

echo 'Repository state'
for repository in /ops/anshin-phone-infra /ops/anshin-phone-infra/anshin-phone-backend; do
  if git -C "$repository" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf '%s\n' "$repository"
    git -C "$repository" branch --show-current
    git -C "$repository" rev-parse --short HEAD
    git -C "$repository" status --short
  fi
done
