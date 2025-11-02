# GitLab Deployment

This directory contains the GitLab deployment for your Kubernetes cluster using Sealed Secrets.

## Components

- **GitLab CE**: The main GitLab Community Edition application
- **PostgreSQL**: Database backend for GitLab
- **Redis**: Caching and background job processing

## Storage Requirements

- GitLab Data: 50Gi
- GitLab Logs: 10Gi
- GitLab Config: 1Gi
- PostgreSQL Data: 20Gi
- Redis Data: 5Gi

**Total: ~86Gi**

## Prerequisites

1. Sealed Secrets controller must be installed in your cluster
2. `kubeseal` CLI tool must be installed
3. ArgoCD must be running

## Deployment Steps

### 1. Create Sealed Secrets

Run the provided script to create sealed secrets:

```bash
cd apps/manifests/gitlab
./create-sealed-secrets.sh
```

This script will:
- Prompt you for passwords (or use defaults)
- Generate secure random keys for GitLab
- Create sealed secret files:
  - `postgresql-sealedsecret.yaml`
  - `gitlab-sealedsecret.yaml`

**Important**: The script uses default passwords if you just press Enter. For production, you should provide strong passwords!

### 2. Verify Sealed Secrets

Check that the sealed secret files were created:

```bash
ls -la *sealedsecret.yaml
```

You should see:
- `postgresql-sealedsecret.yaml`
- `gitlab-sealedsecret.yaml`

### 3. Commit Sealed Secrets

The sealed secrets are safe to commit to git:

```bash
git add postgresql-sealedsecret.yaml gitlab-sealedsecret.yaml
git commit -m "Add GitLab sealed secrets"
git push
```

### 4. Deploy via ArgoCD

Apply the ArgoCD application:

```bash
kubectl apply -f ../../base/gitlab.yaml
```

ArgoCD will automatically sync and deploy all GitLab components.

### 5. Monitor Deployment

Watch the deployment progress:

```bash
# Check ArgoCD application status
kubectl get app -n argocd gitlab

# Watch pods coming up
kubectl get pods -n gitlab -w

# Check all resources
kubectl get all -n gitlab
```

## Accessing GitLab

### Web Interface

1. Get the ingress IP:
   ```bash
   kubectl get ingress -n gitlab
   ```

2. Add to your `/etc/hosts`:
   ```
   <INGRESS_IP> gitlab.local
   ```

3. Access: http://gitlab.local

### Default Credentials

- **Username**: `root`
- **Password**: Whatever you set in the sealed secrets script (default: `changeme123`)

### SSH Access (Git operations)

The SSH service is exposed via LoadBalancer on port 2222:

```bash
# Get the external IP
kubectl get svc -n gitlab gitlab-ssh

# Clone a repo
git clone ssh://git@<EXTERNAL_IP>:2222/your-group/your-project.git
```

## Manual Sealed Secret Creation

If you prefer to create sealed secrets manually:

### PostgreSQL Secret

```bash
kubectl create secret generic gitlab-postgresql \
  --namespace=gitlab \
  --from-literal=postgres-password=YOUR_STRONG_PASSWORD \
  --from-literal=password=YOUR_STRONG_PASSWORD \
  --from-literal=username=gitlab \
  --from-literal=database=gitlabhq_production \
  --dry-run=client -o yaml | \
  kubeseal --format=yaml > postgresql-sealedsecret.yaml
```

### GitLab Secret

```bash
# Generate random keys
DB_KEY=$(openssl rand -hex 64)
SECRET_KEY=$(openssl rand -hex 64)
OTP_KEY=$(openssl rand -hex 64)

kubectl create secret generic gitlab-secret \
  --namespace=gitlab \
  --from-literal=gitlab-root-password=YOUR_ROOT_PASSWORD \
  --from-literal=gitlab-secrets-db-key-base="${DB_KEY}" \
  --from-literal=gitlab-secrets-secret-key-base="${SECRET_KEY}" \
  --from-literal=gitlab-secrets-otp-key-base="${OTP_KEY}" \
  --dry-run=client -o yaml | \
  kubeseal --format=yaml > gitlab-sealedsecret.yaml
```

