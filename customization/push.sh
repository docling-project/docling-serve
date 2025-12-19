#!/usr/bin/env bash

region="us-east-1"
account_id=$(aws sts get-caller-identity --query Account --output text)
ecr_repo_uri="${account_id}.dkr.ecr.us-east-1.amazonaws.com"
version='v1.9.0' # this matches the version in pyproject.toml, the upstream docling-serve version

aws ecr get-login-password --region "${region}" | \
	  docker login --username AWS --password-stdin "${ecr_repo_uri}"

docker push $ecr_repo_uri/docling-sagemaker:$version