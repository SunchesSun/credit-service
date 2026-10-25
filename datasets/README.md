# German Credit Risk dataset

Ноутбук обучения ожидает файл `datasets/german_credit_data.csv` из набора
[German Credit Risk - With Target](https://www.kaggle.com/datasets/kabure/german-credit-data-with-risk),
который указан в паспорте модели.

CSV отслеживается DVC, а в Git хранится `german_credit_data.csv.dvc`.
Два remote используют один бакет `s3://dvc` в RustFS:

| Remote | Endpoint | Использование |
| --- | --- | --- |
| `laptop` (по умолчанию) | `http://s3.localhost` | Команды с хоста через Ingress |
| `cluster` | `http://rustfs.mlops:9000` | Задачи в Kubernetes |

Сначала запустите платформу: `bash platform/up.sh`. Python должен разрешать
`s3.localhost` в `127.0.0.1`. Проверка:

```bash
uv run python -c "import socket; print(socket.gethostbyname('s3.localhost'))"
```

Если имя не разрешается, добавьте `127.0.0.1 s3.localhost` в hosts-файл системы.
На этой машине WSL также понадобились имена интерфейсов платформы:

```bash
echo '127.0.0.1 s3.localhost mlflow.localhost airflow.localhost grafana.localhost s3-console.localhost credit.localhost' | sudo tee -a /etc/hosts
```

Один раз задайте ключи remote локально. Ниже учебные значения по умолчанию из
задания и `platform/up.sh`; если задавали свои ключи S3, используйте их:

```bash
uv run dvc remote modify --local laptop access_key_id dvcadmin
uv run dvc remote modify --local laptop secret_access_key dvc-secret-123
```

Они сохраняются в игнорируемом `.dvc/config.local`, который исключён и из
Docker-контекста. В Git ключи не попадают.

Восстановление и публикация данных с хоста:

```bash
uv run dvc pull
# После изменения CSV и обновления указателя:
uv run dvc add datasets/german_credit_data.csv
uv run dvc push
```

`dvc push` должен завершиться до `git push`, чтобы опубликованный указатель
ссылался на уже доступные данные.

В поде используется `uv run --no-sync dvc pull -r cluster`. Ключи передаются
через `AWS_ACCESS_KEY_ID` и `AWS_SECRET_ACCESS_KEY` из секрета `s3-credentials`
namespace `mlops`. Регион `us-east-1` совпадает с подписанными запросами Job
`platform/s3-init.yaml`. Образ содержит конфигурацию и указатель `.dvc`, а CSV
скачивается перед проверкой и обучением. Режим `core.no_scm=true` в Dockerfile
позволяет выполнять DVC без каталога `.git`.

Remote `local` сохранён для прежнего хранилища `../dvc-storage`:
`uv run dvc pull -r local`. Он больше не используется по умолчанию.

## Проверка перед обучением

```bash
uv run dvc pull
MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m credit_service.data
```

Другой CSV можно проверить через `--data путь.csv` либо переменную `DATA_PATH`.
Модуль переименовывает столбцы в имена контракта модели, проверяет схему строк,
затем объём и долю класса в выгрузке. Он не удаляет строки и не заполняет пропуски.
Границы и их обоснование приведены в разделе Pandera в `REPORT.md`.

Проверка создаёт запуск `validate` в эксперименте `german-credit` (можно изменить
через `--experiment` или `MLFLOW_EXPERIMENT`). В нём сохраняются MD5 исходного
CSV, число строк и параметры проверок. При успехе `valid=true`, код выхода 0.
При нарушении схемы — `valid=false`, статус FAILED, код выхода 1 и артефакт
`failure_cases.csv`. Ошибка чтения файла также сохраняется в этом артефакте.
В MLflow откройте запуск, затем Artifacts → `failure_cases.csv`.

Тесты схем используют синтетические строки и не требуют CSV, S3 или MLflow:

```bash
uv run pytest tests/test_data.py
```
