# Step 7 — Remove the `prod-neuradigi` deploy target

**Goal:** only the `local` and `prod` environments exist.

## Files

- `APP/src/environments/environment.neuradigi.ts` — deleted.
- `APP/angular.json` — remove the `production-neuradigi` build and serve configurations.
- `API/docker-compose.prod-neuradigi.yml` — deleted.
- `API/run.cmd`, `API/run.sh` — env validation, `env`, `secrets-edit`, `secrets-rekey` accept `local|prod` only; help text updated.
- `API/.sops.yaml` — remove the `secrets.prod-neuradigi.enc.env` rule.
- `API/config.local.env`, `API/config.prod.env`, `APP/src/environments/environment*.ts` — comments that
  reference the Neuradigi deploy or repo.

## Tests

- `run env prod-neuradigi` is rejected with the local/prod message (cmd + sh).
- `npm run build` and `ng build --configuration development` succeed.
