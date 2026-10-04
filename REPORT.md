# Отчёт по домашней работе 3

| Пункт | Доказательства |
|---|---|
| 2.1 Платформа | [pod и Ingress](docs/hw3/kind-mlpro3_pods.png), [MLflow Model training](docs/hw3/mlflow_model_traning.png) |
| 2.2 Обучение и гейт | [версии и алиасы](docs/hw3/mlflow_model_registry_aliases.png), [решения гейта](docs/hw3/train_runs.txt) |
| 2.3 Откат | [`/health` до](docs/hw3/health_before_rollback.json) и [после](docs/hw3/health_after_rollback.json) |
| 2.4 Деплой | [зелёный прогон](https://github.com/SunchesSun/credit-service/actions/runs/37229900482), [runner](docs/hw3/github_actions_runner.png) |
| 2.5 DVC | [указатель данных](datasets/german_credit_data.csv.dvc), [проверки](docs/hw3/dvc_verification.txt), [два запуска MLflow](docs/hw3/mlflow_dvc_data_versions.png) |
| 2.6 HPA | [рост и снижение реплик](docs/hw3/hpa_replicas.png), [события HPA](docs/hw3/hpa_describe.txt), [статистика Locust](docs/hw3/locust_10_stats.csv) |
| 2.7 Диагностические прогоны | Пока не выполнено |

## 2.1. Кластер, MLflow и Ingress

Кластер `kind-mlpro3` создан по [`platform/kind-config.yaml`](platform/kind-config.yaml): порт 80 на `127.0.0.1` проброшен на NodePort 30080 Traefik. Через Ingress доступны `mlflow.localhost` и `credit.localhost`. В [`platform/mlflow.yaml`](platform/mlflow.yaml) настроены `--allowed-hosts=mlflow.mlops*,mlflow.localhost*,localhost*,127.0.0.1*`, `--cors-allowed-origins=http://mlflow.localhost` и `MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false`.

[Скрин pod и Ingress](docs/hw3/kind-mlpro3_pods.png) показывает работающие компоненты кластера и маршруты; [скрин MLflow в режиме Model training](docs/hw3/mlflow_model_traning.png) показывает запуск обучения. Повторная проверка `kubectl --context kind-mlpro3 get pods,ingress -A` показала две готовые реплики API, PostgreSQL, MLflow, Traefik и metrics-server; Ingress `credit.localhost` и `mlflow.localhost` присутствуют.

## 2.2. Обучение и гейт MLflow

В исходных данных класс `bad` встречается реже `good` (300 и 700 строк соответственно), поэтому для гейта выбрана PR-AUC по вероятности `bad`. Запас `GATE_MIN_GAIN=0.01` требует прироста PR-AUC больше 0.01 относительно текущего `champion`; равный результат, как у версии 2, не меняет алиас. Во всех трёх запусках ниже использовались одинаковые данные и разбиение (`random_state=42`), а менялись сила регуляризации `C` и вес класса `bad`.

| Версия | Run ID | `C` | Вес `bad` | PR-AUC | Решение гейта | `champion` после запуска |
|---|---|---:|---:|---:|---|---|
| 3 | `59baab5362b948b4859d6c2b31b0cf10` | 0.007 | 1 | 0.628601 | Принята: предыдущая версия 1 имела 0.617173 | 3 |
| 4 | `29f04cb543314db1a940b7486447d604` | 0.000001 | 1 | 0.579212 | Отклонена; версия 4 получила только `challenger` | 3 |
| 5 | `2543660b024f407b9125b5aa8d92ca29` | 0.01 | 2 | 0.644035 | Принята: прирост относительно версии 3 равен 0.015435 | 5 |

Каждый запуск сохранил `metadata.json` с признаками и порогом, `confusion_matrix.json` и собственный артефакт `precision_recall_curve.png` через `mlflow.log_figure`. Параметр `data_md5` во всех трёх запусках равен `3086216ff1ff32f7626554e730cccc91`.
Копия [PR-кривой версии 5](docs/hw3/precision_recall_curve.png) сохранена вместе с доказательствами задания.
Вывод команд с решениями гейта сохранён в [`docs/hw3/train_runs.txt`](docs/hw3/train_runs.txt).

## 2.3. Откат модели

Сервис загружает модель по алиасу `german-credit@champion` при запуске; без `MODEL_NAME` остаётся загрузка локального файла для CI. После обучения версии 5 pod были перезапущены, и [`/health` до отката](docs/hw3/health_before_rollback.json) показывал `german-credit-v5`. Затем в MLflow Model registry алиас `champion` был перенесён с версии 5 на прежний champion, версию 3. После `kubectl rollout restart deploy/credit-service` [`/health` после отката](docs/hw3/health_after_rollback.json) показывал `german-credit-v3`; обе реплики стали Ready. Образ Deployment остался `ghcr.io/sunchessun/credit-service:sha-87abc5e6ced57069822c47fb0865436d1cf7c5ed`, пересборки не было.

После клика в UI первый ответ `/health` со старой версией появился **примерно через 9–10 секунд**. Наблюдение проверяло алиас каждые 0,5 секунды; измеренное время от обнаружения смены алиаса до ответа составило 8,95 секунды. Поэтому время от клика указано приблизительно: задержка до обнаружения алиаса отдельно не измерялась. Полный rollout занял 20,3 секунды. После опыта `champion` указывает на версию 3, `challenger` — на версию 5.
Версии модели и колонка алиасов видны на [скрине Model registry](docs/hw3/mlflow_model_registry_aliases.png).

## 2.4. CI/CD и smoke-проверка

Job `deploy` в `.github/workflows/ci.yml` выполняется на runner с метками `self-hosted` и `kind`. Контейнер `gh-runner` запущен в Docker-сети `kind`; его зарегистрированное имя — `mlpro3-kind`. Шаг создания `credit-secrets` применяет результат `kubectl create secret --dry-run=client -o yaml` через `kubectl apply`, поэтому повторный деплой обновляет Secret.

Smoke-шаг обращается к сервису через Traefik Ingress (`Host: credit.localhost`, порт 30080 узла `mlpro3-control-plane`). Он проверяет, что `/health` сообщает о загрузке `models:/german-credit@champion`, отправляет пример из `good.json` в `/v1/predict`, проверяет вероятность, решение по порогу 0.5 и версию модели, затем ищет в PostgreSQL ровно одну строку с тем же `request_id`, версией и кодом 200.

Этот smoke-скрипт извлечён из workflow и успешно выполнен внутри контейнера `gh-runner` на работающем кластере: `/health` показал `german-credit-v3`, ответ предсказания содержал `score=0.1887866461272916`, `is_bad_risk=false`, `model_version=german-credit-v3`, а проверка строки в PostgreSQL завершилась с кодом 0.

После публикации изменений [workflow run #33](https://github.com/SunchesSun/credit-service/actions/runs/37229900482) для коммита `15afa42e8018e737b8389cafa2919543a84db11e` на `main` завершился успешно: jobs `tests`, `build` и [`deploy`](https://github.com/SunchesSun/credit-service/actions/runs/37229900482/job/111517592279) зелёные. В `deploy` использовался runner `mlpro3-kind`, а шаг `smoke` завершился успешно. В кластере после этого запущен образ с тем же SHA, обе реплики API доступны; дополнительный запрос через Ingress вернул `german-credit-v3`, и PostgreSQL содержал ровно одну строку с его `request_id` и кодом 200.

По подтверждению владельца репозитория в Settings → Actions → General включено `Require approval for all external contributors`.
На [скриншоте Settings → Actions → Runners](docs/hw3/github_actions_runner.png) видны runner `mlpro3-kind`, метка `kind` и статус `Idle` (runner онлайн и ожидает задания).

## 2.5. Версии данных в DVC

Исходный `datasets/german_credit_data.csv` перенесён из Git в DVC в коммите `9030a294334cb3a642831491b227b8f3630d3562`. Репозиторий хранит [`datasets/german_credit_data.csv.dvc`](datasets/german_credit_data.csv.dvc) с MD5 и размером файла, а сам CSV исключён из Git через `datasets/.gitignore`. Локальный remote DVC — `../dvc-storage` относительно корня проекта; в `.dvc/config` он записан как `../../dvc-storage`. Зависимость DVC уже была в `pyproject.toml`, поэтому добавлять её повторно не потребовалось.

В коммите `6e15c46a24e41a962d604e6c6873e3bfb449081a` создана вторая версия: удалены 99 строк, в которых одновременно отсутствовали `Saving accounts` и `Checking account`. В ней 901 строка вместо 1000. Для обеих версий `dvc push` вывел `1 file pushed`; `dvc diff HEAD~1` показал `Modified: datasets/german_credit_data.csv`. После переключения указателя и `dvc checkout` восстановились сначала исходные 1000 строк с MD5 `3086216ff1ff32f7626554e730cccc91`, затем 901 строка с MD5 `75716716a440972dfc0fed80bb7791cc`. В отдельном чистом клоне `dvc pull` вывел `1 file fetched and 1 file added` и восстановил текущий CSV с тем же MD5. [Вывод проверок](docs/hw3/dvc_verification.txt).

| Версия модели в MLflow | Run ID | Строк данных | `data_md5` | PR-AUC |
|---|---|---:|---|---:|
| 6 | `29418906d9394f0f8e832f3b5dbc7fba` | 1000 | `3086216ff1ff32f7626554e730cccc91` | 0.617173 |
| 7 | `512a720820a3424393a614992ada0c3d` | 901 | `75716716a440972dfc0fed80bb7791cc` | 0.610738 |

[Скрин сравнения двух запусков MLflow](docs/hw3/mlflow_dvc_data_versions.png) показывает оба Run ID и разные `data_md5`.

Оба запуска не прошли гейт относительно `champion` версии 3, поэтому работающий сервис продолжает использовать прежнюю модель. После переноса CSV тесты не требуют полного датасета (`25 passed`, `2 skipped`), Ruff также прошёл. Dockerfile копирует `src/` и `artifact/`, а CSV не копирует.

## 2.6. HPA

Metrics-server установлен в `kube-system` чартом версии 3.14.0 с [`platform/metrics-server-values.yaml`](platform/metrics-server-values.yaml). До установки `kubectl top nodes` отвечал `Metrics API not available`; после установки он и `kubectl top pods` показывают цифры. Для kind потребовался `--kubelet-insecure-tls`. При первом запуске pod metrics-server получил `ImagePullBackOff`: узел не смог подключиться к IPv6-адресу `registry.k8s.io`. После `docker pull` на хосте и `kind load docker-image` pod запустился, а Helm завершился успешно.

[`k8s/hpa.yaml`](k8s/hpa.yaml) управляет `credit-service` по CPU: цель 60% от `requests.cpu`, минимум 2 и максимум 6 реплик. Нагрузка из [`locustfile.py`](locustfile.py) посылала `good.json` через Ingress `http://credit.localhost`. По выборке `kubectl top pods` CPU в таблице — медиана по pod после первой минуты каждого прогона; все три прогона имели 0 ошибок.

| Пользователи | Длительность | Запросы | Реплики во время прогона | p95 | CPU на pod, медиана |
|---:|---:|---:|---|---:|---:|
| 1 | 2 мин | 347 | 2 | 88 мс | 22,5m |
| 5 | 3 мин | 2538 | 2 → 4 | 110 мс | 52,5m |
| 10 | 2 мин | 3235 | 2 → 4 → 6 | 160 мс | 70m |

Вывод [наблюдения HPA](docs/hw3/hpa_watch.txt), [периодические замеры CPU и памяти](docs/hw3/hpa_samples.csv), [график числа реплик](docs/hw3/hpa_replicas.png) и CSV статистики Locust для [1](docs/hw3/locust_1_stats.csv), [5](docs/hw3/locust_5_stats.csv) и [10](docs/hw3/locust_10_stats.csv) пользователей сохранены. В первом прогоне рост до 4 реплик наблюдался через примерно 51 секунду, до 6 — через примерно 72 секунды. После остановки 10 пользователей снижение до 2 произошло примерно через 5 минут 36 секунд: HPA удерживал прежние рекомендации в окне стабилизации. [Вывод `kubectl describe hpa`](docs/hw3/hpa_describe.txt) содержит события `SuccessfulRescale` для увеличения и уменьшения числа pod.

До замера ресурсы контейнера были `requests.cpu=100m`, `requests.memory=256Mi`, лимиты `1 CPU` и `512Mi`. Максимальная наблюдавшаяся память pod во всех прогонах — 200Mi. Поэтому CPU request оставлен 100m, а memory request установлен в 272Mi: это около трети запаса над измеренным максимумом. Лимиты остались прежними. Изменение применено к работающему Deployment без смены образа; rollout завершился успешно, обе реплики Ready, `/health` возвращает `german-credit-v3`. Сразу после замены pod HPA временно показывал `<unknown>`, затем снова получил метрики и показал 1%/60%.

## 2.7. Три диагностических прогона

Этот пункт ещё не выполнен: отдельных красных и следующих зелёных прогонов для трёх заданных поломок пока нет.

## Ответы на восемь вопросов

### 1. Почему облачные tests и build, но локальный deploy

Tests и build не требуют доступа к локальному kind-кластеру, поэтому выполняются на runner GitHub. Кластер находится в локальной Docker-сети за NAT и напрямую недоступен такому runner. Код можно было бы доставлять через публичный API Kubernetes, VPN/туннель или GitOps-контроллер, который сам забирает изменения; здесь выбран runner в сети kind, потому что ему доступны кластер и локальный Docker daemon.

### 2. Зачем runner три параметра Docker

`--network kind` даёт контейнеру runner доступ к адресу `mlpro3-control-plane` внутри Docker-сети; без него кластер по этому имени не виден. Монтирование `/var/run/docker.sock` позволяет шагам `docker pull` и `kind load docker-image` обращаться к Docker daemon хоста; без сокета эти команды не смогут работать с Docker хоста. `--group-add 0` добавляет группу root и помог бы, если бы сокет принадлежал этой группе, но в текущем запуске сокет имеет группу `runner` (GID 1001), в которой пользователь runner уже состоит; поэтому именно здесь удаление `--group-add 0` не должно лишить его доступа к сокету.

### 3. Зачем `--dry-run=client -o yaml | kubectl apply`

`kubectl create secret` без этого конвейера завершился бы ошибкой `AlreadyExists` при втором деплое. Команда с `--dry-run=client` формирует манифест, а `kubectl apply` создаёт Secret при первом запуске и обновляет его при повторном. Пароль передаётся из GitHub Secret в шаг deploy.

### 4. `challenger`, `champion` и два отката

Каждая обученная версия получает `challenger`; `champion` переносится только при прохождении гейта PR-AUC. Сервис запрашивает алиас, чтобы можно было заменить модель без изменения образа и кода: для отката алиас вернули с версии 5 на 3 и перезапустили pod. `rollout undo` вместо этого откатывает Kubernetes Deployment к прошлой конфигурации и образу; он не меняет алиасы MLflow.

### 5. Деплой до обучения первой модели

Если алиас `german-credit@champion` ещё не создан, загрузка модели при старте сервиса завершится ошибкой. В k9s pod будет перезапускаться, а в его логе будет ошибка поиска модели или алиаса; в CI `kubectl rollout status` не дождётся готовых реплик, после чего выполнится шаг диагностики. Это ожидаемое следствие текущего кода загрузки, а не отдельный проведённый красный прогон.

### 6. Путь запроса к MLflow

Браузер открывает `http://mlflow.localhost` на порту 80 хоста. Проброс kind ведёт на порт 30080 узла, Traefik выбирает маршрут Ingress по имени хоста и отправляет запрос через Service `mlflow` на порт 5000 pod. `--allowed-hosts` разрешает эти Host-заголовки, а `--cors-allowed-origins` разрешает обращения UI с `http://mlflow.localhost`; порт 80 закреплён в конфигурации kind при создании контейнера узла.

### 7. Расчёт числа реплик HPA

При 5 пользователях HPA видел 102% CPU на двух pod при цели 60%: `ceil(2 × 102 / 60) = 4`, и наблюдалось увеличение до 4. В прогоне с 10 пользователями при четырёх pod измерено 212%: формула дала бы `ceil(4 × 212 / 60) = 15`, но `maxReplicas=6`, поэтому HPA остановился на 6. После прекращения нагрузки снижение заняло около 5 минут 36 секунд из-за окна стабилизации, которое удерживает предыдущие рекомендации.

### 8. Что хранит Git и как восстановить данные версии модели

Git хранит `.dvc`-указатель с MD5 и размером CSV, а содержимое файла находится в локальном DVC remote `../dvc-storage`. Чтобы восстановить данные модели, нужно найти у её запуска MLflow параметр `data_md5`, выбрать коммит с таким MD5 в `datasets/german_credit_data.csv.dvc`, извлечь этот указатель и выполнить `dvc pull` или `dvc checkout`, затем сверить MD5 восстановленного CSV. Для версии модели 6 подходит исходный указатель из коммита `9030a29` с MD5 `3086216ff1ff32f7626554e730cccc91`; для версии 7 — указатель из `6e15c46` с MD5 `75716716a440972dfc0fed80bb7791cc`.

## Журнал проблем третьей работы

| Проблема | Как нашли причину | Исправление |
|---|---|---|
| Metrics API отсутствовал | До установки metrics-server `kubectl top nodes` отвечал `Metrics API not available` | Установлен чарт metrics-server 3.14.0 с флагом `--kubelet-insecure-tls`; после этого `kubectl top` показал CPU и память |
| Pod metrics-server находился в `ImagePullBackOff` | События pod содержали ошибку подключения к IPv6-адресу `registry.k8s.io` | Образ получен через `docker pull` на хосте и проверен в kind через `kind load docker-image`; Helm завершил установку |
| После изменения memory request HPA временно показывал `<unknown>` | `kubectl describe hpa` сообщил `FailedGetResourceMetric`: для новых pod ещё не было метрик CPU | После сбора следующей выборки метрик HPA снова показал 1%/60%; обе реплики оставались Ready |
