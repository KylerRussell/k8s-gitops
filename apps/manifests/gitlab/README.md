# GitLab Manifests

This directory contains Kustomize overlays and additional resources for GitLab.

## Structure

- `kustomization.yaml` - Kustomize configuration that manages all resources
- `namespace.yaml` - GitLab namespace definition

## Adding Resources

To add additional resources (PrometheusRules, ServiceMonitors, ConfigMaps, etc.):

1. Create the resource file in this directory
2. Add it to `kustomization.yaml` under `resources:`
3. Commit and push - ArgoCD will automatically sync

## Examples to Add

### PrometheusRule for GitLab monitoring
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: gitlab-alerts
spec:
  groups:
  - name: gitlab
    interval: 30s
    rules:
    # Add alert rules here
```

### ServiceMonitor for Prometheus scraping
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: gitlab
spec:
  selector:
    matchLabels:
      release: gitlab
  endpoints:
  - port: metrics
```

## Related

- Helm chart values: `apps/base/gitlab.yaml`
- GitLab official docs: https://docs.gitlab.com/
- GitLab Helm chart: https://github.com/gitlabhq/helm-charts
