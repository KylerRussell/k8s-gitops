# Talos Configuration — `r820-cluster`

Talos machine configuration for the cluster this repo deploys onto. Argo CD
manages everything *inside* Kubernetes; this folder covers the layer
underneath it, which Argo CD cannot reach.

These are **patches, not full machine configs**. The complete machine config
contains the cluster CA private keys, the service account key, the bootstrap
tokens and the secretbox encryption secret — none of which belong in Git.
The authoritative config lives on the nodes; this folder records the
intentional deltas so they survive a rebuild.

## Cluster

| Node | Role | Address | Notes |
|---|---|---|---|
| `talos-7j9-1pq` | control plane | `192.168.86.23` (`eno1`), `192.168.86.55` (`eno2`) | 2× RTX 3090 |
| `talos-lgp-38q` | worker | `192.168.86.46`, `192.168.86.47` | |
| `talos-dmt-nnk` | worker | `192.168.86.52`, `192.168.86.54` | |

Talos v1.9.5 · Kubernetes v1.32.3 · pods `10.244.0.0/16` · services `10.96.0.0/12`

Reserved addresses:

| Address | Purpose |
|---|---|
| `192.168.86.230` | control plane VIP — sits below the MetalLB pool |
| `192.168.86.240-250` | MetalLB pool (`.240` = ingress-nginx) |

`.230` was chosen at the bottom of the free `.230-.239` block so an expanded
MetalLB pool would not reach it. Verified free by ARP probe; `.236` is the
only occupied address in that block.

> Note that ICMP silence does not prove an address is free — several hosts
> here do not answer pings but do answer ARP. Probe with ARP before claiming
> an address, and treat an `(incomplete)` ARP entry as free.

## Contents

| File | Scope | Type |
|---|---|---|
| `schematic.yaml` | all nodes | Image Factory schematic |
| `patches/all-nodes-endpoint.yaml` | all nodes | strategic merge |
| `patches/controlplane-vip.yaml` | control plane | strategic merge |
| `patches/controlplane-certsans.yaml` | control plane | JSON patch |
| `patches/controlplane-kernel-modules.yaml` | control plane | JSON patch |
| `patches/controlplane-nvidia-sysctl.yaml` | control plane | strategic merge |
| `patches/controlplane-node-label.yaml` | control plane | strategic merge |
| `patches/worker-kernel-modules.yaml` | workers | JSON patch |

### Why some patches are JSON patches

Talos **appends** to lists when applying a strategic merge patch. Anything
that needs a list *replaced* — deduplicating `kernel.modules`, dropping the
stale `certSANs` entry — must be an RFC 6902 JSON patch using `op: replace`.
Using a merge patch for those would add entries rather than fix them.

## Applying

`talosctl` targets real node IPs, never the VIP — the VIP is bound to etcd
and kube-apiserver health, so it cannot be used to recover from a failure.

```bash
export TALOSCONFIG=~/.talos/config
CP=192.168.86.23
W1=192.168.86.46
W2=192.168.86.52
```

### Stage 1 — config only, no reboot

Deduplicate the doubled `iscsi_tcp` module on the workers:

```bash
talosctl -e $CP -n $W1,$W2 patch mc --patch @talos/patches/worker-kernel-modules.yaml
```

Add the VIP and the certificate SANs to the control plane:

```bash
talosctl -e $CP -n $CP patch mc --patch @talos/patches/controlplane-vip.yaml --patch @talos/patches/controlplane-certsans.yaml
```

Confirm the VIP came up before going further — it depends on etcd, so it
will not appear if etcd is unhealthy:

```bash
talosctl -e $CP -n $CP get addresses | grep 192.168.86.230
```

### Stage 2 — register the schematic

```bash
curl -X POST --data-binary @talos/schematic.yaml https://factory.talos.dev/schematics
```

Already done — the resulting ID is baked into
`patches/all-nodes-endpoint.yaml`:

```
f53e88768342a2fd9d590e037332c5fcd709d8fd80aa7db6c326f81a43227bf4
```

The ID is deterministic, so re-registering the same schematic returns the
same value. Re-run this and update the patch only if the extension list
changes.

> **The extension names are branch-suffixed on v1.9.** The unsuffixed names
> in the Talos docs (`siderolabs/nvidia-container-toolkit`,
> `siderolabs/nvidia-open-gpu-kernel-modules`) do not exist for v1.9.5. The
> Image Factory accepts a schematic containing them and returns an ID
> without complaint — the failure only shows up when the installer is
> pulled. Check the names for your release before changing them:
>
> ```bash
> curl -s https://factory.talos.dev/version/v1.9.5/extensions/official
> ```

