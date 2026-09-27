# Отчёт по домашней работе 2

## Выполнение

| Задание | Ссылка или результат |
|---|---|
| Зелёный пайплайн `tests` → `build` → `deploy` | [Прогон 36339776441](https://github.com/SunchesSun/credit-service/actions/runs/36339776441) |
| Итоговый зелёный пайплайн после всех исправлений | [Прогон 36345927955](https://github.com/SunchesSun/credit-service/actions/runs/36345927955) |
| Образ в GHCR | [Пакет credit-service](https://github.com/SunchesSun/credit-service/pkgs/container/credit-service), тег `sha-0599cb362f1363ea1b57f8aa8ed3fae98387fa44` |
| Интеграционные тесты ответов 200 и 422 | [`tests/test_integration.py`](https://github.com/SunchesSun/credit-service/blob/dfc8738ccab1f0c3495c95b732292f68b0e5042e/tests/test_integration.py) |
| Настройка `MODEL_PATH` из ConfigMap видна через `/health` | [`configmap.yaml`](https://github.com/SunchesSun/credit-service/blob/dfc8738ccab1f0c3495c95b732292f68b0e5042e/k8s/configmap.yaml), [`app.py`](https://github.com/SunchesSun/credit-service/blob/dfc8738ccab1f0c3495c95b732292f68b0e5042e/src/credit_service/service/app.py) |
| Smoke проверяет диапазон `score` | [`ci.yml`](https://github.com/SunchesSun/credit-service/blob/dfc8738ccab1f0c3495c95b732292f68b0e5042e/.github/workflows/ci.yml) |
| Pull request с красным и следующим зелёным тестом | [PR №2](https://github.com/SunchesSun/credit-service/pull/2), [красный прогон](https://github.com/SunchesSun/credit-service/actions/runs/36339299618), [зелёный прогон](https://github.com/SunchesSun/credit-service/actions/runs/36339500101) |
| Поломка ConfigMap | [красный](https://github.com/SunchesSun/credit-service/actions/runs/36341080062), [зелёный после исправления](https://github.com/SunchesSun/credit-service/actions/runs/36341727120) |
| Поломка Secret | [красный](https://github.com/SunchesSun/credit-service/actions/runs/36342273134), [зелёный после исправления](https://github.com/SunchesSun/credit-service/actions/runs/36342690030) |
| Поломка ресурсов | [красный](https://github.com/SunchesSun/credit-service/actions/runs/36343116328), [зелёный после исправления](https://github.com/SunchesSun/credit-service/actions/runs/36343685505) |
| Звёздочка: расширенная диагностика | [красный прогон](https://github.com/SunchesSun/credit-service/actions/runs/36345487325), [зелёный после возврата модели](https://github.com/SunchesSun/credit-service/actions/runs/36345927955) |

Итоговый прогон выполнен для коммита `baa4963e942145399f6eb9ca35f3c9cd9433e993`.
В нём `tests` занял 30 секунд, `build` — 17 секунд, `deploy` — 103 секунды.

## Три диагностические поломки

### 1. Неверный путь модели в ConfigMap

В [красном прогоне](https://github.com/SunchesSun/credit-service/actions/runs/36341080062) успешно закончились `tests` и `build`, а `deploy` упал на шаге `сервис`. В ConfigMap был указан отсутствующий файл `artifact/missing-model.joblib`, поэтому контейнер запускался, не мог загрузить модель и переходил в `CrashLoopBackOff`; диагностика показывала этот статус и ошибку открытия файла модели.

Исправление вернуло путь `artifact/model.joblib`. Следующий [прогон 36341727120](https://github.com/SunchesSun/credit-service/actions/runs/36341727120) прошёл полностью.

### 2. Несовпадающее имя Secret

В [красном прогоне](https://github.com/SunchesSun/credit-service/actions/runs/36342273134) `deploy` упал на шаге `сервис`. Deployment ссылался на `missing-credit-secrets`, хотя пайплайн создавал `credit-secrets`; pod находился в `CreateContainerConfigError`, потому что Kubernetes не мог сформировать переменные окружения контейнера из отсутствующего Secret.

После возврата имени `credit-secrets` [прогон 36342690030](https://github.com/SunchesSun/credit-service/actions/runs/36342690030) стал зелёным.

### 3. Недоступный объём памяти

В [красном прогоне](https://github.com/SunchesSun/credit-service/actions/runs/36343116328) `deploy` снова упал на шаге `сервис`. Контейнер запрашивал `1000000000Mi` памяти, поэтому планировщик не мог подобрать узел, а pod оставался в `Pending`; это было видно в выводе диагностики.

После возврата запроса `256Mi` и лимита `512Mi` итоговый [прогон 36343685505](https://github.com/SunchesSun/credit-service/actions/runs/36343685505) прошёл полностью.

## Ответы на семь вопросов

### 1. Время build и кэш Dockerfile

Первый [job build](https://github.com/SunchesSun/credit-service/actions/runs/36339776441/job/108677568321) шёл 68 секунд, второй [job build](https://github.com/SunchesSun/credit-service/actions/runs/36341080062/job/108681259596) — 20 секунд. Во втором запуске из кэша был доступен дорогой слой `RUN uv sync --frozen --no-dev --no-install-project`: его входы `pyproject.toml` и `uv.lock` не менялись, а изменение Kubernetes-манифеста не инвалидирует этот слой Dockerfile.

### 2. Почему виден `ImagePullBackOff`, но deploy зелёный

Команда `kubectl apply -f k8s/` сначала создаёт Deployment с исходным образом `credit-service:1.0`, которого нет в новом kind-кластере. Следующая команда `kubectl set image` указывает загруженный SHA-образ и создаёт актуальный ReplicaSet; после его успешного rollout временные pod старого ReplicaSet не влияют на результат job.

### 3. Путь пароля базы

Пароль начинается в GitHub Actions Secret `DB_PASSWORD`, попадает в одноимённую переменную окружения шага и передаётся в `kubectl create secret generic credit-secrets`. Kubernetes Secret содержит `POSTGRES_PASSWORD` и `DATABASE_URL`, а `secretRef`/`secretKeyRef` передают их в контейнеры API и PostgreSQL.

ConfigMap предназначен для несекретной конфигурации и доступен отдельно от Secret, поэтому пароль туда класть нельзя. Разделение также позволяет ограничивать доступ к чувствительным данным независимо от обычных настроек.

### 4. Что будет без `needs: tests`

Без `needs: tests` сборка сможет начаться параллельно с тестами. Если тесты обнаружат ошибку, `build` всё равно может опубликовать образ этого коммита, а зависимый от него `deploy` — попытаться развернуть непроверенную версию.

### 5. Почему в pull request выполняются только тесты

У `build` стоит условие `if: github.ref == 'refs/heads/main'`, поэтому на событии `pull_request` он пропускается; `deploy` также пропускается, потому что зависит от `build`. Это оставляет в PR быструю проверку кода и не публикует образ до попадания коммита в `main`.

### 6. Зачем нужен `pg_advisory_xact_lock`

Deployment API содержит две реплики, и оба pod при одновременном старте вызывают `init()` на одной пустой базе. `pg_advisory_xact_lock` сериализует выполнение DDL в рамках транзакций. Без блокировки обе реплики сервиса могли бы одновременно выполнять инициализацию и конфликтовать при создании объектов базы. один pod создаёт схему, второй продолжает после освобождения блокировки.

### 7. Порядок трёх статусов pod

Порядок по жизненному циклу: `Pending` → `CreateContainerConfigError` → `CrashLoopBackOff`. При огромном запросе памяти pod ещё не назначен на узел; при отсутствующем Secret он уже дошёл до подготовки конфигурации контейнера, но контейнер нельзя создать; при неверном пути модели контейнер запускается и падает, после чего Kubernetes увеличивает паузу между перезапусками.

## Журнал проблем

| Проблема | Как определена причина | Исправление |
|---|---|---|
| Неверные параметры PostgreSQL service container в первых прогонах PR | Job останавливался на `Initialize containers`; в workflow были опечатки в `--health-cmd` и `POSTGRES_PASSWORD` | Исправлены параметры healthcheck и имя переменной; [следующий зелёный прогон](https://github.com/SunchesSun/credit-service/actions/runs/36204784481) выполнил интеграционный тест с PostgreSQL |
| Workflow не создавал jobs после добавления build | GitHub отметил [прогон 36237924494](https://github.com/SunchesSun/credit-service/actions/runs/36237924494) как ошибочный на уровне workflow; проверка файла выявила неверное выражение для `env.IMAGE` и опечатки в шагах | Исправлены выражения GitHub Actions, build/push action, SHA-тег, имена kind, Secret и PostgreSQL |
| Неверный путь модели | `deploy` завершился ошибкой, pod перезапускался, а лог указывал на отсутствующий файл | В ConfigMap восстановлен `artifact/model.joblib` |
| Deployment ссылался на отсутствующий Secret | Статус `CreateContainerConfigError` появился до запуска контейнера; имя в Deployment не совпадало с именем, создаваемым CI | Восстановлен `secretRef: credit-secrets` |
| Pod нельзя было запланировать | Pod оставался `Pending` после запроса `1000000000Mi` памяти | Восстановлены request `256Mi` и limit `512Mi` |

## Дополнительные задания

### Диагностика богаче

`if: failure()` показывал только список pod, конец описания Deployment и текущий лог одного pod. Этого было недостаточно для pod, который ещё не запустился, или уже успел перезапуститься. В коммите `3f2c54b64b044d558a70a4548dc6768252ba86ca` шаг был расширен:

```bash
kubectl get pods -o wide
kubectl get events --sort-by=.lastTimestamp
kubectl describe pods -l app=credit
kubectl describe deploy/credit-service | tail -20
kubectl logs -l app=credit --all-containers=true --tail=50 --prefix=true || true
kubectl logs -l app=credit --all-containers=true --previous --tail=50 --prefix=true || true
```

События кластера показывают ошибки планирования и недоступные объекты, а `kubectl describe pods` показывает `Waiting` reason и события конкретного pod. Селектор `app=credit` собирает логи обеих реплик, а `--previous` сохраняет текст ошибки предыдущего запуска при `CrashLoopBackOff`.

Такой набор команд покрывает все три базовые поломки: события объясняют `Pending` при нехватке памяти, описание pod — `CreateContainerConfigError` при отсутствующем Secret, а предыдущий лог — падение загрузки модели при `CrashLoopBackOff`.

Проверка сделана отдельным коммитом `0fbe2995d119272808e6b000f59c389548bde9b8`: `MODEL_PATH` был заменён на `artifact/missing-model.joblib`. В [красном deploy job](https://github.com/SunchesSun/credit-service/actions/runs/36345487325/job/108693839746) шаг `сервис` завершился с ошибкой, а следующий шаг `диагностика` успешно выполнился. После возврата `artifact/model.joblib` в коммите `baa4963e942145399f6eb9ca35f3c9cd9433e993` [прогон 36345927955](https://github.com/SunchesSun/credit-service/actions/runs/36345927955) стал зелёным.
