#!/bin/bash
# GitLab Monitoring Script

echo "🔍 GitLab Status Monitor"
echo "========================"
echo ""

echo "📦 Pods:"
kubectl get pods -n gitlab
echo ""

echo "🌐 Services:"
kubectl get svc -n gitlab
echo ""

echo "🔗 Ingress:"
kubectl get ingress -n gitlab
echo ""

echo "📊 Recent Events:"
kubectl get events -n gitlab --sort-by='.lastTimestamp' | tail -10
echo ""

echo "📝 GitLab Pod Logs (last 20 lines):"
POD_NAME=$(kubectl get pod -n gitlab -l app=gitlab -o jsonpath='{.items[0].metadata.name}')
if [ -n "$POD_NAME" ]; then
    echo "Pod: $POD_NAME"
    kubectl logs -n gitlab "$POD_NAME" --tail=20 2>&1 | tail -20
else
    echo "GitLab pod not found yet"
fi
echo ""

echo "💡 Helpful commands:"
echo "  Watch pod status:        kubectl get pods -n gitlab -w"
echo "  Follow logs:             kubectl logs -n gitlab -l app=gitlab -f"
echo "  Check readiness probe:   kubectl describe pod -n gitlab -l app=gitlab"
echo "  Access GitLab:           http://gitlab.homelab.com"
echo "  Login:                   root / changeme123"