## Configuration

### Changing the External URL

Edit the `external_url` in `gitlab-deployment.yaml`:

```yaml
- name: GITLAB_OMNIBUS_CONFIG
  value: |
    external_url 'http://your-domain.com'
```

After changing, commit and ArgoCD will sync automatically.

### Email Configuration

To enable email notifications, update the OMNIBUS_CONFIG in `gitlab-deployment.yaml`:

```yaml
gitlab_rails['gitlab_email_enabled'] = true
gitlab_rails['gitlab_email_from'] = 'gitlab@yourdomain.com'
gitlab_rails['gitlab_email_display_name'] = 'GitLab'
gitlab_rails['smtp_enable'] = true
gitlab_rails['smtp_address'] = "smtp.server.com"
gitlab_rails['smtp_port'] = 465
gitlab_rails['smtp_user_name'] = "smtp user"
gitlab_rails['smtp_password'] = "smtp password"
gitlab_rails['smtp_domain'] = "yourdomain.com"
gitlab_rails['smtp_authentication'] = "login"
gitlab_rails['smtp_enable_starttls_auto'] = true
gitlab_rails['smtp_tls'] = true
```

### Resource Limits

Current resource allocation:
- **GitLab**: 4-8Gi RAM, 1-4 CPU cores
- **PostgreSQL**: 512Mi-2Gi RAM, 250m-1 CPU
- **Redis**: 256Mi-1Gi RAM, 100m-500m CPU

Adjust in the respective deployment files based on your workload.

## Initial Setup

1. Wait for all pods to be running (this takes 5-10 minutes):
   ```bash
   kubectl get pods -n gitlab
   ```

2. Monitor GitLab initialization:
   ```bash
   kubectl logs -n gitlab -l app=gitlab -f
   ```

3. GitLab is ready when you see: "gitlab Reconfigured!"

4. Access the web interface and log in with root credentials

5. **Change the root password immediately** after first login

6. Configure your GitLab instance:
   - Set up runners for CI/CD
   - Configure LDAP/OAuth if needed
   - Set up backup schedules
   - Configure container registry if needed

## Troubleshooting

### Sealed Secrets Not Decrypting

Check if sealed-secrets controller is running:
```bash
kubectl get pods -n kube-system -l name=sealed-secrets-controller
```

Verify the sealed secret was created:
```bash
kubectl get sealedsecrets -n gitlab
```

Check for decryption errors:
```bash
kubectl get events -n gitlab --sort-by='.lastTimestamp'
```

### GitLab Pod Not Starting

Check the logs:
```bash
kubectl logs -n gitlab -l app=gitlab --tail=100
```

Common issues:
- Insufficient memory (increase resources in deployment)
- Database connection issues (check PostgreSQL pod)
- PVC not binding (check storage class availability)
- Secrets not decrypted (check sealed-secrets controller)

### Database Connection Errors

Verify PostgreSQL is running:
```bash
kubectl get pods -n gitlab -l app=gitlab-postgresql
kubectl logs -n gitlab -l app=gitlab-postgresql
```

Test database connectivity from GitLab pod:
```bash
kubectl exec -n gitlab deployment/gitlab -it -- gitlab-rake gitlab:check
```

### Performance Issues

1. Increase Puma workers and threads in `gitlab-deployment.yaml`
2. Increase Sidekiq concurrency
3. Allocate more CPU/RAM resources
4. Scale PostgreSQL if needed

## Backup and Restore

### Manual Backup

```bash
kubectl exec -n gitlab deployment/gitlab -- gitlab-backup create
```

Backups are stored in `/var/opt/gitlab/backups` (on the gitlab-data PVC).

### Restore from Backup

```bash
# Copy backup file to pod
kubectl cp backup_file.tar -n gitlab deployment/gitlab:/var/opt/gitlab/backups/

# Stop services
kubectl exec -n gitlab deployment/gitlab -- gitlab-ctl stop puma
kubectl exec -n gitlab deployment/gitlab -- gitlab-ctl stop sidekiq

# Restore
kubectl exec -n gitlab deployment/gitlab -- gitlab-backup restore BACKUP=timestamp_of_backup

# Restart
kubectl exec -n gitlab deployment/gitlab -- gitlab-ctl restart
```

