# Migration Process

This document outlines the process used to migrate the existing Kubernetes cluster to a GitOps workflow.

## Step 1: Clean and Organize Manifests

Run the migration script to clean kubectl-exported manifests and organize them:

```bash
python3 ~/migrate-to-gitops.py
```

This script:

- Removes runtime metadata (status, UIDs, resourceVersions, etc.)
- Cleans up kubectl annotations
- Organizes manifests by application
- Creates kustomization.yaml for each app

## Step 2: Create Argo CD Applications

Generate Argo CD Application definitions:

```bash
python3 ~/create-argocd-apps.py
```

**IMPORTANT:** Before running, update the `REPO_URL` in the script with your actual GitHub repository URL.

## Step 3: Review Generated Files

Check the generated manifests:

```bash
# Review manifests
ls -la apps/manifests/*/

# Review Application definitions
ls -la apps/base/

# Review root app
cat argocd/root-app.yaml
```

## Step 4: Commit and Push to GitHub

```bash
git add .
git commit -m "Add Kubernetes manifests for GitOps with Argo CD"
git push origin main
```

## Step 5: Deploy to Argo CD

Apply the root App of Apps:

```bash
kubectl apply -f argocd/root-app.yaml
```
