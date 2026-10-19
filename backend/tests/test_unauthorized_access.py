
from fastapi.testclient import TestClient

def test_unauthorized_access_to_protected_routes(client: TestClient):
    """
    Ensures that routes requiring authentication return 401/422 when no token is provided.
    """
    # 1. Interaction list (Requires Token)
    response = client.get("/api/v1/interactions")
    assert response.status_code == 401

    # 2. Manager review queue (Requires Manager Auth) — replaces the retired
    #    /emotion-events/flagged endpoint.
    response = client.get("/api/v1/reviews/queue")
    assert response.status_code in [401, 422]
