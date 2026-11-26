# Service containers

Service containers run on Linux runners only (GitHub-hosted `ubuntu-*` or self-hosted
Linux with Docker). The runner starts them before the first step and, with health
options, waits until they report healthy.

## Postgres

```yaml
services:
  postgres:
    image: postgres:17
    env:
      POSTGRES_PASSWORD: postgres     # required by the image (test-only value)
      POSTGRES_DB: app_test
    ports: ["5432:5432"]
    options: >-
      --health-cmd "pg_isready -U postgres"
      --health-interval 5s
      --health-timeout 5s
      --health-retries 10
env:
  DATABASE_URL: postgres://postgres:postgres@localhost:5432/app_test
```

## MySQL / MariaDB

```yaml
services:
  mysql:
    image: mysql:8.4
    env:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: app_test
    ports: ["3306:3306"]
    options: >-
      --health-cmd "mysqladmin ping -h 127.0.0.1 -proot"
      --health-interval 5s --health-timeout 5s --health-retries 20
```

Use `127.0.0.1` rather than `localhost` in MySQL clients on the runner (`localhost`
means the Unix socket for the mysql CLI). Ubuntu runner images also ship a MySQL server
that is stopped by default; do not start it alongside the service on 3306.

## Redis / Valkey

```yaml
services:
  redis:
    image: redis:8
    ports: ["6379:6379"]
    options: --health-cmd "redis-cli ping" --health-interval 5s --health-timeout 3s --health-retries 10
```

## MongoDB

```yaml
services:
  mongo:
    image: mongo:8
    ports: ["27017:27017"]
    options: --health-cmd "mongosh --quiet --eval 'db.runCommand({ping:1})'" --health-interval 5s --health-retries 20
```

## Job on the runner vs in a container

| | Job on the runner | Job in `container:` |
| --- | --- | --- |
| Reach the service at | `localhost:<mapped port>` | `<service name>:<container port>` |
| `ports:` needed | yes | no |
| Example host | `localhost:5432` | `postgres:5432` |

Random host port: `ports: ["5432"]` and read `${{ job.services.postgres.ports['5432'] }}`.

## Credentials

The passwords above are throwaway values for an ephemeral container that is reachable only
from the job. Do not reuse real credentials; do not put `secrets.*` into service env unless
the image needs a licence key or a private registry login (`credentials:` with username and
password from secrets).

## Matrix over database versions

```yaml
strategy:
  matrix:
    pg: [15, 16, 17]
services:
  postgres:
    image: postgres:${{ matrix.pg }}
```

## When to use Docker Compose instead

Multi-container setups with custom networks, init scripts or build steps are easier as a
step:

```yaml
- run: docker compose -f compose.test.yml up -d --wait
- run: npm run test:integration
- if: always()
  run: docker compose -f compose.test.yml logs --no-color > compose.log
```

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `connection refused` on localhost | job in a container (use service name) or no `ports:` |
| `database system is starting up` | no health options; add `--health-cmd` |
| Postgres container exits immediately | `POSTGRES_PASSWORD` missing |
| Error that container operations are only supported on Linux | macOS/Windows runner |
| Works locally, flaky in CI | tests share one database across parallel matrix jobs - each job has its own service, but parallel test workers in one job need separate schemas |
