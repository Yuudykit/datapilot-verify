from fastapi.testclient import TestClient

from webapp.api import app

client = TestClient(app)


def test_health_and_analysis_snapshot_flow() -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    response = client.post(
        "/api/analyze", json={"question": "7 月净销售额为什么下降？", "thread_id": "api-test"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    snapshot_id = payload["snapshot_id"]
    evidence = client.post("/api/evidence", json={"snapshot_id": snapshot_id}).json()
    replay = client.post("/api/replay", json={"snapshot_id": snapshot_id}).json()
    assert evidence["ok"]
    assert replay["ok"] and replay["data"]["identical"]


def test_upload_dataset() -> None:
    content = b"id,value\n1,10\n2,20\n"
    response = client.post("/api/datasets", files={"file": ("demo.csv", content, "text/csv")})
    assert response.status_code == 200
    assert response.json()["data"]["profile"]["row_count"] == 2


def test_unified_agent_endpoint_uses_mock_graph_by_default() -> None:
    response = client.post("/api/agent", json={"question": "退款率口径是什么"})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
