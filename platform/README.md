# Запуск

Из корня репозитория:

```bash
bash platform/up.sh
```

Состав: Traefik, metrics-server, Prometheus/Grafana, MLflow, Airflow standalone,
RustFS и бакет `dvc`.

| Интерфейс | Адрес |
| --- | --- |
| MLflow | http://mlflow.localhost |
| Airflow | http://airflow.localhost |
| Grafana | http://grafana.localhost, `admin` / `admin` из `monitoring-values.yaml` |
| S3 API с хоста | http://s3.localhost |
| S3 API в кластере | http://rustfs.mlops:9000 |
| Консоль S3 | http://s3-console.localhost |

Секрет `s3-credentials` в namespace `mlops` содержит `AWS_ACCESS_KEY_ID` и
`AWS_SECRET_ACCESS_KEY`. При первом запуске значения по умолчанию — `dvcadmin` и
`dvc-secret-123`.
Их можно задать переменными `S3_ACCESS_KEY_ID` и `S3_SECRET_ACCESS_KEY` перед первым
запуском.
Данные RustFS лежат на PVC `rustfs-data` размером 2 GiB. Удаление kind-кластера
удалит и локальное хранилище. Размер PVC и ресурсы нового контейнера — начальные
настройки учебной установки, а не результат нагрузочного измерения.

## Основания настроек

Версии `traefik` 41.6.0, `metrics-server` 3.14.0 и `kube-prometheus-stack` 91.5.2
взяты из `helm list -A` существующего кластера 16.10.2026. Образ узла
`kindest/node:v1.37.0` с digest взят из `docker inspect mlpro3-control-plane`.
Это фиксация текущей установки, не утверждение о последних версиях компонентов.
Архивы чартов скачиваются по закреплённым URL через `curl`, проверяются по SHA256
и кешируются в `${XDG_CACHE_HOME:-$HOME/.cache}/credit-service/charts`.
SHA256 и URL взяты из соответствующих записей официальных индексов:
[Traefik](https://traefik.github.io/charts/index.yaml),
[metrics-server](https://kubernetes-sigs.github.io/metrics-server/index.yaml),
[Prometheus Community](https://prometheus-community.github.io/helm-charts/index.yaml).

Конфигурация RustFS сверена с исходниками версии 1.0.1:

- [docker-compose.yml](https://github.com/rustfs/rustfs/blob/1.0.1/docker-compose.yml):
  переменные `RUSTFS_*`, порты API 9000 и консоли 9001, проверки `/health` и
  `/rustfs/console/health`.
- [Dockerfile](https://github.com/rustfs/rustfs/blob/1.0.1/Dockerfile):
  пользователь и группа 10001, каталог данных `/data`. `fsGroup: 10001` нужен,
  чтобы процесс этого пользователя мог писать в смонтированный PVC.
- [Helm values](https://github.com/rustfs/rustfs/blob/1.0.1/helm/rustfs/values.yaml):
  readiness endpoint `/health/ready`.
- [Метаданные образа 1.0.1](https://hub.docker.com/v2/repositories/rustfs/rustfs/tags/1.0.1):
  multi-platform digest `sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`.

Для Job создания бакета используется тот же образ RustFS. Его Dockerfile
устанавливает `curl`; в запущенном контейнере проверен `curl --version`.
Запросы HeadBucket и CreateBucket подписываются ключами S3 с помощью
[`curl --aws-sigv4`](https://curl.se/docs/manpage.html#--aws-sigv4).
Отдельный образ клиента MinIO не нужен: при проверке старого локального
`minio/mc` по digest реестр ответил `pull access denied`.

## Прокси хоста при создании кластера

При запуске с нуля 16.10.2026 Traefik получил `ImagePullBackOff`, а Helm
завершился `context deadline exceeded`. В событиях pod была причина:
`proxyconnect tcp: dial tcp 127.0.0.1:10809: connect: connection refused`.
В `/etc/systemd/system.conf.d/proxy-default-environment.conf` узла kind
оказались `HTTP_PROXY` и `HTTPS_PROXY` с этим адресом, унаследованные с хоста.
Внутри узла `127.0.0.1` относится к самому контейнеру, где прокси не запущен.

При создании нового кластера `up.sh` исключает из окружения команды `kind`
переменные HTTP/HTTPS/ALL proxy с адресами `127.0.0.1`, `localhost` и `::1`.
Переменные прокси для остальных команд на хосте и прокси с другими адресами
сохраняются. Это рассчитано на прямой доступ узла к реестрам образов.

У уже созданного узла окружение само не меняется. Для восстановления текущей
установки в containerd добавлен drop-in
`/etc/systemd/system/containerd.service.d/20-disable-host-loopback-proxy.conf`
с `UnsetEnvironment` для переменных proxy, выполнены `systemctl daemon-reload`
и перезапуск containerd. После замены pod образ Traefik скачался успешно.

## Если API кластера недоступен

Сначала сравните `kubectl get --raw=/readyz` с проверкой внутри узла:

```bash
docker exec mlpro3-control-plane curl -k https://127.0.0.1:6443/readyz
docker inspect mlpro3-control-plane --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
ip route get <адрес-узла>
```

На этой машине 16.10.2026 маршрут `172.19.0.0/30` через `eth0` перекрывал
Docker-сеть `172.19.0.0/16`. Добавлен временный маршрут
`172.19.0.2/32` через `br-2ac6fd6166af`; после этого API и Ingress стали доступны
с хоста. Адреса и имя моста относятся к этой установке: перед изменением
маршрутов на другой машине нужно проверить её сеть. `up.sh` маршруты не меняет.
