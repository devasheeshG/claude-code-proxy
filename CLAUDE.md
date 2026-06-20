# Project Instructions

## Task tracking

- Always track tasks and keep their statuses current.
- Include an approximate ETA in every pending or in-progress task title, and update it as work progresses.
- When a task is finished, mark it completed and remove the ETA from its title.

## Deployment safety

- Use `scripts/blue-green.sh` / `make deploy-blue-green` for production changes.
- Keep one Traefik instance on the shared network and never publish a second
  gateway on the same ports.
- The script waits for healthchecks, probes `/api/health` continuously, promotes
  and verifies the backend before the frontend, and drains the old slot only
  after both routes identify the new slot. Avoid in-place `up --build` for live
  updates.
- Check `scripts/blue-green.sh status` and render Compose with
  `BG_SLOT=blue BG_PRIORITY=1 BG_API_PRIORITY=2 docker compose ... config --quiet`
  before modifying deployment files.
