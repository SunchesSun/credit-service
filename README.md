# Credit service

MLOps-проект кредитного скоринга. FastAPI принимает признаки заявки
и возвращает вероятность класса bad, решение по порогу 0.5, версию модели
и request_id. Каждый запрос предсказания записывается в PostgreSQL.

Модель — scikit-learn Pipeline: обработка пропусков, OneHotEncoder,
StandardScaler и LogisticRegression. Данные German Credit Risk хранятся
в DVC/S3, модели и результаты обучения — в MLflow. Airflow проверяет данные,
обучает кандидата и перезапускает сервис при продвижении модели.
Prometheus собирает метрики, Grafana показывает нагрузку и ответы модели.
Статус выполнения задания и доказательства: [REPORT.md](REPORT.md).

## Quickstart

Linux/WSL: нужны Docker с Buildx, uv, kind, kubectl, Helm 3 и curl.
Порт 80 должен быть свободен; Python 3.11 устанавливается через uv.

~~~bash
git clone https://github.com/SunchesSun/credit-service.git
cd credit-service
bash scripts/quickstart.sh
~~~

Скрипт устанавливает зависимости, проверяет локальные имена, поднимает
платформу, получает ключи S3 из Kubernetes Secret и восстанавливает данные
через DVC. Для пустого бакета скачивает исходный набор из Kaggle и проверяет
MD5 по указателю перед публикацией в S3. Затем проверяет CSV, обучает
отсутствующий champion, собирает образ и разворачивает API, мониторинг и DAG.
В конце выводит ответы health/predict, метрику версии, список pod и время запуска.

Если локальные имена не настроены, скрипт попросит sudo для добавления
записи в /etc/hosts. Изменённый вручную CSV не перезаписывается;
существующие champion и Secret PostgreSQL сохраняются. Гейт требует
абсолютного прироста PR-AUC больше 0.01 на сопоставимом holdout.
Первый запуск требует доступа к реестрам образов и Kaggle.

Повторный запуск — та же команда. Только пересобрать и обновить API
на уже готовой платформе с существующим champion:

~~~bash
bash scripts/deploy-local.sh
~~~

Состав платформы и диагностика: [platform/README.md](platform/README.md).

## CI/CD: настройка

Для полного CI/CD нужны права на GitHub-репозиторий или свой форк.

1. В Settings → Secrets and variables → Actions создай DB_PASSWORD с паролем
   текущей БД. Для новой установки скрипт использует postgres. Изменение
   GitHub Secret само по себе не меняет пароль существующей роли PostgreSQL.
2. В Settings → Actions → Runners → New self-hosted runner получи registration
   token и выполни команду ниже. Скрипт запросит токен; для форка можно передать
   его URL первым аргументом. Существующий gh-runner запускается повторно
   при необходимости; сохранённая регистрация используется без нового токена.

~~~bash
bash scripts/register-runner.sh
~~~

3. После публикации кода в main выбери Actions → ci → Run workflow → main.
   Выполнятся tests, build и deploy на runner с меткой kind. CI применит
   Secret, БД, API, мониторинг, DAG и переменную credit_image, затем проверит
   ответ через Ingress, запись PostgreSQL и метрику версии модели.

Обычный push в main запускает tests и build; deploy запускается по кнопке.

## Интерфейсы и переобучение

| Компонент | Адрес |
| --- | --- |
| API, Swagger | http://credit.localhost/docs |
| MLflow | http://mlflow.localhost |
| Airflow | http://airflow.localhost |
| Grafana, дашборд | http://grafana.localhost/d/credit-service/credit-service |
| RustFS, консоль S3 | http://s3-console.localhost |
| S3 API с хоста / из кластера | http://s3.localhost / http://rustfs.mlops:9000 |

Grafana: admin / admin. Airflow в этой конфигурации запускается
с simple_auth_manager_all_admins=True. Ключи RustFS по умолчанию —
dvcadmin / dvc-secret-123.

В Airflow включи DAG credit_retrain и нажми Trigger, либо выполни:

~~~bash
kubectl exec -n mlops deploy/airflow -- airflow dags unpause credit_retrain
kubectl exec -n mlops deploy/airflow -- airflow dags trigger credit_retrain
~~~

Цепочка: validate → train → promoted → rollout. Проверка и обучение выполняются
в отдельных pod и скачивают CSV из S3. При promoted=false rollout пропускается.
Расписание — ежедневно в 03:00 по Москве, без start_date; при создании DAG на паузе.
Параметры ручного запуска c и bad_class_weight по умолчанию равны 1.

Гейт сравнивает data_md5, seed, test_size, stratified и отпечаток строк
валидации validation_sha256. Несовпадение или отсутствие этих полей
останавливает обучение до регистрации модели и изменения aliases.
Старые run без контекста разбиения автоматически сопоставимыми не считаются.
При новом реестре Quickstart создаёт первого champion с нужными полями;
для существующего старого реестра потребуется baseline с полным контекстом.

После публикации нового образа сценарии проверяются последовательно.
Сначала запусти генератор трафика из команды ниже, затем кандидата:

~~~bash
kubectl exec -n mlops deploy/airflow -- airflow dags trigger \
  -c '{"c":0.01,"bad_class_weight":2}' credit_retrain
~~~

На сохранённых данных и seed 42 эта конфигурация имела PR-AUC 0.634330
против 0.624200 у baseline C=0.007 / вес bad=1: прирост 0.010130 проходит
политику 0.01. Актуальное решение зависит от текущего champion.
После завершения первого DAG проверь отказ на кандидате C=1 / вес bad=1:

~~~bash
kubectl exec -n mlops deploy/airflow -- airflow dags trigger \
  -c '{"c":1,"bad_class_weight":1}' credit_retrain
~~~

Фиксированный допуск — инженерная политика, не тест статистической значимости.
Повторное обучение той же конфигурации не гарантирует продвижение.

Для заполнения дашборда:

~~~bash
uv run python scripts/traffic.py --duration 300 --rps 5
~~~

## Проверки и структура

~~~bash
uv run --frozen ruff check .
uv run --frozen pytest
~~~

| Каталог / файл | Назначение |
| --- | --- |
| src/credit_service | API, обучение, Pandera, метрики, запись в БД |
| datasets, .dvc | Указатель данных и настройки хранилища |
| artifact | Локальная модель для запуска без реестра и тестов |
| platform | Платформа Kubernetes и скрипт её установки |
| k8s | PostgreSQL, API, HPA, Ingress и мониторинг |
| dags/credit_retrain.py | Конвейер Airflow |
| scripts/quickstart.sh | Полный локальный запуск |
| scripts/prepare.py | DVC, проверка CSV и первый champion |
| scripts/deploy-local.sh | Сборка, локальный деплой и проверка ответа |
| scripts/register-runner.sh | Первоначальная регистрация GitHub runner |
| scripts/traffic.py | Трафик через Ingress |
| .github/workflows/ci.yml | Тесты, сборка, деплой и smoke |
| docs/hw4 | Скриншоты работы 4 |

RustFS, MLflow и Airflow используют PVC внутри kind. Удаление кластера удаляет
его локальные данные; у PostgreSQL в текущем манифесте отдельного PVC нет.
Полный проход этого Quickstart в свежем клоне с новым кластером ещё не измерен.
