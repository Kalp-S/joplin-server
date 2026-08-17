#!/usr/bin/env python3
"""
Joplin Server & Sync Service Integration Test Suite
===================================================
Validates:
1. Docker container status & PostgreSQL database health
2. Joplin API origin/host validation & health ping
3. Authentication & session security contracts
4. Sync protocol operations (Delta synchronization, item upload, download, and deletion)
5. Backup pipeline & Google Drive rclone integration
"""

import json
import os
import subprocess
import unittest
import urllib.error
import urllib.request
import uuid

BASE_URL = os.environ.get("JOPLIN_BASE_URL", "http://127.0.0.1:22300")
HOST_HEADER = os.environ.get("JOPLIN_HOST_HEADER", "joplin.kalp.dev")
ORIGIN_HEADER = os.environ.get("JOPLIN_ORIGIN_HEADER", "https://joplin.kalp.dev")
DB_CONTAINER = os.environ.get("DB_CONTAINER", "joplin-joplin-db-1")
SERVER_CONTAINER = os.environ.get("SERVER_CONTAINER", "joplin-joplin-1")


def make_request(path, method="GET", headers=None, data=None, with_host=True):
    url = f"{BASE_URL}{path}"
    req_headers = {
        "User-Agent": "JoplinSyncIntegrationTest/1.0",
    }
    if with_host:
        req_headers["Host"] = HOST_HEADER
        req_headers["Origin"] = ORIGIN_HEADER
    if headers:
        req_headers.update(headers)

    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data

    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read()
            return response.status, dict(response.headers), res_body
    except urllib.error.HTTPError as e:
        res_body = e.read()
        return e.code, dict(e.headers), res_body
    except urllib.error.URLError as e:
        return 0, {}, str(e).encode("utf-8")


