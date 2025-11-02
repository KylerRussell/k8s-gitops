#!/bin/bash
set -e

echo "Creating Sealed Secrets for GitLab..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

NAMESPACE="gitlab"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECTL="/usr/local/bin/kubectl"
KUBESEAL="/opt/homebrew/bin/kubeseal"

# Check if kubectl is available
if [ ! -x "$KUBECTL" ]; then
    echo "Error: kubectl not found at $KUBECTL"
    exit 1
fi

# Check if kubeseal is available
if [ ! -x "$KUBESEAL" ]; then
    echo "Error: kubeseal not found at $KUBESEAL"
    exit 1
fi

# Function to create sealed secret
create_sealed_secret() {
    local secret_name=$1
    local output_file=$2
    shift 2
    local args=("$@")
    
    echo -e "${YELLOW}Creating sealed secret: ${secret_name}${NC}"
    
    $KUBECTL create secret generic "${secret_name}" \
        --namespace="${NAMESPACE}" \
        "${args[@]}" \
        --dry-run=client -o yaml | \
        $KUBESEAL --format=yaml > "${SCRIPT_DIR}/${output_file}"
    
    echo -e "${GREEN}✓ Created ${output_file}${NC}"
}

# PostgreSQL Secret
echo ""
echo "=== PostgreSQL Secret ==="
read -sp "Enter PostgreSQL password (or press enter for default 'changeme123'): " POSTGRES_PASS
POSTGRES_PASS=${POSTGRES_PASS:-changeme123}
echo ""

create_sealed_secret "gitlab-postgresql" "postgresql-sealedsecret.yaml" \
    --from-literal=postgres-password="${POSTGRES_PASS}" \
    --from-literal=password="${POSTGRES_PASS}" \
    --from-literal=username=gitlab \
    --from-literal=database=gitlabhq_production

# GitLab Root Secret
echo ""
echo "=== GitLab Root Password ==="
read -sp "Enter GitLab root password (or press enter for default 'changeme123'): " GITLAB_ROOT_PASS
GITLAB_ROOT_PASS=${GITLAB_ROOT_PASS:-changeme123}
echo ""

echo ""
echo "=== GitLab Secret Keys ==="
echo "Generating random secret keys..."

# Generate secure random keys
DB_KEY=$(openssl rand -hex 64)
SECRET_KEY=$(openssl rand -hex 64)
OTP_KEY=$(openssl rand -hex 64)

create_sealed_secret "gitlab-secret" "gitlab-sealedsecret.yaml" \
    --from-literal=gitlab-root-password="${GITLAB_ROOT_PASS}" \
    --from-literal=gitlab-secrets-db-key-base="${DB_KEY}" \
    --from-literal=gitlab-secrets-secret-key-base="${SECRET_KEY}" \
    --from-literal=gitlab-secrets-otp-key-base="${OTP_KEY}"

echo ""
echo -e "${GREEN}=== Sealed Secrets Created Successfully! ===${NC}"
echo ""
echo "Files created:"
echo "  - postgresql-sealedsecret.yaml"
echo "  - gitlab-sealedsecret.yaml"
echo ""
echo "Passwords used:"
echo "  - PostgreSQL: ${POSTGRES_PASS}"
echo "  - GitLab root: ${GITLAB_ROOT_PASS}"
echo ""
echo "Next steps:"
echo "  1. Review the sealed secret files"
echo "  2. Commit the sealed secrets to git"
echo "  3. Apply the ArgoCD application: kubectl apply -f ../../base/gitlab.yaml"
echo ""
echo -e "${YELLOW}Note: Keep your passwords in a secure location!${NC}"
