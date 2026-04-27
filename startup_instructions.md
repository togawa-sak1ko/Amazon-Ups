# Mini-Amazon C + Mini-UPS Startup Instructions

Use these exact steps to start everything cleanly.

## 1) Go to the wrapper repo root

```bash
cd /Users/nautilus/Desktop/Duke_Spring2026/ECE568/final_project/ups-amazon-c
```

Repo layout:
- `erss-project-zx158-zq65` for team C Mini-Amazon
- `erss-final-project-tl396-ldw59-hs452` for Mini-UPS
- `world_simulator_exec` for the world simulator

---

## 2) Start the full local stack (recommended)

```bash
./start_docker_only.sh
```

This script:
- starts the world simulator
- starts UPS
- writes `erss-project-zx158-zq65/.env`
- starts team C Amazon
- reads Amazon `world_id` from `/healthz`
- aligns UPS to the same `world_id`
- starts the UPS daemon in live mode

---

## 3) If ports 8080 or 8081 are already in use

```bash
AMAZON_HTTP_PORT=8190 UPS_HTTP_PORT=8191 ./start_docker_only.sh
```

This is the exact pattern used during Linux VM verification.

---

## 4) Optional VM world mode

```bash
USE_VM_WORLD=1 VM_WORLD_HOST=<VM_HOST_OR_IP> ./start_docker_only.sh
```

Use this only if you want Amazon and UPS to connect to a VM-hosted world simulator instead of the local world container.

---

## 5) Expected URLs after startup

- Amazon: `http://127.0.0.1:8080`
- UPS: `http://127.0.0.1:8081`

If you used port overrides, use those overridden ports instead.

---

## 6) Optional health checks

Default ports:

```bash
curl -s http://127.0.0.1:8080/healthz
curl -I http://127.0.0.1:8081/
```

Overridden ports:

```bash
curl -s http://127.0.0.1:8190/healthz
curl -I http://127.0.0.1:8191/
```

Expected:
- Amazon `/healthz` returns `{"status":"ok","world_id":...}`
- UPS home page responds successfully

---

## 7) Useful logs if something fails

World simulator:

```bash
cd /Users/nautilus/Desktop/Duke_Spring2026/ECE568/final_project/ups-amazon-c/world_simulator_exec/docker_deploy
docker-compose logs -f server
```

UPS:

```bash
cd /Users/nautilus/Desktop/Duke_Spring2026/ECE568/final_project/ups-amazon-c/erss-final-project-tl396-ldw59-hs452
docker-compose logs -f web
docker logs -f ups-daemon
```

Team C Amazon:

```bash
cd /Users/nautilus/Desktop/Duke_Spring2026/ECE568/final_project/ups-amazon-c/erss-project-zx158-zq65
docker-compose logs -f web
docker-compose logs -f worker
```

---

## 8) Quick recovery

If Docker reports stale containers or old daemon state:

```bash
docker rm -f ups-daemon >/dev/null 2>&1 || true
./start_docker_only.sh
```
