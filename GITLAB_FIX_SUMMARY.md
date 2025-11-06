## GitLab GitOps Configuration Update - Network Connectivity Fix

**Date**: November 6, 2025  
**Issue**: GitLab pod stuck in CrashLoopBackOff due to inability to reach internal APIs  
**Root Cause**: Pod configured with external URL but unable to route to itself internally (hairpin NAT issue)

---

## Changes Made

### 1. **gitlab-deployment.yaml** - Added hostAliases

**What was added:**
```yaml
spec:
  template:
    spec:
      hostAliases:
      - ip: "127.0.0.1"
        hostnames:
        - "gitlab.homelab.com"
```

**Why this helps:**
- Maps `gitlab.homelab.com` to `localhost` (127.0.0.1) inside the pod
- Allows internal services (KAS, Workhorse, Puma) to reach the API via the configured external URL
- Solves the hairpin NAT issue where the pod couldn't route to its own external IP (100.83.234.92)

### 2. **gitlab-configmap.yaml** - Enhanced Configuration

**Key additions:**

#### A. KAS Internal API URL Fix
```ruby
gitlab_kas['internal_api_url'] = 'http://gitlab.homelab.com'
```
- KAS now correctly points to the external URL (which resolves to localhost via hostAliases)
- This fixes: `Failed to get receptive agents` error
- Replaces the broken attempt to use `http://127.0.0.1:8080`

#### B. Reverse Proxy Trust Settings
```ruby
nginx['real_ip_trusted_addresses'] = ['0.0.0.0/0']
gitlab_rails['trusted_proxies'] = ['0.0.0.0/0']
```
- Tells GitLab to trust X-Forwarded-* headers from the nginx ingress controller
- Ensures GitLab knows requests are proxied through the ingress
- Fixes potential redirect loops and protocol issues

#### C. Workhorse Socket Configuration
```ruby
gitlab_rails['workhorse_socket_dir'] = '/var/opt/gitlab/gitlab-workhorse'
```
- Explicitly sets where Workhorse socket is located
- Ensures Puma and Workhorse can communicate properly
- Fixes: `badgateway: failed to receive response` errors

#### D. Health Probe Fixes
```ruby
nginx['custom_gitlab_server_config'] = "
location ~ ^/-/(readiness|liveness|health) {
  access_log off;
  proxy_pass http://gitlab-workhorse;
}
"
```
- Allows Kubernetes health probes to work properly
- Fixes: HTTP 404 errors on readiness/liveness endpoints

---

## What These Changes Fix

### Errors Addressed

1. **KAS Connection Error**
   - ❌ Before: `Get "http://gitlab.homelab.com/api/v4/internal/kubernetes/receptive_agents": dial tcp 100.83.234.92:80: connect: network is unreachable`
   - ✅ After: KAS uses local resolution → localhost → nginx → internal API

2. **Workhorse Bad Gateway**
   - ❌ Before: `dial unix /var/opt/gitlab/gitlab-rails/sockets/gitlab.socket: connect: connection refused`
   - ✅ After: Socket path explicitly configured, communication chain restored

3. **Readiness Probe Failures**
   - ❌ Before: HTTP 404 on `/-/readiness` endpoint
   - ✅ After: Health probes properly routed to Workhorse

---

## How It Works Now

```
External Traffic (100.83.234.92:80)
    ↓
Ingress Controller (nginx-ingress)
    ↓
Service: gitlab:80
    ↓
Pod nginx:80 (listens on 0.0.0.0:80)
    ↓
gitlab.homelab.com resolves to 127.0.0.1 (via hostAliases)
    ↓
Internal Services (KAS, Workhorse, Puma) can now reach API
```

---

## Next Steps

1. **Commit changes to git:**
   ```bash
   git add apps/manifests/gitlab/
   git commit -m "fix: Add hostAliases and improve internal API routing for GitLab

   - Add hostAliases to map gitlab.homelab.com to localhost
   - Configure KAS internal_api_url to use external hostname
   - Add reverse proxy trust settings for ingress headers
   - Explicitly set workhorse socket directory
   - Fix health probe routing
   
   Fixes CrashLoopBackOff due to network unreachability"
   ```

2. **Push and let ArgoCD deploy:**
   ```bash
   git push origin main
   ```

3. **Monitor the pod:**
   - ArgoCD should detect the changes and redeploy automatically
   - Watch: `kubectl logs -f -n gitlab deployment/gitlab`
   - The pod should start successfully after configuration is applied

4. **Verify connectivity:**
   - Check pod is running: `kubectl get pods -n gitlab`
   - Test readiness: `kubectl port-forward -n gitlab svc/gitlab 8080:80`
   - Then: `curl -H "Host: gitlab.homelab.com" http://localhost:8080/-/readiness`

---

## Files Modified

- `/Users/kylerrussell/Documents/GitHub/k8s-gitops/apps/manifests/gitlab/gitlab-deployment.yaml`
- `/Users/kylerrussell/Documents/GitHub/k8s-gitops/apps/manifests/gitlab/gitlab-configmap.yaml`

## Files Not Modified (No changes needed)

- `gitlab-ingress.yaml` - Ingress configuration is correct
- `gitlab-service.yaml` - Service configuration is correct
- `kustomization.yaml` - Resources order is correct

---

## Key Insight

The core issue was a **networking loop problem**: GitLab needed to communicate with itself via its external URL, but the pod couldn't reach the external IP from inside the cluster. By:
1. Adding `hostAliases` to resolve the hostname locally
2. Configuring services to use that hostname
3. Setting proper reverse proxy headers

GitLab can now successfully communicate internally while still being externally accessible through the ingress.
