#!/bin/sh
set -e

mkdir -p app/integrations/generated
python -m grpc_tools.protoc -I./proto --python_out=./app/integrations/generated ./proto/world_amazon.proto

