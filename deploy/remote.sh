#!/usr/bin/env bash
# Runs on the server: deploy.py uploads it and runs it. The first time it installs Docker and adds
# swap. Every time it puts the uploaded code in place (with --data the listing data too, which
# setup_database.py then imports), builds the images and starts or restarts the containers.
set -euo pipefail

UPLOAD="$HOME/dss5105-upload"
CODE="$HOME/dss5105"
DATA_DIR="$HOME/dss5105-data"
CONFIG_DIR="$HOME/dss5105-config"
DATA=false
if [ "${1:-}" = "--data" ]; then DATA=true; fi
if ! $DATA && [ ! -d "$DATA_DIR/output-final-delivery" ]; then
  echo "The server has no listing data yet: the first deployment needs --data." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "== First run: installing Docker =="
  curl -fsSL https://get.docker.com | sudo sh
fi
if ! sudo swapon --show=NAME --noheadings | grep -qx /swapfile; then
  echo "== Adding 2 GB of swap, so building images does not fail when memory is short =="
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
if [ -f "$UPLOAD/server.env" ]; then
  tr -d '\r' < "$UPLOAD/server.env" > "$CONFIG_DIR/server.env"
  chmod 600 "$CONFIG_DIR/server.env"
  rm -f "$UPLOAD/server.env"
fi

echo "== Updating the code =="
rm -rf "$CODE.new"
mkdir -p "$CODE.new"
tar -xzf "$UPLOAD/code.tar.gz" -C "$CODE.new"
rm -rf "$CODE"
mv "$CODE.new" "$CODE"
if $DATA; then
  echo "== Updating the listing data =="
  rm -rf "$DATA_DIR.new"
  mkdir -p "$DATA_DIR.new"
  tar -xzf "$UPLOAD/data.tar.gz" -C "$DATA_DIR.new"
  rm -rf "$DATA_DIR"
  mv "$DATA_DIR.new" "$DATA_DIR"
fi
rm -f "$UPLOAD"/*.tar.gz

compose() {
  sudo DATA_DIR="$DATA_DIR" docker compose --project-name dss5105 \
    -f "$CODE/deploy/docker-compose.yml" --env-file "$CONFIG_DIR/server.env" "$@"
}

echo "== Building the images (a few minutes the first time) =="
compose build
if $DATA; then
  echo "== Importing the listings and commute times =="
  compose up -d --wait db
  compose run --rm -T backend python setup_database.py
fi
echo "== Starting =="
compose up -d --remove-orphans
# Caddy reads the Caddyfile from the code folder, which was just replaced.
compose up -d --force-recreate --no-deps caddy
sudo docker image prune -f >/dev/null
sleep 5
compose ps
echo "== The backend's latest log =="
compose logs --tail=15 backend
