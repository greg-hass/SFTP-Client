# Tailscale Connection Setup

## Option 1: Use Tailscale IP Address (Recommended)

Find your device's Tailscale IP:

```bash
# On the target device (raspberrypi), run:
tailscale ip -4
# Example output: 100.x.y.z
```

Use this IP (e.g., `100.64.1.1`) as the host instead of `raspberrypi`.

## Option 2: Use Tailscale Hostname with Docker

### macOS

Docker Desktop on macOS cannot resolve Tailscale MagicDNS names directly.

**Workaround - Add to /etc/hosts:**

1. Get the Tailscale IP of your device:
```bash
# From your Mac or the target device
tailscale status | grep raspberrypi
# Or on the raspberrypi:
tailscale ip -4
```

2. Add to your Mac's `/etc/hosts`:
```bash
sudo sh -c 'echo "100.x.y.z raspberrypi" >> /etc/hosts'
```

3. Restart the container:
```bash
docker-compose restart
```

### Linux

Use host networking mode in docker-compose.yml:

```yaml
services:
  sftp-client:
    network_mode: host
    # ... rest of config
```

Then access via `http://localhost:8040`

## Option 3: Run without Docker

If Tailscale DNS is essential, run the Python app directly:

```bash
cd /Users/greg/Projects/sftp-client
pip3 install -r requirements.txt
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8040
```

## Finding Your Tailscale IPs

```bash
# List all devices in your tailnet
tailscale status

# Get IP of specific device
tailscale ip -4 raspberrypi
```

## SSH Key Setup for Tailscale

For passwordless auth with Tailscale SSH:

```bash
# Generate key pair (on your Mac)
ssh-keygen -t ed25519 -f ~/.ssh/tailscale -C "your-email"

# Copy public key to raspberrypi
cat ~/.ssh/tailscale.pub | ssh raspberrypi 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys'

# Test connection
ssh -i ~/.ssh/tailscale user@raspberrypi
```

Then use the private key file when connecting via the web UI.
