# GitLab GitOps Migration - Summary

## What Was Created

This document summarizes all the files and changes made to migrate your GitLab deployment from Helm to Argo CD GitOps.

## Files Created

### 1. **apps/base/gitlab.yaml** (NEW)
- **Purpose:** Main Argo CD Application manifest
- **Function:** Tells Argo CD where to find and how to manage GitLab
- **Key Config:**
  - Points to `apps/manifests/gitlab` path
  - Enables automatic pruning and self-healing
  - Creates gitlab namespace automatically
  - Auto-syncs with your repository

### 2. **apps/manifests/gitlab/gitlab-namespace.yaml** (NEW)
- **Purpose:** Creates the gitlab namespace
- **Includes:** Pod security policies for baseline security
- **Size:** ~7 lines

### 3. **apps/manifests/gitlab/gitlab-helm-app.yaml** (NEW)
- **Purpose:** The actual GitLab deployment configuration
- **What it does:**
  - Deploys official GitLab Helm chart (v9.5.1)
  - Configures PostgreSQL, Redis, MinIO
  - Sets up Gitaly, WebService, Sidekiq
  - Configures ingress for your domain
  - Uses local-path storage class
  - Includes sensible resource requests/limits
- **Size:** ~200 lines of configuration
- **Customization Points:**
  - Domain name (line ~17)
  - Storage sizes (lines ~26-35)
  - Resource limits (lines ~170+)
  - Replica counts
  - HTTPS/TLS settings

### 4. **apps/manifests/gitlab/gitlab-sealedsecret.yaml** (NEW - Template)
- **Purpose:** Secure credential management
- **Status:** Currently a template - needs your passwords sealed
- **Usage:** Optional but recommended for production
- **How to use:** See README.md for sealing instructions

### 5. **apps/manifests/gitlab/kustomization.yaml** (NEW)
- **Purpose:** Orchestrates all GitLab resources
- **Pattern:** Matches your other apps (coder, harbor, etc.)
- **Includes:** All namespace, helm app, and optional secrets

### 6. **apps/manifests/gitlab/README.md** (NEW)
- **Purpose:** Detailed documentation
- **Contains:**
  - Migration instructions
  - Backup procedures
  - Troubleshooting guide
  - Configuration options
  - Access instructions

### 7. **apps/manifests/gitlab/QUICKSTART.md** (NEW)
- **Purpose:** Quick reference guide
- **Contains:** 3-step start, monitoring, customization checklist

## Structure Created

Your repository now follows this structure for GitLab:

```
k8s-gitops/
├── apps/
│   ├── base/
│   │   ├── coder.yaml                    (existing)
│   │   ├── coredns.yaml                  (existing)
│   │   ├── excalidraw.yaml               (existing)
│   │   ├── gitlab.yaml                   ✨ NEW
│   │   ├── harbor.yaml                   (existing)
│   │   ├── headlamp.yaml                 (existing)
│   │   ├── ... other apps ...
│   └── manifests/
│       ├── coder/                        (existing)
│       ├── coredns/                      (existing)
│       ├── excalidraw/                   (existing)
│       ├── gitlab/                       ✨ NEW DIRECTORY
│       │   ├── gitlab-namespace.yaml
│       │   ├── gitlab-helm-app.yaml
│       │   ├── gitlab-sealedsecret.yaml
│       │   ├── kustomization.yaml
│       │   ├── README.md
│       │   └── QUICKSTART.md
│       ├── harbor/                       (existing)
│       ├── headlamp/                     (existing)
│       └── ... other apps ...
```

## Configuration Details

### Default Settings

| Setting | Value | Notes |
|---------|-------|-------|
| Domain | gitlab.homelab.com | Change to your domain |
| Protocol | HTTP | Set to HTTPS if you have certs |
| Storage Class | local-path | Works with k3s, kind, microk8s |
| PostgreSQL Size | 20Gi | Adjust for large deployments |
| Gitaly Size | 30Gi | Adjust for many repositories |
| MinIO Size | 20Gi | For artifacts and backups |
| Replicas | 1 | Single instance setup |
| CPU Limit | 2000m | Adjust for small clusters |
| Memory Limit | 4Gi | Adjust for small clusters |

### What's Different from Direct Helm

| Aspect | Before (Helm) | After (GitOps) |
|--------|---------------|----------------|
| **Source** | helm command | Git repository |
| **Deployment** | Manual helm upgrade | Automatic via Argo CD |
| **History** | helm history | Full git log |
| **Rollback** | helm rollback | git revert or Argo CD rollback |
| **Multi-cluster** | Run helm on each | One push deploys to all |
| **Audit Trail** | helm history | git history + Argo CD UI |
| **Updates** | Edit values, helm upgrade | Edit YAML, git push, auto-sync |

