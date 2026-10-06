"""
SafeRoute Feature Verification Test Suite
==========================================
Deeply verifies:
- Profile updates (name, email, password validation)
- F7 Admin Dashboard reports (top reporters, top searchers)
- Geocoding API & Route Hazard Corridor Matching
- PostgreSQL/SQLite Boolean Compatibility on hazards & notifications
"""

import time
import unittest
import os
from app import create_app


class FeatureVerificationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DEMO_ADMIN_PASSWORD"] = "test-only-admin-password"
        os.environ["DEMO_USER_PASSWORD"] = "test-only-user-password"
        cls.app = create_app("testing")
        cls.client = cls.app.test_client()
        cls.run_id = int(time.time())

        # Log in admin
        resp = cls.client.post(
            "/api/auth/login",
            json={"email": "admin@saferoute.com", "password": os.environ["DEMO_ADMIN_PASSWORD"]},
        )
        cls.admin_token = resp.get_json()["data"]["token"]

        # Log in user
        resp = cls.client.post(
            "/api/auth/login",
            json={"email": "user@saferoute.com", "password": os.environ["DEMO_USER_PASSWORD"]},
        )
        cls.user_token = resp.get_json()["data"]["token"]

    def test_profile_update_validation(self):
        # 1. Blank name rejection
        resp = self.client.patch(
            "/api/profile",
            json={"name": "   "},
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "MISSING_NAME")

        # 2. Invalid email rejection
        resp = self.client.patch(
            "/api/profile",
            json={"email": "invalid-email-string"},
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "INVALID_EMAIL")

        # 3. Short password rejection
        resp = self.client.patch(
            "/api/profile",
            json={"new_password": "short"},
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "PASSWORD_TOO_SHORT")

        # 4. Successful update of name
        resp = self.client.patch(
            "/api/profile",
            json={"name": "Asha Rao SafeRoute"},
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["user"]["name"], "Asha Rao SafeRoute")

    def test_geocoding_and_route_search(self):
        # 1. Geocode known landmark
        resp = self.client.get(
            "/api/routes/geocode?q=Benz+Circle",
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertAlmostEqual(data["data"]["latitude"], 16.5020, places=2)
        self.assertAlmostEqual(data["data"]["longitude"], 80.6510, places=2)

        # 2. Missing query validation
        resp = self.client.get(
            "/api/routes/geocode?q=",
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 400)

        # 3. Route search Benz Circle -> Auto Nagar with custom corridor radius
        resp = self.client.post(
            "/api/routes/search",
            json={
                "origin": {"latitude": 16.5020, "longitude": 80.6510},
                "destination": {"latitude": 16.4950, "longitude": 80.6720},
                "radius_km": 2.0,
            },
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        rdata = resp.get_json()
        self.assertTrue(rdata["success"])
        self.assertIn("distance_km", rdata["data"])
        self.assertIn("duration_minutes", rdata["data"])
        self.assertIn("hazards", rdata["data"])
        # Benz Circle to Auto Nagar has multiple active hazards in Vijayawada
        self.assertGreaterEqual(len(rdata["data"]["hazards"]), 1)
        for h in rdata["data"]["hazards"]:
            self.assertIn("distance_from_route", h)
            self.assertIn("severity", h)

    def test_f7_admin_dashboard(self):
        resp = self.client.get(
            "/api/admin/reports/dashboard",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

        # Check top reporters list
        self.assertIn("top_reporters", data["data"])
        self.assertIsInstance(data["data"]["top_reporters"], list)
        if data["data"]["top_reporters"]:
            top_rep = data["data"]["top_reporters"][0]
            self.assertIn("report_count", top_rep)
            self.assertIn("verified_count", top_rep)

        # Check top searchers list
        self.assertIn("top_searchers", data["data"])
        self.assertIsInstance(data["data"]["top_searchers"], list)
        if data["data"]["top_searchers"]:
            top_search = data["data"]["top_searchers"][0]
            self.assertIn("search_count", top_search)
            self.assertIn("total_distance_km", top_search)

    def test_boolean_type_handling_notifications(self):
        # 1. Unread notifications query
        resp = self.client.get(
            "/api/notifications?unread_only=true",
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("unread_count", data["data"])

        # 2. Mark all read
        resp = self.client.post(
            "/api/notifications/mark-all-read",
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 200)

        # Verify unread count is now 0
        resp = self.client.get(
            "/api/notifications?unread_only=true",
            headers={"Authorization": f"Bearer {self.user_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["data"]["unread_count"], 0)

    def test_registration_auto_login_and_subsequent_login(self):
        test_email = f"newdriver_{self.run_id}@saferoute.com"
        test_password = "SecurePassword123!"

        # 1. Register new user
        reg_resp = self.client.post(
            "/api/auth/register",
            json={
                "name": "New Registered Driver",
                "email": test_email,
                "password": test_password,
            },
        )
        self.assertEqual(reg_resp.status_code, 201)
        reg_data = reg_resp.get_json()
        self.assertTrue(reg_data["success"])
        self.assertEqual(reg_data["data"]["user"]["email"], test_email)
        self.assertIn("token", reg_data["data"])
        reg_token = reg_data["data"]["token"]

        # 2. Token from registration immediately works on protected endpoints
        profile_resp = self.client.get(
            "/api/profile",
            headers={"Authorization": f"Bearer {reg_token}"},
        )
        self.assertEqual(profile_resp.status_code, 200)
        self.assertEqual(profile_resp.get_json()["data"]["user"]["email"], test_email)

        # 3. Log in with the registered credentials
        login_resp = self.client.post(
            "/api/auth/login",
            json={"email": test_email, "password": test_password},
        )
        self.assertEqual(login_resp.status_code, 200)
        login_data = login_resp.get_json()
        self.assertTrue(login_data["success"])
        self.assertIn("token", login_data["data"])
        self.assertEqual(login_data["data"]["user"]["email"], test_email)


if __name__ == "__main__":
    unittest.main()

