import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from credit_service.service.app import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def good_row():
    return json.loads(Path("good.json").read_text())
