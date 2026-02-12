#!/usr/bin/env bash

version='v1.12.0' # this matches the version in pyproject.toml, the upstream docling-serve version
cd ..

account_id=$(aws sts get-caller-identity --query Account --output text)
# docker build --no-cache --platform linux/amd64 -t harbor.onebrief.tools/onebrief/docling-sagemaker:$version .
docker build --platform linux/amd64 --provenance=false --output type=docker -t $account_id.dkr.ecr.us-east-1.amazonaws.com/docling-sagemaker:$version .