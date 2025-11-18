# GitLab Argo CD GitOps - Quick Start

## Files Created

All files have been created in your repository following your established patterns:

```
✅ apps/base/gitlab.yaml                      - Main Argo Application
✅ apps/manifests/gitlab/
   ✅ gitlab-namespace.yaml                   - Namespace
   ✅ gitlab-helm-app.yaml                    - Helm chart via Argo
   ✅ gitlab-sealedsecret.yaml                - Sealed secrets template
   ✅ kustomization.yaml                      - Kustomize config
   ✅ README.md                               - Documentation
```

## Quick Start (3 Steps)

### 1. Update Configuration

Edit `apps/manifests/gitlab/gitlab-helm-app.yaml`:

```bash
# Change domain to your setup
global:
  hosts:
    domain: gitlab.homelab.com          # Update this
    externalUrl: http://gitlab.homelab.com
```

### 2. Add to Git and Push

```bash
cd ~/Documents/GitHub/k8s-gitops
git add apps/base/gitlab.yaml apps/manifests/gitlab/
git commit -m "feat: add gitlab gitops configuration"
git push
```

### 3. Apply via Argo CD

```bash
# Option A: Auto-sync (if root-app has directory.recurse)
# It will pick up gitlab automatically

# Option B: Manual
argocd app sync gitlab
```

## Monitoring Deployment

```bash
# Watch the deployment
kubectl get pods -n gitlab -w

# Check Argo CD status
argocd app get gitlab

# Access GitLab
# URL: http://gitlab.homelab.com
# User: root
# Pass: kubectl get secret -n gitlab gitlab-initial-root-password -o jsonpath='{.data.password}' | base64 -d
```

## Key Differences from Helm Direct

| Aspect | Direct Helm | Argo CD GitOps |
|--------|-------------|----------------|
| Source | helm upgrade commands | Git repository |
| Deployment | Manual | Automated via Argo CD |
| History | helm history | git log |
| Rollback | helm rollback | git revert |
| Version Control | Manual tracking | Full git history |
| Multiple Clusters | Requires script | One push for all |

## Important Customizations

Before deploying, check these in `gitlab-helm-app.yaml`:

1. **Domain:** Line ~17 - Change `gitlab.homelab.com` to your domain
2. **Storage Size:** Lines ~26-35 - Adjust based on your needs
3. **Resources:** Lines ~170+ - Adjust CPU/Memory for your cluster
4. **HTTPS:** Line ~18 - Change to `https: true` if you want HTTPS
5. **Replicas:** Search `replicas: 1` to scale up components

## Sealed Secrets (Optional but Recommended)

Currently using plain text passwords. To use sealed secrets:

```bash
# 1. Seal your passwords
kubectl create secret generic gitlab-secrets \
  --from-literal=postgres-password='your-password' \
  -n gitlab --dry-run=client -o yaml | kubeseal -f - -w apps/manifests/gitlab/gitlab-sealedsecret.yaml

# 2. Update reference in gitlab-helm-app.yaml to use the sealed secret

# 3. Uncomment in kustomization.yaml:
# - gitlab-sealedsecret.yaml
```

## File Descriptions

### apps/base/gitlab.yaml
Argo CD Application wrapper - points to the manifests directory. This is what ties everything together in Argo CD.

### apps/manifests/gitlab/gitlab-helm-app.yaml
Main GitLab deployment using the official GitLab Helm chart. All configuration is here with sensible defaults for your homelab setup (local-path storage, nginx ingress, HTTP only).

### apps/manifests/gitlab/gitlab-namespace.yaml
Creates the gitlab namespace with pod security policies. Matches your cluster's setup.

### apps/manifests/gitlab/gitlab-sealedsecret.yaml
Template for sealed secrets (currently commented out). Provides secure credential management via Bitnami sealed-secrets.

### apps/manifests/gitlab/kustomization.yaml
Orchestrates the resources. Uses Kustomize to organize and manage the GitLab deployment components.

## Troubleshooting

**GitLab not starting?**
```bash
# Check pod status
kubectl get pods -n gitlab
kubectl describe pod -n gitlab -l app=gitlab-webservice

# Check logs
kubectl logs -n gitlab -l app=gitlab-webservice
```

**PostgreSQL issue?**
```bash
# Check if database is initializing
kubectl logs -n gitlab -l app=postgresql
kubectl get pvc -n gitlab
```

**Ingress not working?**
```bash
# Verify nginx ingress controller
kubectl get pods -n ingress-nginx
kubectl get ingress -n gitlab
```

**Argo CD sync failed?**
```bash
# Check what's wrong
argocd app describe gitlab
argocd app sync gitlab --dry-run

# Check controller logs
kubectl logs -n argocd deployment/argocd-application-controller | grep gitlab
```

## Next Phase: GitLab Runner

Once GitLab is running, you can add GitLab Runner for CI/CD:

```bash
# Create similar structure in
apps/manifests/gitlab-runner/
```

## Documentation Links

- [Your GitOps Repo](https://github.com/KylerRussell/k8s-gitops)
- [GitLab Kubernetes Docs](https://docs.gitlab.com/ee/install/kubernetes/)
- [Argo CD App Spec](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/)
- [GitLab Helm Chart](https://docs.gitlab.com/ee/installation/kubernetes/helm_chart/)

## Success Indicators

✅ You'll know it's working when:
- All pods in `kubectl get pods -n gitlab` show "Running"
- `argocd app get gitlab` shows "Synced"
- You can access http://gitlab.homelab.com
- You can login as `root`
- Git commands work: `git clone http://gitlab.homelab.com/root/test.git`

## Support

For questions about your setup:
1. Check the detailed README.md in `apps/manifests/gitlab/`
2. Review the artifacts generated during this session
3. Check your cluster logs: `kubectl logs -n gitlab ...`
4. Check Argo CD status: `argocd app describe gitlab`

Good luck with your GitLab deployment! 🚀
