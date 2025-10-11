# Kubernetes GitOps with Argo CD

This repository contains Kubernetes manifests managed by Argo CD using the GitOps approach.

## 📁 Repository Structure

```
k8s-gitops/
├── apps/
│   ├── base/                    # Argo CD Application definitions
│   │   ├── harbor.yaml
│   │   ├── homarr.yaml
│   │   └── ...
│   └── manifests/               # Kubernetes manifests
│       ├── harbor/
│       │   ├── kustomization.yaml
│       │   ├── harbor-core.yaml
│       │   └── ...
│       ├── homarr/
│       └── ...
├── argocd/
│   └── root-app.yaml           # App of Apps pattern
└── README.md
```

## 🚀 Migration Process

### Step 1: Clean and Organize Manifests

Run the migration script to clean kubectl-exported manifests and organize them:

```bash
python3 ~/migrate-to-gitops.py
```

This script:
- Removes runtime metadata (status, UIDs, resourceVersions, etc.)
- Cleans up kubectl annotations
- Organizes manifests by application
- Creates kustomization.yaml for each app

### Step 2: Create Argo CD Applications

Generate Argo CD Application definitions:

```bash
python3 ~/create-argocd-apps.py
```

**IMPORTANT:** Before running, update the `REPO_URL` in the script with your actual GitHub repository URL.

### Step 3: Review Generated Files

Check the generated manifests:

```bash
# Review manifests
ls -la apps/manifests/*/

# Review Application definitions
ls -la apps/base/

# Review root app
cat argocd/root-app.yaml
```

### Step 4: Commit and Push to GitHub

```bash
git add .
git commit -m "Add Kubernetes manifests for GitOps with Argo CD"
git push origin main
```

### Step 5: Deploy to Argo CD

Apply the root App of Apps:

```bash
kubectl apply -f argocd/root-app.yaml
```

## 📊 Monitoring

### View Applications in Argo CD

```bash
# List all applications
kubectl get applications -n argocd

# Watch application sync status
watch kubectl get applications -n argocd

# Get detailed info about an app
kubectl describe application harbor -n argocd
```

### Access Argo CD UI

```bash
# Port forward to Argo CD server
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

Then access: https://localhost:8080

## 🔄 Sync Policies

All applications are configured with:
- **Auto-sync**: Automatically sync when changes are detected in Git
- **Self-heal**: Automatically revert manual changes to match Git state
- **Auto-prune**: Remove resources that are no longer in Git
- **Retry**: Automatically retry failed syncs with exponential backoff

## 🛠️ Managing Applications

### Add a New Application

1. Add manifests to `apps/manifests/new-app/`
2. Create `kustomization.yaml`
3. Create Application definition in `apps/base/new-app.yaml`
4. Commit and push
5. Argo CD will auto-sync

### Update an Application

1. Modify manifests in `apps/manifests/app-name/`
2. Commit and push
3. Argo CD will auto-sync within ~3 minutes

### Remove an Application

1. Delete the Application definition from `apps/base/`
2. Commit and push
3. Argo CD will remove the resources (due to prune=true)

## 📝 Application Configuration

Each application has:

- **Source**: Git repository + path to manifests
- **Destination**: Target cluster + namespace
- **Sync Policy**: Auto-sync, self-heal, prune settings
- **Health**: Argo CD monitors application health

## 🎯 Best Practices

1. **Never apply manifests directly**: Always commit to Git and let Argo CD sync
2. **Use namespaces**: Each app should have its own namespace
3. **Keep secrets secure**: Don't commit secrets to Git (use Sealed Secrets or External Secrets Operator)
4. **Review changes**: Always review diffs before merging
5. **Test in dev first**: Use branches for testing before merging to main

## 🔐 Secrets Management

Currently, secrets are managed in-cluster. For production, consider:

- [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets)
- [External Secrets Operator](https://external-secrets.io/)
- [SOPS](https://github.com/mozilla/sops)

## 📚 Resources

- [Argo CD Documentation](https://argo-cd.readthedocs.io/)
- [Kustomize Documentation](https://kustomize.io/)
- [GitOps Principles](https://opengitops.dev/)

## 🆘 Troubleshooting

### Application won't sync

```bash
# Check application status
kubectl describe application <app-name> -n argocd

# Check sync status
kubectl get application <app-name> -n argocd -o yaml

# Force sync
kubectl patch application <app-name> -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

### Application shows degraded

```bash
# Check resources
kubectl get all -n <app-namespace>

# Check events
kubectl get events -n <app-namespace> --sort-by='.lastTimestamp'
```

### Manual changes keep reverting

This is expected! Self-heal is enabled. To make changes:
1. Update manifests in Git
2. Commit and push
3. Let Argo CD sync

## 📧 Support

For issues or questions, check the Argo CD documentation or open an issue in this repository.
