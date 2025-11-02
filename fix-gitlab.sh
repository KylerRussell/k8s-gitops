#!/bin/bash
# GitLab Fix Script - Resolves PVC binding issues

set -e

echo "🔧 Fixing GitLab deployment..."
echo ""

# Step 1: Delete the gitlab namespace to clear all stuck resources
echo "📦 Step 1: Removing stuck GitLab resources..."
kubectl delete namespace gitlab --wait=true || echo "Namespace already deleted or doesn't exist"
echo "✅ Cleanup complete"
echo ""

# Step 2: Wait a moment for resources to fully clean up
echo "⏳ Waiting for cleanup to complete..."
sleep 5
echo ""

# Step 3: Sync ArgoCD application to recreate with fixed manifests
echo "🔄 Step 3: Syncing ArgoCD application..."
kubectl get application gitlab -n argocd > /dev/null 2>&1 && {
    echo "Triggering ArgoCD sync..."
    kubectl patch application gitlab -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
} || {
    echo "ArgoCD application doesn't exist, applying it now..."
    kubectl apply -f /Users/kylerrussell/Documents/GitHub/k8s-gitops/apps/base/gitlab.yaml
}
echo "✅ Sync triggered"
echo ""

# Step 4: Monitor the deployment
echo "👀 Step 4: Monitoring deployment..."
echo "Waiting for namespace to be created..."
timeout=60
while [ $timeout -gt 0 ]; do
    if kubectl get namespace gitlab > /dev/null 2>&1; then
        echo "✅ Namespace created"
        break
    fi
    sleep 2
    timeout=$((timeout - 2))
done

if [ $timeout -eq 0 ]; then
    echo "⚠️  Timeout waiting for namespace creation"
    exit 1
fi

echo ""
echo "Waiting for PVCs to bind..."
sleep 10

echo ""
echo "📊 Current status:"
echo ""
echo "=== PersistentVolumeClaims ==="
kubectl get pvc -n gitlab
echo ""
echo "=== Pods ==="
kubectl get pods -n gitlab
echo ""
echo "=== Services ==="
kubectl get svc -n gitlab
echo ""

echo "🎉 Fix script complete!"
echo ""
echo "Next steps:"
echo "1. Monitor the pods: kubectl get pods -n gitlab -w"
echo "2. Check logs if needed: kubectl logs -n gitlab -l app=gitlab -f"
echo "3. GitLab will take 5-10 minutes to fully initialize"
echo "4. Access GitLab at: http://gitlab.local (after adding to /etc/hosts)"
echo "5. Default login: root / changeme123"
