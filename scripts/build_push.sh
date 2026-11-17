#!/usr/bin/env bash
# Build the Nimbus service image and push it to the ECR repository Terraform created (P3 owns the image).
#
#   AWS_PROFILE=nimbus-p3 AWS_REGION=ap-south-1 scripts/build_push.sh [tag]      # default tag: the current commit
#
# ECR tags are immutable (#20): every push needs a new tag, and `latest` is refused. The default tag is the short
# commit hash, plus a UTC timestamp when the working tree has uncommitted or untracked files, so a tag always names
# one exact build. Deploy what was pushed with
#   terraform -chdir=infra/terraform apply -var app_image_tag=<tag>
# which pins the task definition to that image's digest.
#
# Needs: Docker running, AWS credentials, and the repository to exist
# (`terraform apply -target=aws_ecr_repository.app` in infra/terraform, run by P4).
# The image is built for linux/amd64 because the Fargate task definition does not ask for ARM; building on an
# Apple Silicon Mac without --platform would give an image that fails on Fargate with "exec format error".
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -gt 0 ]]; then
  TAG="$1"
else
  TAG="$(git rev-parse --short=12 HEAD)"
  if [[ -n "$(git status --porcelain)" ]]; then
    TAG="${TAG}-dirty-$(date -u +%Y%m%dT%H%M%SZ)"
  fi
fi
if [[ "$TAG" == "latest" ]]; then
  echo "Refusing to push 'latest': tags are immutable and Terraform deploys a pinned commit tag (issue #20)." >&2
  echo "Run without an argument to tag the image with the current commit." >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REPO="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/nimbus-app"

aws ecr describe-repositories --repository-names nimbus-app --region "$REGION" >/dev/null \
  || { echo "ECR repository nimbus-app not found: ask P4 to run 'terraform apply -target=aws_ecr_repository.app'" >&2; exit 1; }

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
docker build --platform linux/amd64 -t "nimbus-app:${TAG}" .
docker tag "nimbus-app:${TAG}" "${REPO}:${TAG}"
docker push "${REPO}:${TAG}"
DIGEST="$(aws ecr describe-images --repository-name nimbus-app --region "$REGION" --image-ids imageTag="$TAG" \
  --query 'imageDetails[0].imageDigest' --output text)"
echo "pushed ${REPO}:${TAG} (${DIGEST})"
echo "Deploy it: terraform -chdir=infra/terraform apply -var app_image_tag=${TAG}"
