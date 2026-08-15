# claude-code-vm

A Kasm desktop pinned to the GPU node, sized for large local model work.
Same shape as `remote-dev-vm`, with both GPUs, a much larger memory
reservation, and a persistent 500Gi home directory.

Reachable at `https://ccllm.homelab.com` once ingress resolves.

Nothing is installed by the manifest. You install Claude Code once, by hand,
and it stays.

## What actually persists

This is the part that matters, and it is not obvious.

The container filesystem is thrown away on every restart. **Only
`/home/kasm-user` survives** — that is where the 500Gi volume is mounted.

| Where it lands | Survives restart? |
|---|---|
| `~/.nvm`, `~/.npm-global`, `~/anything` | ✅ |
| `sudo apt install ...` → `/usr`, `/etc` | ❌ |
| `sudo npm install -g ...` as root → `/usr/lib` | ❌ |

So install into your home directory, not the system. The volume is seeded
with an `.npmrc` setting `prefix=~/.npm-global` and a matching `PATH` entry in
`.bashrc`, so a plain `npm install -g` already lands somewhere persistent —
**as long as you do not run it under `sudo`**, which ignores your `.npmrc`.

## Installing Claude Code (once)

Open a terminal in the desktop and use nvm, which keeps Node itself inside
`$HOME` and therefore persistent:

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc
nvm install --lts
npm install -g @anthropic-ai/claude-code
claude --version
```

Then authenticate:

```bash
claude
```

Credentials live in `~/.claude`, so you stay logged in across restarts.

Installing Node with `apt` instead will appear to work and then vanish on the
next restart — the binary goes to `/usr/bin`. Use nvm.

## First boot

An init container seeds the empty volume from the image's own home directory,
because mounting a volume straight over `/home/kasm-user` would otherwise
shadow the desktop profile and bring up a broken session. It writes a
`.home-seeded` marker and skips itself on every later start, so your installs
are never touched.

To start over from a clean home, delete the PVC `home-claude-code-vm-0` and
let it re-seed. That destroys everything you installed, so confirm the name
first:

```bash
kubectl get pvc -n claude-code-vm
```

## Prerequisites

This app will not run until the Talos GPU work is finished. In order:

1. All stages in [`talos/README.md`](../../../talos/README.md) — the NVIDIA
   extensions, kernel modules, and the `nvidia.com/gpu.present` node label.
2. The `nvidia-device-plugin` app, so `nvidia.com/gpu` becomes an allocatable
   resource.

Until then the pod stays `Pending` on `Insufficient nvidia.com/gpu`. Check:

```bash
kubectl get node talos-7j9-1pq -o jsonpath='{.status.allocatable.nvidia\.com/gpu}{"\n"}'
```

Expect `2`.

## Access

No login prompt — the ingress injects an `Authorization` header that
pre-authenticates every request, exactly like `remote-dev-vm`. The
credentials are `kasm_user:password`, held in two places that must agree:

| File | Field |
|---|---|
| `statefulset.yaml` | `VNC_PW` |
| `ingress.yaml` | base64 in `configuration-snippet` |

Change one without the other and auto-login silently breaks into a login
page.

### What this means

The credential is in Git and every request reaching the ingress is already
authenticated. Nothing is exposed to the internet — no Tailscale Funnel is
configured — but ingress-nginx is a LoadBalancer on `192.168.86.240`, a LAN
address, so the tailnet is an *additional* path rather than a restriction.
Anything on the home network can reach this.

That is a deliberate choice, consistent with `remote-dev-vm`. The one thing
that differs: this box keeps Claude Code credentials in `~/.claude` on the
persistent volume, so desktop access also means access to that account and
to everything under `/workspace`.

To tighten it later, drop the `configuration-snippet` from `ingress.yaml`
and move `VNC_PW` into a sealed secret — the desktop then shows its own
login page.

## Optional secret

To skip interactive login, seal an API key into `claude-code-vm-api`:

```bash
kubectl create secret generic claude-code-vm-api \
  --namespace claude-code-vm \
  --from-literal=ANTHROPIC_API_KEY='<key>' \
  --dry-run=client -o yaml | kubeseal --format yaml > claude-code-vm-api-sealedsecret.yaml
```

Referenced with `optional: true`, so leaving it out is fine.

## Sizing

Measured against the GPU node after Ray was scaled down:

| | GiB |
|---|---|
| allocatable | 629.2 |
| requested by everything else | 3.9 |
| schedulable | 625.2 |
| **this pod** | **576** |
| remaining headroom | 49.2 |

576Gi is 618 GB in decimal terms. 620Gi would also schedule, but would leave
only ~5 GiB for the rest of the node — and **etcd runs here**, so an OOM takes
the whole cluster down. Both GPUs are claimed exclusively; no time-slicing or
MPS is configured, so nothing else can use them while this is running.

Storage is `local-path` on the node's 3.0 TB disk (~2.79 TiB allocatable).
Note that local-path does not enforce the 500Gi figure — it provisions a
directory, so the number is nominal rather than a hard quota.

## Known rough edges

- The container runs `privileged: true`, inherited from `remote-dev-vm`.
  Worth revisiting given this namespace now holds both GPUs and most of the
  cluster's memory.
- `remote-dev-vm` declares a `config` PVC that its container never mounts, so
  that volume claim does nothing. Unrelated, but worth fixing separately.
