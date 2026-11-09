import unittest

from fastapi.testclient import TestClient


class WebhookHealthTests(unittest.TestCase):
    def test_health_endpoint(self):
        from services.webhook_server import app

        client = TestClient(app)
        r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("ok"))


if __name__ == "__main__":
    unittest.main()