> **Talos does not validate the image reference either.** A wrong or stale
> schematic ID applies cleanly and only fails at upgrade time.

### Stage 3 — repoint the endpoint and installer

```bash
talosctl -e $CP -n $CP,$W1,$W2 patch mc --patch @talos/patches/all-nodes-endpoint.yaml
```

### Stage 4 — upgrade onto the factory image (reboots each node)

Pass the image **explicitly**. Do not rely on `install.image` alone.
Upgrade one node at a time and wait for `Ready` in between.

```bash
talosctl -e $CP -n $W1 upgrade --image factory.talos.dev/installer/f53e88768342a2fd9d590e037332c5fcd709d8fd80aa7db6c326f81a43227bf4:v1.9.5
```

Repeat for `$W2`, then `$CP` last. The control plane reboot takes the API
server with it, so expect a short outage.

### Stage 5 — load the NVIDIA modules

Only after the control plane is running the factory image, or the modules
will not exist:

```bash
talosctl -e $CP -n $CP patch mc --patch @talos/patches/controlplane-kernel-modules.yaml --patch @talos/patches/controlplane-nvidia-sysctl.yaml --patch @talos/patches/controlplane-node-label.yaml
```

Confirm the node label landed, since the device plugin selects on it:

```bash
kubectl get node talos-7j9-1pq -o jsonpath='{.metadata.labels}' | tr ',' '\n' | grep nvidia
```

## Verifying

```bash
talosctl -e $CP -n $CP,$W1,$W2 get extensions
```

Expect `iscsi-tools`, `nvidia-open-gpu-kernel-modules` and
`nvidia-container-toolkit` on all three.

```bash
talosctl -e $CP -n $CP read /proc/driver/nvidia/version
```

```bash
talosctl -e $CP -n $CP read /proc/modules | grep nvidia
```

Longhorn is the thing most likely to break here — check its volumes are
still healthy after each node comes back.

## The Kubernetes side

The Talos side only exposes the hardware. The `RuntimeClass` and the NVIDIA
device plugin DaemonSet live under
[`apps/manifests/nvidia-device-plugin`](../apps/manifests/nvidia-device-plugin),
deployed by Argo CD like any other app.

Do not sync that app until Stage 5 is complete. The plugin selects on the
`nvidia.com/gpu.present` label and will not schedule anywhere until the label
exists, and it needs the NVIDIA runtime the extensions provide.

Once it is running:

```bash
kubectl get node talos-7j9-1pq -o jsonpath='{.status.allocatable.nvidia\.com/gpu}{"\n"}'
```

Expect `2`. GPU pods then request `nvidia.com/gpu` and set
`runtimeClassName: nvidia`:

```yaml
spec:
  runtimeClassName: nvidia
  containers:
    - name: app
      resources:
        limits:
          nvidia.com/gpu: 1
```

`ollama`, `ray` and the `ml-training` workloads in this repo need both of
those fields added before they can use the GPUs.

The control plane has `allowSchedulingOnControlPlanes: true` and carries no
taints, so GPU pods schedule there without tolerations.

## Hardware notes

Both 3090s enumerate cleanly with BAR1 mapped above 4G, so Above-4G decoding
is already enabled in the R820's BIOS.

The cards sit on **asymmetric PCIe links** — `0000:43:00.0` negotiates Gen3
x8 (63 Gb/s) while `0000:44:00.0` gets Gen3 x16 (126 Gb/s). Fine for
inference; for multi-GPU training the x8 card will bottleneck gradient sync.
Moving it to a x16 slot is a physical fix.

## Known gaps

- **The node addresses are still DHCP.** The VIP stabilises the Kubernetes
  endpoint, but `talosctl` targets real node IPs, and those can still drift
  the same way `.26` did. Add DHCP reservations on the router for the node
  MACs. Look them up with:

  ```bash
  talosctl -e $CP -n $CP,$W1,$W2 get links | grep -E 'eno1|eno2'
  ```

- **Single control plane.** The VIP uses etcd leader election, so with one
  control plane node it buys a stable address but no high availability.

- **MetalLB's pool overlaps the default Google Wifi DHCP range**
  (`192.168.86.20-249`). Pre-existing, unrelated to these patches, but the
  router could in principle lease an address MetalLB has already handed out.
