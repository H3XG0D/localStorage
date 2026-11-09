# Casino deployment status

## Production rollout заблокирован

Не запускайте `DEPLOY_CASINO_FRONTEND.sh`, не применяйте casino-миграции и не перезапускайте production-сервисы по этому документу.

Casino-контур требует отдельного утверждённого runbook: резервной копии PostgreSQL, проверки исторических principal-зачислений, ручного применения миграций с `ON_ERROR_STOP=1`, изолированного end-to-end тестирования и post-checks.

Актуальные обязательные условия и безопасные локальные проверки находятся в [`../focuspay-casino/QUICKSTART.md`](../focuspay-casino/QUICKSTART.md) и [`CASINO_DEPLOYMENT.md`](CASINO_DEPLOYMENT.md).

Raffle отключён (`RAFFLE_ENABLED=False`) и не может быть включён или использован с реальными средствами до появления отдельного доверенного backend-расчёта и серверной проверки условий.
