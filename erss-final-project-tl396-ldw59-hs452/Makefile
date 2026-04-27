run:
	python3 manage.py runserver

migrate:
	python3 manage.py migrate

makemigrations:
	python3 manage.py makemigrations

test:
	python3 manage.py test

daemon:
	python3 manage.py run_world_daemon --once --dry-run

# Regenerate world protobuf Python from proto/world_ups.proto (installs grpcio-tools via pip).
proto:
	python3 -m pip install -q 'grpcio-tools>=1.59,<2'
	python3 -m grpc_tools.protoc --proto_path=proto --python_out=ups/world/generated proto/world_ups.proto
	@echo "Generated ups/world/generated/world_ups_pb2.py"