def make_multipart_upload(path, filename, content_bytes, headers=None):
    """Performs multipart/form-data upload expected by Joplin item sync API."""
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    url = f"{BASE_URL}{path}"

    body_parts = [
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"),
        b"Content-Type: text/markdown\r\n\r\n",
        content_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    body = b"".join(body_parts)

    req_headers = {
        "Host": HOST_HEADER,
        "Origin": ORIGIN_HEADER,
        "User-Agent": "JoplinSyncIntegrationTest/1.0",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=body, headers=req_headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def get_active_session_token():
    """Fetches an active session token from the local Postgres database for testing."""
    cmd = [
        "docker", "exec", DB_CONTAINER,
        "psql", "-U", "joplin", "-d", "joplin", "-t", "-A",
        "-c", "SELECT id FROM sessions ORDER BY updated_time DESC LIMIT 1;"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("No active session found in Joplin database to test sync protocol.")
    return token


class TestDockerAndDatabaseHealth(unittest.TestCase):
    """Verifies Docker containers and PostgreSQL connectivity."""

    def test_docker_containers_running(self):
        """Ensure both server and database containers are Up."""
        res = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, check=True
        )
        lines = res.stdout.strip().split("\n")
        containers = {line.split("\t")[0]: line.split("\t")[1] for line in lines if "\t" in line}

        self.assertIn(SERVER_CONTAINER, containers, f"{SERVER_CONTAINER} is not running")
        self.assertIn(DB_CONTAINER, containers, f"{DB_CONTAINER} is not running")
        self.assertTrue(containers[SERVER_CONTAINER].startswith("Up"), f"{SERVER_CONTAINER} is down")
        self.assertTrue(containers[DB_CONTAINER].startswith("Up"), f"{DB_CONTAINER} is down")

    def test_postgres_table_integrity(self):
        """Ensure critical Joplin database tables exist and are queryable."""
        cmd = [
            "docker", "exec", DB_CONTAINER,
            "psql", "-U", "joplin", "-d", "joplin", "-t", "-A",
            "-c", "SELECT count(*) FROM items; SELECT count(*) FROM users;"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        counts = [line.strip() for line in res.stdout.strip().split("\n") if line.strip().isdigit()]
        self.assertEqual(len(counts), 2, "Failed to query items and users count from database")
        item_count = int(counts[0])
        user_count = int(counts[1])
        self.assertGreater(user_count, 0, "No users registered in Joplin database")
        self.assertGreaterEqual(item_count, 0, "Item count query returned invalid count")


class TestJoplinApiSecurityAndPing(unittest.TestCase):
    """Tests Joplin HTTP API health and origin validation security."""

    def test_api_ping_with_valid_host(self):
        """API ping should return HTTP 200 and status: ok with valid Host header."""
        status, headers, body = make_request("/api/ping", method="GET", with_host=True)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("Joplin Server is running", data.get("message", ""))

    def test_api_ping_origin_validation(self):
        """API ping without Host/Origin headers should be rejected with 404 Invalid origin."""
        status, headers, body = make_request("/api/ping", method="GET", with_host=False)
        self.assertEqual(status, 404)
        self.assertIn(b"Invalid origin", body)


class TestAuthenticationSecurity(unittest.TestCase):
    """Tests session creation and authentication guardrails."""

    def test_invalid_login_rejection(self):
        """POST /api/sessions with invalid credentials must return 403 Forbidden."""
        payload = {
            "email": "nonexistent_user_test@example.com",
            "password": "wrong_password_12345"
        }
        status, headers, body = make_request("/api/sessions", method="POST", data=payload)
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("error"), "Invalid email or password")

    def test_unauthenticated_delta_sync_rejection(self):
        """GET /api/items/root:/:delta without auth token must return 403 Forbidden."""
        status, headers, body = make_request("/api/items/root:/:delta", method="GET")
        self.assertEqual(status, 403)


class TestJoplinSyncProtocol(unittest.TestCase):
    """Tests delta synchronization and CRUD operations over the Joplin sync API."""

    @classmethod
    def setUpClass(cls):
        cls.session_token = get_active_session_token()
        cls.auth_headers = {"X-API-AUTH": cls.session_token}

    def test_delta_sync_pagination(self):
        """GET /api/items/root:/:delta should return item list and delta cursor."""
        status, headers, body = make_request(
            "/api/items/root:/:delta?limit=5",
            method="GET",
            headers=self.auth_headers
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("items", data)
        self.assertIn("cursor", data)
        self.assertIsInstance(data["items"], list)

    def test_item_sync_lifecycle(self):
        """Test full item lifecycle: create sync item, fetch content, and delete it."""
        test_filename = f"test_integration_{uuid.uuid4().hex[:8]}.md"
        test_content = (
            f"# Integration Test Note\n"
            f"Created by automated test suite: {uuid.uuid4().hex}\n"
            f"Sync protocol validation item.\n"
        )

        # 1. PUT item content via multipart form upload
        status, _, body = make_multipart_upload(
            f"/api/items/root:/{test_filename}:/content",
            filename=test_filename,
            content_bytes=test_content.encode("utf-8"),
            headers=self.auth_headers
        )
        self.assertEqual(status, 200, f"Failed to upload item: {body.decode('utf-8')}")
        resp_data = json.loads(body.decode("utf-8"))
        self.assertEqual(resp_data.get("name"), test_filename)

        try:
            # 2. GET item content and verify exact match
            status, _, get_body = make_request(
                f"/api/items/root:/{test_filename}:/content",
                method="GET",
                headers=self.auth_headers
            )
            self.assertEqual(status, 200)
            self.assertEqual(get_body.decode("utf-8"), test_content)

        finally:
            # 3. DELETE item by path to ensure clean database state
            del_status, _, _ = make_request(
                f"/api/items/root:/{test_filename}:",
                method="DELETE",
                headers=self.auth_headers
            )
            self.assertEqual(del_status, 200, "Failed to delete test item")


class TestBackupAndStoragePipeline(unittest.TestCase):
    """Validates the backup script and Google Drive rclone integration."""

    def test_backup_script_exists_and_executable(self):
        """Ensure backup.sh script is present and executable."""
        script_path = "/home/kalp/git/joplin/scripts/backup.sh"
        self.assertTrue(os.path.isfile(script_path), "backup.sh not found")
        self.assertTrue(os.access(script_path, os.X_OK), "backup.sh is not executable")

    def test_local_backup_archive_integrity(self):
        """Ensure local backup archives exist and are valid tar.gz files containing database dumps."""
        backup_dir = "/home/kalp/git/joplin/backups"
        archives = [
            os.path.join(backup_dir, f)
            for f in os.listdir(backup_dir)
            if f.endswith(".tar.gz")
        ]
        self.assertGreater(len(archives), 0, "No local backup archives found")

        # Test latest archive with tar -tzf
        latest_archive = max(archives, key=os.path.getmtime)
        res = subprocess.run(["tar", "-tzf", latest_archive], capture_output=True, text=True, check=True)
        files = res.stdout.strip().split("\n")
        self.assertTrue(any("joplin.sql" in f for f in files), "joplin.sql missing from backup archive")
        self.assertTrue(any("docker-compose.yml" in f for f in files), "docker-compose.yml missing from backup archive")
        self.assertTrue(any(".env" in f for f in files), ".env missing from backup archive")

    def test_rclone_gdrive_connectivity(self):
        """Ensure rclone can connect to Google Drive and list joplin backups folder."""
        res = subprocess.run(
            ["rclone", "ls", "gdrive:joplin backups"],
            capture_output=True, text=True, check=True
        )
        self.assertIn(".tar.gz", res.stdout, "No archives found in remote Google Drive joplin backups")


if __name__ == "__main__":
    import warnings
    warnings.simplefilter("ignore", ResourceWarning)
    unittest.main(verbosity=2)
