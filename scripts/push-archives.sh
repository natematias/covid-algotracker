#!/usr/bin/env bash

set -e

repo_path="$1"
run_dt=`date -u --rfc-3339=seconds`

if [ -z "$repo_path" ]; then
  echo "usage: push-archives.sh REPO_PATH"
  exit 1;
fi

cd $repo_path

echo Pulling latest version...
git pull
echo Pushing archives...
echo Adding changes.
git add data-archive/*
git add page-archive/*
git add index.html
git add assets/preview-image.png

echo Committing archives.
git commit -m "Automated archive update at $run_dt"
git push origin

echo Archives successfully pushed."
