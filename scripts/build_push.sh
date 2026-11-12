#!/usr/bin/env bash
# Build the Nimbus service image and push it to the ECR repository Terraform created (P3 owns the image).
#
#   AWS_PROFILE=nimbus-p3 AWS_REGION=ap-south-1 scripts/build_push.sh [tag]   # default tag: git short SHA
#
# Every build is pushed twice: under an immutable-by-convention tag (the git short SHA, with `-dirty` appended when
# tracked files have uncommitted changes) and as `latest`. Terraform only redeploys when the task definition changes,
# and pushing a new `latest` does not change it, so deploy the commit tag or digest this script prints:
#   terraform -chdir=infra/terraform apply -var app_image=<repo>:<sha>
#
# Needs: Docker running, AWS credentials, git, and the repository to exist
# (`terraform apply -target=aws_ecr_repository.app` in infra/terraform, run by P4).
# The image is built for linux/amd64 because the Fargate task definition does not ask for ARM; building on an
# Apple Silicon Mac without --platform would give an image that fails on Fargate with "exec format error".
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "${1:-}" ]; then
  TAG="$1"
else
  TAG="$(git rev-parse --short HEAD)"
  git diff --quiet HEAD -- || TAG="${TAG}-dirty"
fi
[ "$TAG" = latest ] && { echo "pass a build tag other than 'latest' (latest is pushed as well automatically)" >&2; exit 2; }
REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REPO="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/nimbus-app"

aws ecr describe-repositories --repository-names nimbus-app --region "$REGION" >/dev/null \
  || { echo "ECR repository nimbus-app not found: ask P4 to run 'terraform apply -target=aws_ecr_repository.app'" >&2; exit 1; }

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
docker build --platform linux/amd64 --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" -t "nimbus-app:${TAG}" .
docker tag "nimbus-app:${TAG}" "${REPO}:${TAG}"
docker tag "nimbus-app:${TAG}" "${REPO}:latest"
docker push "${REPO}:${TAG}"
docker push "${REPO}:latest"
DIGEST="$(docker inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "${REPO}:${TAG}" 2>/dev/null | grep -m1 "^${REPO}@" || true)"
echo "pushed ${REPO}:${TAG} (also tagged latest)"
[[ "$TAG" == *-dirty ]] && echo "warning: built from a working tree with uncommitted changes; the tag does not identify the code" >&2
echo "Deploy this build (the ECR repository is MUTABLE, so the digest is the exact image):"
echo "  terraform -chdir=infra/terraform apply -var app_image=${REPO}:${TAG}"
[ -n "$DIGEST" ] && echo "  terraform -chdir=infra/terraform apply -var app_image=${DIGEST}"
exit 0