## How It Matches Your Existing Pattern

Your new GitLab config follows the same pattern as your other apps:

**Coder Example:**
```
apps/base/coder.yaml → apps/manifests/coder/
```

**GitLab (New):**
```
apps/base/gitlab.yaml → apps/manifests/gitlab/
```

All use:
- Kustomization for resource organization
- Namespace auto-creation
- Helm charts (or direct manifests)
- Sealed secrets for credentials
- Automated Argo CD syncing
- Local-path storage class

## Pre-Deployment Checklist

Before you deploy:

- [ ] Updated domain in `gitlab-helm-app.yaml` (if not homelab.com)
- [ ] Adjusted storage sizes if needed
- [ ] Adjusted resource limits for your cluster
- [ ] Created sealed secrets (optional)
- [ ] Reviewed all passwords are changed from defaults
- [ ] Backed up any existing GitLab data
- [ ] nginx-ingress controller is running
- [ ] Local-path storage class exists

## Post-Deployment Checklist

After deploying:

- [ ] All pods in Running state (`kubectl get pods -n gitlab`)
- [ ] Argo CD shows Synced status (`argocd app get gitlab`)
- [ ] Can access GitLab at your domain
- [ ] Can login as root user
- [ ] Initial password obtained successfully
- [ ] Storage is being used correctly
- [ ] No critical errors in pod logs

## Deployment Options

### Option 1: Automatic (Recommended if root-app uses directory.recurse)

```bash
# Just push to git
git add apps/base/gitlab.yaml apps/manifests/gitlab/
git commit -m "feat: add gitlab gitops"
git push

# Argo CD automatically picks it up and deploys
```

### Option 2: Manual Application Creation

```bash
# Apply the base application
kubectl apply -f apps/base/gitlab.yaml

# Argo CD then manages it
```

### Option 3: Via ArgoCD CLI

```bash
# If you prefer CLI
argocd app create gitlab \
  --repo https://github.com/KylerRussell/k8s-gitops.git \
  --path apps/manifests/gitlab \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace gitlab \
  --auto-prune \
  --self-heal
```

## Key Files Reference

**For Customization:**
- `apps/manifests/gitlab/gitlab-helm-app.yaml` - All GitLab configuration

**For Understanding:**
- `apps/manifests/gitlab/README.md` - Detailed documentation
- `apps/manifests/gitlab/QUICKSTART.md` - Quick reference

**For Credentials:**
- `apps/manifests/gitlab/gitlab-sealedsecret.yaml` - Template for sealed secrets

**For Resource Organization:**
- `apps/manifests/gitlab/kustomization.yaml` - How Argo CD finds resources

## Next Steps

1. **Review:** Read through `apps/manifests/gitlab/README.md`
2. **Customize:** Update domain and other settings in `gitlab-helm-app.yaml`
3. **Test:** Deploy in your test environment first (if you have one)
4. **Deploy:** Push to git and let Argo CD handle it
5. **Verify:** Check all pods and access GitLab
6. **Maintain:** Future updates just require editing the YAML

## Troubleshooting Resources

If something goes wrong:

1. **Check Argo CD status:** `argocd app describe gitlab`
2. **Check pod status:** `kubectl get pods -n gitlab`
3. **Check pod logs:** `kubectl logs -n gitlab -l app=gitlab-webservice`
4. **Check Argo CD controller logs:** `kubectl logs -n argocd deployment/argocd-application-controller | grep gitlab`
5. **Read troubleshooting sections in:**
   - `apps/manifests/gitlab/README.md`
   - Artifacts generated during this session

## Support

For help with:
- **GitLab specific questions:** See [GitLab Kubernetes Docs](https://docs.gitlab.com/ee/install/kubernetes/)
- **Argo CD questions:** See [Argo CD Docs](https://argo-cd.readthedocs.io/)
- **Your GitOps setup:** Check the README.md files or your git repository history

## Version Information

- **Helm Chart:** gitlab/9.5.1 (configurable in `gitlab-helm-app.yaml`)
- **Argo CD:** Any recent version that supports Applications
- **Kubernetes:** 1.20+ (tested with k3s, kind, full K8s)

## Notes

- All files follow your existing GitOps patterns
- Configuration is designed for homelab/small clusters
- Passwords in `gitlab-helm-app.yaml` should be changed or replaced with sealed secrets
- Storage classes use `local-path` - works with k3s and kind
- No external dependencies beyond what you already have

---

**Created:** 2025-11-15
**Repository:** https://github.com/KylerRussell/k8s-gitops
**Status:** Ready to deploy
