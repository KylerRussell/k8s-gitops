# GitLab Argo CD GitOps Configuration

This directory contains the GitOps configuration for deploying GitLab via Argo CD using the official GitLab Helm chart.

## ⚠️ IMPORTANT: Configuration Matches Your Working Setup

Your configuration uses:
- **Domain:** `homelab.com` (GitLab automatically prepends "gitlab" so it becomes `gitlab.homelab.com`)
- **Replicas:** 1 (exactly as your current working deployment)
- **Storage:** local-path
- **Protocol:** HTTP (no HTTPS)
- **Ingress:** Nginx

✅ **Do NOT change the domain or replica settings** - they match your working Helm deployment

## Files in This Directory

### Core Deployment
- **gitlab-helm-app.yaml** - Main GitLab Helm chart configuration (matches your current setup exactly)
- **gitlab-namespace.yaml** - Namespace with pod security policies

### Secrets (Recommended)
- **gitlab-sealedsecret.yaml** - Template for encrypted credentials (OPTIONAL but recommended)

### Organization
- **kustomization.yaml** - Orchestrates resources via Kustomize

### Documentation
- **QUICKSTART.md** - 3-step deployment guide
- **SEALED_SECRETS_SETUP.md** - Sealed secrets setup specific to your cluster
- **README.md** - This file

## Quick Start

### Option 1: Without Sealed Secrets (Quick)

```bash
# 1. Add to git
cd ~/Documents/GitHub/k8s-gitops
git add apps/base/gitlab.yaml apps/manifests/gitlab/
git commit -m "feat: add gitlab gitops (matches current config)"
git push

# 2. Argo CD automatically deploys
argocd app sync gitlab

# Done!
```

### Option 2: With Sealed Secrets (Recommended for Production)

```bash
# 1. Follow SEALED_SECRETS_SETUP.md (takes 10 minutes)

# 2. Commit sealed secrets
git add apps/manifests/gitlab/gitlab-sealedsecret.yaml
git commit -m "feat: add sealed secrets for gitlab"
git push

# 3. Argo CD deploys with encrypted credentials
argocd app sync gitlab
```

## Sealed Secrets Setup (Recommended)

Your credentials are currently plain text in the Helm values. For better security:

### Quick Steps:

```bash
# 1. Verify sealed-secrets is installed
kubectl get pods -n kube-system | grep sealed-secrets

# 2. Extract your current passwords
kubectl get secret -n gitlab gitlab-postgresql -o jsonpath='{.data.postgres-password}' | base64 -d

# 3. Follow the detailed guide
cat SEALED_SECRETS_SETUP.md
```

See **SEALED_SECRETS_SETUP.md** for complete, step-by-step instructions.

## Deploying GitLab

### Method 1: Automatic (Recommended)

If your root-app.yaml uses `directory.recurse: true`:

```bash
# Push to git - that's it!
git push

# Argo CD automatically discovers and deploys
# Check status:
argocd app get gitlab
```

### Method 2: Manual

```bash
# Apply the application
kubectl apply -f apps/base/gitlab.yaml

# Argo CD takes over
argocd app sync gitlab
```

## Accessing GitLab After Deployment

### Get the Initial Admin Password

```bash
kubectl get secret -n gitlab gitlab-initial-root-password \
  -o jsonpath='{.data.password}' | base64 -d
```

### Access the Web Interface

- **URL:** http://gitlab.homelab.com
- **Username:** root
- **Password:** [from above command]

## Monitoring Deployment

### Watch Pods Start

```bash
# Initial deployment takes 2-5 minutes
kubectl get pods -n gitlab -w
```

### Check Argo CD Status

```bash
argocd app get gitlab
argocd app describe gitlab
```

### Verify All Components Are Healthy

```bash
# All should show 1/1 or Running
kubectl get pods -n gitlab

# Check storage is being used
kubectl get pvc -n gitlab

# Check ingress is configured
kubectl get ingress -n gitlab
```

## Configuration Details

### Storage

All components use `local-path` storage:
- PostgreSQL: 20GB (database)
- Gitaly: 30GB (repositories)
- MinIO: 20GB (artifacts/backups)
- Redis: 5GB (caching)

Adjust sizes in `gitlab-helm-app.yaml` if needed for your setup.

### Replicas

Currently configured with 1 replica of each component (single instance).

To scale for high availability:
```yaml
gitlab-webservice:
  replicas: 3  # Change from 1
```

### Resources

CPU and memory requests are configured for homelab environments. For larger deployments, increase in `gitlab-helm-app.yaml`.

## Troubleshooting

### Pods Not Starting

