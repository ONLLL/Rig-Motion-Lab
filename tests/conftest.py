import pytest
from fastapi.testclient import TestClient
from lab.main import app
from lab.demo import new_project

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setenv('RIG_LAB_DATA_DIR',str(tmp_path/'projects'))
    monkeypatch.setenv('RIG_LAB_POSE_MODEL',str(tmp_path/'missing.task'))

@pytest.fixture
def project(): return new_project(demo=True)

@pytest.fixture
def client():
    with TestClient(app,headers={'X-Rig-Request':'1'}) as c: yield c