### Automated Backups

Create a CronJob for automated backups:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gitlab-backup
  namespace: gitlab
spec:
  schedule: "0 2 * * *"  # 2 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: gitlab/gitlab-ce:16.11.0-ce.0
            command:
            - /bin/bash
            - -c
            - gitlab-backup create
            volumeMounts:
            - name: gitlab-data
              mountPath: /var/opt/gitlab
          restartPolicy: OnFailure
          volumes:
          - name: gitlab-data
            persistentVolumeClaim:
              claimName: gitlab-data
```

## Monitoring

### Check Component Status

```bash
# All GitLab resources
kubectl get all -n gitlab

# Storage
kubectl get pvc -n gitlab

# Sealed secrets
kubectl get sealedsecrets -n gitlab

# Regular secrets (should exist after sealed secrets are decrypted)
kubectl get secrets -n gitlab

# Ingress
kubectl get ingress -n gitlab
```

### View Logs

```bash
# GitLab application logs
kubectl logs -n gitlab -l app=gitlab --tail=100 -f

# PostgreSQL logs
kubectl logs -n gitlab -l app=gitlab-postgresql --tail=100

# Redis logs
kubectl logs -n gitlab -l app=gitlab-redis --tail=100
```

### GitLab Internal Checks

```bash
# Run GitLab's internal health checks
kubectl exec -n gitlab deployment/gitlab -- gitlab-rake gitlab:check

# Check GitLab environment info
kubectl exec -n gitlab deployment/gitlab -- gitlab-rake gitlab:env:info
```

## Upgrading GitLab

To upgrade to a newer version:

1. Update the image tag in `gitlab-deployment.yaml`
2. Commit and push changes
3. ArgoCD will automatically sync the new version
4. Monitor the rollout:
   ```bash
   kubectl rollout status -n gitlab deployment/gitlab
   ```

**Important**: Always review [GitLab's upgrade path documentation](https://docs.gitlab.com/ee/update/) before upgrading. Some versions require specific upgrade paths.

## Security Recommendations

1. ✅ **Sealed Secrets**: Already using sealed secrets for sensitive data
2. 🔒 **Strong Passwords**: Use strong passwords when running create-sealed-secrets.sh
3. 🔐 **HTTPS**: Configure TLS certificates for production (update ingress)
4. 🛡️ **Network Policies**: Consider implementing network policies
5. 💾 **Backups**: Set up regular automated backups
6. 🔑 **2FA**: Enable two-factor authentication for all users
7. 📝 **Audit Logs**: Review GitLab admin panel security settings
8. 🚫 **Public Signup**: Disable public signup unless needed

## Useful Commands

```bash
# Get GitLab version
kubectl exec -n gitlab deployment/gitlab -- gitlab-rake gitlab:env:info | grep GitLab

# Reset root password (if locked out)
kubectl exec -n gitlab deployment/gitlab -it -- gitlab-rake "gitlab:password:reset[root]"

# Check database migrations
kubectl exec -n gitlab deployment/gitlab -- gitlab-rake db:migrate:status

# Clear cache
kubectl exec -n gitlab deployment/gitlab -- gitlab-rake cache:clear

# Check GitLab configuration
kubectl exec -n gitlab deployment/gitlab -- gitlab-rake gitlab:check SANITIZE=true
```

## Additional Resources

- [GitLab Official Documentation](https://docs.gitlab.com/)
- [GitLab on Kubernetes](https://docs.gitlab.com/ee/install/kubernetes/)
- [Sealed Secrets Documentation](https://sealed-secrets.netlify.app/)
- [GitLab Backup/Restore](https://docs.gitlab.com/ee/raketasks/backup_restore.html)
- [GitLab Runner Setup](https://docs.gitlab.com/runner/install/kubernetes.html)
