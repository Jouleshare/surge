# Surge — AMPD VPS deployment

Standalone Flask/WhatsApp service for AMPD Surge. This repository contains the approved deployable application and product context only; it is not an OpenClaw agent transfer.

## Dependencies

The service requires:

- Python 3.11+
- network access to `https://loadout.getjoule.co.uk/api/calculate`
- network access to `https://deploy.getjoule.co.uk/api/manufacturers`
- Meta WhatsApp Cloud API credentials for inbound/outbound WhatsApp
- Resend credentials if lead notifications are enabled

## VPS install

```bash
sudo useradd --system --home /opt/surge --shell /usr/sbin/nologin surge
sudo mkdir -p /opt/surge /var/lib/surge /etc/surge
sudo chown -R surge:surge /opt/surge /var/lib/surge
git clone <private-repository-url> /opt/surge/current
sudo -u surge python3 -m venv /opt/surge/venv
sudo -u surge /opt/surge/venv/bin/pip install --upgrade pip
sudo -u surge /opt/surge/venv/bin/pip install -r /opt/surge/current/surge/requirements.txt
sudo cp /opt/surge/current/.env.example /etc/surge/surge.env
sudo chmod 600 /etc/surge/surge.env
sudoedit /etc/surge/surge.env
```

Install `deploy/surge.service` as `/etc/systemd/system/surge.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now surge
curl http://127.0.0.1:8010/healthz
```

Put `deploy/nginx.conf.example` behind the chosen AMPD hostname, obtain TLS, and point Meta's webhook to `/webhook`.

## Local test

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r surge/requirements.txt
PYTHONPATH=surge python tests/test_surge.py
```

The test uses temporary runtime storage and non-production test credentials. It does not call Meta, Resend, Loadout or Deploy.

## Operations

```bash
sudo journalctl -u surge -f
sudo systemctl restart surge
sudo systemctl status surge
```

Back up `/var/lib/surge` using AMPD's approved backup process. Never commit that directory: it contains leads, conversations and saved jobs.

## Required handover items from AMPD/Brand

1. Private repository access for the deployment operator.
2. A hostname and DNS record for the service.
3. Fresh Meta WhatsApp credentials and webhook verification token.
4. Fresh Resend key and approved notification address, if lead email is wanted.
5. A unique admin username/password stored outside git.
6. Confirmation that the VPS can reach the Loadout and Deploy APIs.
7. An AMPD owner for evidence approval, technical escalation and rate changes.
