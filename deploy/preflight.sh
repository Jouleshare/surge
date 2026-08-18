#!/usr/bin/env bash
set -euo pipefail

test -f /etc/surge/surge.env
test "$(stat -c '%a' /etc/surge/surge.env)" = "600"
test -d /var/lib/surge
curl --fail --silent --show-error http://127.0.0.1:8010/healthz
echo
