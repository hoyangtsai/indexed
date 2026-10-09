#!/bin/sh
# Indexed only listens on loopback. Forward the container's external port to it;
# docker-compose publishes that port on the host's 127.0.0.1 only.
set -e
socat TCP-LISTEN:18768,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:18767 &
exec ./bin/indexed serve --host 127.0.0.1 --port 18767
