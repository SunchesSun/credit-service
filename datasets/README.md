# German Credit Risk dataset

Ноутбук обучения ожидает файл `datasets/german_credit_data.csv` из набора
[German Credit Risk - With Target](https://www.kaggle.com/datasets/kabure/german-credit-data-with-risk),
который указан в паспорте модели.

CSV отслеживается DVC, а в Git хранится `german_credit_data.csv.dvc`. После клонирования
восстановите файл командой `uv run dvc pull`. Сейчас DVC remote `local` указывает на
`../dvc-storage` рядом с репозиторием, поэтому для клона на другом компьютере нужно
сначала перенести это хранилище или настроить другой remote.
