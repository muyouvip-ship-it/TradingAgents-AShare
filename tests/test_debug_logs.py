from fastapi.testclient import TestClient


def _get_client():
    from api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _auth(client: TestClient) -> str:
    response = client.post("/v1/auth/request-code", json={"email": "debug-log@test.com"})
    code = response.json()["dev_code"]
    verified = client.post("/v1/auth/verify-code", json={"email": "debug-log@test.com", "code": code})
    return verified.json()["access_token"]


def test_log_sources_requires_auth():
    client = _get_client()
    response = client.get("/v1/debug/log-sources")

    assert response.status_code in (401, 403)


def test_log_sources_and_tail_response():
    client = _get_client()
    token = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    sources = client.get("/v1/debug/log-sources", headers=headers)
    assert sources.status_code == 200
    body = sources.json()
    assert any(item["id"] == "backend_runtime" for item in body["sources"])

    logs = client.get("/v1/debug/logs?source=backend_runtime&lines=10", headers=headers)
    assert logs.status_code == 200
    payload = logs.json()
    assert payload["source"]["id"] == "backend_runtime"
    assert isinstance(payload["lines"], list)
    assert payload["max_lines"] == 10
