import json
from pathlib import Path

from locust import HttpUser, between, task


class CreditUser(HttpUser):
    wait_time = between(0.1, 0.5)
    payload = json.loads(Path(__file__).with_name("good.json").read_text())

    @task
    def predict(self):
        self.client.post("/v1/predict", json=self.payload)