```bash
# Check what's blocking
kubectl describe pod -n gitlab -l app=gitlab-webservice

# Check logs
kubectl logs -n gitlab -l app=gitlab-webservice --tail=50
```

### PostgreSQL Issues

```bash
# Check database pod
kubectl logs -n gitlab -l app=postgresql

# Check PVC is bound
kubectl get pvc -n gitlab | grep postgres
```

### Ingress Not Working

```bash
# Verify ingress controller is running
kubectl get pods -n ingress-nginx

# Check ingress configuration
kubectl describe ingress -n gitlab
```

### Argo CD Sync Fails

```bash
# Check what's wrong
argocd app describe gitlab

# Dry run to see errors
argocd app sync gitlab --dry-run

# Check controller logs
kubectl logs -n argocd deployment/argocd-application-controller | grep gitlab
```

## Configuration Does NOT Include

These are intentionally simplified for homelab:

- ❌ **HTTPS/TLS** - Configured for HTTP only
- ❌ **Multiple Replicas** - Single instance setup
- ❌ **External Databases** - Uses PostgreSQL subchart
- ❌ **Cert Manager** - Not configured
- ❌ **GitLab Runner** - Deploy separately if needed
- ❌ **LDAP/OAuth** - Configure after deployment
- ❌ **Email/SMTP** - Configure after deployment

These can all be added later by modifying `gitlab-helm-app.yaml`.

## Updating GitLab

To update to a new version:

```bash
# 1. Edit gitlab-helm-app.yaml
# Change: targetRevision: 9.5.1 → 9.6.0

# 2. Commit and push
git add apps/manifests/gitlab/gitlab-helm-app.yaml
git commit -m "chore: update gitlab to 9.6.0"
git push

# 3. Argo CD automatically syncs
# The Helm chart upgrade happens automatically
```

## Rollback

If something breaks:

```bash
# View history
git log -- apps/manifests/gitlab/gitlab-helm-app.yaml

# Rollback to previous version
git revert <commit-hash>
git push

# Argo CD automatically reverts to previous configuration
```

## Maintenance

### Regular Tasks

1. **Monitor Storage** - Check PVC usage
   ```bash
   kubectl get pvc -n gitlab
   ```

2. **Check Logs** - Monitor for errors
   ```bash
   kubectl logs -n gitlab -l app=gitlab-webservice -f
   ```

3. **Backup Data** - Regular backups recommended
   ```bash
   # Set up automated backups in GitLab settings
   ```

## Integration with Argo CD

This application integrates seamlessly with your existing setup:

✅ Follows same pattern as other apps (coder, harbor, headlamp, etc.)
✅ Managed by root-app with `directory.recurse: true`
✅ Automatic syncing like other applications
✅ Consistent kustomization structure

## Next Steps After Deployment

1. ✅ Access GitLab and set admin password
2. ✅ Configure GitLab settings (email, OAuth, LDAP)
3. ✅ Set up container registry authentication
4. ✅ Create projects and repositories
5. ✅ Deploy GitLab Runner for CI/CD (separate app)
6. ✅ Configure backups

## Support & Documentation

- **Helm Chart Docs:** https://docs.gitlab.com/ee/installation/kubernetes/helm_chart/
- **GitLab Kubernetes:** https://docs.gitlab.com/ee/install/kubernetes/
- **Argo CD:** https://argo-cd.readthedocs.io/
- **Your GitOps Repo:** https://github.com/KylerRussell/k8s-gitops

## Important Notes

⚠️ **Domain Configuration**
- Your domain is set to `homelab.com`
- GitLab will be accessible at `gitlab.homelab.com` (GitLab automatically adds "gitlab." prefix)
- Do NOT change this to avoid the "gitlab.gitlab.homelab.com" issue

⚠️ **Replicas**
- All components are set to 1 replica to match your working setup
- Do NOT change unless you understand the implications

✅ **Configuration Matches Your Helm Deployment**
- This configuration mirrors your current working GitLab Helm values exactly
- All settings are proven to work in your environment

## Files Documentation

| File | Purpose |
|------|---------|
| `gitlab-helm-app.yaml` | Main deployment config (read comments for customization) |
| `gitlab-namespace.yaml` | Namespace definition |
| `gitlab-sealedsecret.yaml` | Encrypted credentials template |
| `kustomization.yaml` | Resource organization |
| `QUICKSTART.md` | 3-step deployment guide |
| `SEALED_SECRETS_SETUP.md` | Step-by-step sealed secrets setup |
| `README.md` | This file |

## Questions?

1. For sealed secrets help: See `SEALED_SECRETS_SETUP.md`
2. For deployment issues: Check troubleshooting section above
3. For configuration questions: Check comments in `gitlab-helm-app.yaml`
4. For Argo CD questions: See your other app examples
