# GitLab Sealed Secrets - Quick Setup for Your Cluster

## Your Configuration (Already Matching)

✅ **Domain:** `homelab.com` (not gitlab.homelab.com - fixed!)
✅ **HTTP:** Enabled (no HTTPS)
✅ **Ingress:** Nginx
✅ **Storage:** local-path
✅ **Replicas:** 1 (your working setup)

The `gitlab-helm-app.yaml` has been updated to match your EXACT current working configuration.

## Quick Secret Sealing (Your Setup)

### Step 1: Verify sealed-secrets is installed

```bash
kubectl get pods -n kube-system | grep sealed-secrets
# Should show: sealed-secrets-xxxxx   1/1     Running
```

If not installed:
```bash
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.24.0/controller.yaml
```

### Step 2: Extract your CURRENT passwords

```bash
# Get what's currently running
kubectl get secret -n gitlab gitlab-postgresql -o jsonpath='{.data.postgres-password}' | base64 -d
# Copy this password

kubectl get secret -n gitlab gitlab-redis-secret -o jsonpath='{.data.redis-password}' | base64 -d
# Copy this password

# For MinIO (if you have it)
kubectl get secret -n gitlab gitlab-minio-secret -o jsonpath='{.data.accesskey}' | base64 -d
kubectl get secret -n gitlab gitlab-minio-secret -o jsonpath='{.data.secretkey}' | base64 -d
```

### Step 3: Create the sealed secret file

```bash
# Create temporary secret file with YOUR actual passwords
cat > /tmp/gitlab-secrets.yaml <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-secrets
  namespace: gitlab
type: Opaque
stringData:
  postgres-password: "PASTE_YOUR_POSTGRES_PASSWORD_HERE"
  redis-password: "PASTE_YOUR_REDIS_PASSWORD_HERE"
  minio-access-key: "minioadmin"
  minio-secret-key: "minioadmin"
EOF
```

### Step 4: Seal it

```bash
cd ~/Documents/GitHub/k8s-gitops

# Seal the secret
kubeseal -f /tmp/gitlab-secrets.yaml \
  -w apps/manifests/gitlab/gitlab-sealedsecret.yaml \
  --namespace gitlab

# Verify it was sealed (you should see encryptedData)
head -20 apps/manifests/gitlab/gitlab-sealedsecret.yaml
```

### Step 5: Test it works

```bash
# Apply the sealed secret
kubectl apply -f apps/manifests/gitlab/gitlab-sealedsecret.yaml

# Verify it unseals and contains the secrets
kubectl get secret -n gitlab gitlab-secrets -o yaml | grep postgres-password
# Should show a base64 encoded value
```

### Step 6: Enable in kustomization

Edit `apps/manifests/gitlab/kustomization.yaml`:

```yaml
resources:
  - gitlab-namespace.yaml
  - gitlab-helm-app.yaml
  - gitlab-sealedsecret.yaml     # ← Add this line
```

### Step 7: Commit to Git

```bash
cd ~/Documents/GitHub/k8s-gitops

git add apps/manifests/gitlab/
git commit -m "feat: add sealed secrets for gitlab with current passwords"
git push

# Delete the temporary unencrypted file (IMPORTANT!)
rm /tmp/gitlab-secrets.yaml
```

### Step 8: Verify sync

```bash
# Check Argo CD picks it up
argocd app describe gitlab
argocd app sync gitlab

# Verify secrets are accessible
kubectl get secrets -n gitlab
kubectl get sealedsecrets -n gitlab
```

## Troubleshooting Your Setup

### Sealed secret not appearing

```bash
# Check sealing worked
kubectl get sealedsecrets -n gitlab

# Check the sealed secret controller is running
kubectl get pods -n kube-system | grep sealed-secrets

# Check controller logs
kubectl logs -n kube-system -l app.kubernetes.io/name=sealed-secrets
```

### Unsealed secret not appearing

```bash
# Manually apply and check
kubectl apply -f apps/manifests/gitlab/gitlab-sealedsecret.yaml

# See if it unseal
kubectl get secret -n gitlab gitlab-secrets
kubectl describe secret -n gitlab gitlab-secrets
```

### "Cannot re-seal" error

```bash
# This means it was sealed with a different encryption key
# Re-seal it with the correct namespace:
kubeseal -f /tmp/gitlab-secrets.yaml \
  -w apps/manifests/gitlab/gitlab-sealedsecret.yaml \
  --namespace gitlab
```

## IMPORTANT: Backup Your Sealing Key!

Your sealing key is stored in the cluster. If you lose it, you can't decrypt old secrets.

```bash
# Backup the sealing key NOW
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/status=active \
  -o yaml > ~/sealed-secrets-key-backup.yaml

# Store this somewhere safe
# WARNING: This file contains the ability to decrypt all your secrets!
# Keep it private and secure.
```

## What Just Happened

✅ Your current passwords are extracted
✅ They're encrypted with your cluster's sealing key
✅ The encrypted file is safe to commit to Git
✅ Only YOUR cluster can decrypt them
✅ When Argo CD deploys, the secrets are automatically unsealed

## Your Configuration is Now:

```
apps/manifests/gitlab/
├── gitlab-helm-app.yaml           ✅ Matches your working setup exactly
├── gitlab-sealedsecret.yaml       ✅ Encrypted credentials (safe for Git)
├── kustomization.yaml             ✅ Includes sealed secrets
└── other files...
```

## Next Deploy

When you deploy via Argo CD:

1. Argo CD applies `gitlab-sealedsecret.yaml`
2. Sealed-secrets controller automatically decrypts it
3. Regular Secret `gitlab-secrets` is created with your passwords
4. GitLab uses these passwords to initialize

All secure, all version controlled, no plaintext secrets in Git!

## Questions?

For detailed step-by-step: See `SEALED_SECRETS_GUIDE.md` (full guide created)
For your current setup: Everything is already configured to match
For troubleshooting: Check the troubleshooting sections above

You're ready to seal! 🔐
