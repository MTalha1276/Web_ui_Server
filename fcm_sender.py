#!/usr/bin/env python3
"""
FCM Sender Module — sends Firebase Cloud Messaging push notifications
to Android devices using the HTTP v1 API.

Uses the service account JSON for authentication (OAuth2 access token).

Usage:
    from fcm_sender import FcmSender

    fcm = FcmSender("path/to/service-account.json")
    fcm.send_command("device_fcm_token", "get_location")
    fcm.send_command("device_fcm_token", "list_files", {"path": "/storage/emulated/0/"})
"""

import json
import time
import urllib.request
import urllib.parse
import os
import logging

logger = logging.getLogger("FCM_Sender")


class FcmSender:
    """
    Sends FCM push notifications via Firebase HTTP v1 API.
    Authenticates using a service account JSON key (OAuth2 token exchange).
    """

    # Google OAuth2 token endpoint
    OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
    # FCM HTTP v1 endpoint template
    FCM_URL_TEMPLATE = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    # OAuth scope for FCM
    FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

    def __init__(self, service_account_path):
        """
        Initialize with the path to the Firebase service account JSON.

        Args:
            service_account_path: Path to the downloaded service account JSON file.
        """
        self.service_account_path = service_account_path
        self.project_id = None
        self.client_email = None
        self.private_key = None
        self.token_uri = None
        self._access_token = None
        self._token_expires_at = 0

        self._load_service_account()

    def _load_service_account(self):
        """Load the service account JSON and extract needed fields."""
        try:
            with open(self.service_account_path, 'r') as f:
                data = json.load(f)
            self.project_id = data.get("project_id")
            self.client_email = data.get("client_email")
            self.private_key = data.get("private_key")
            self.token_uri = data.get("token_uri", self.OAUTH_TOKEN_URL)

            if not self.project_id or not self.private_key or not self.client_email:
                raise ValueError("Service account JSON missing required fields")

            logger.info(f"FCM initialized — project: {self.project_id}, client: {self.client_email}")
        except Exception as e:
            logger.error(f"Failed to load service account: {e}")
            raise

    def _get_access_token(self):
        """
        Get an OAuth2 access token using the service account.
        Caches the token and refreshes it before expiry.
        """
        # Check if cached token is still valid (with 60s buffer)
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        # Create JWT assertion
        import base64
        import hashlib

        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": self.client_email,
            "scope": self.FCM_SCOPE,
            "aud": self.token_uri,
            "exp": now + 3600,
            "iat": now,
        }

        def b64url(data):
            return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

        header_b64 = b64url(json.dumps(header, separators=(',', ':')).encode())
        payload_b64 = b64url(json.dumps(payload, separators=(',', ':')).encode())

        # Sign the assertion with the private key
        signing_input = f"{header_b64}.{payload_b64}".encode()
        signature = self._sign_jwt(signing_input)
        signature_b64 = b64url(signature)

        jwt_assertion = f"{header_b64}.{payload_b64}.{signature_b64}"

        # Exchange JWT for access token
        data = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt_assertion,
        }).encode()

        req = urllib.request.Request(self.token_uri, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                token_data = json.loads(resp.read().decode())
                self._access_token = token_data["access_token"]
                self._token_expires_at = now + token_data.get("expires_in", 3600)
                logger.info("FCM access token obtained successfully")
                return self._access_token
        except Exception as e:
            logger.error(f"Failed to get FCM access token: {e}")
            raise

    def _sign_jwt(self, signing_input):
        """Sign the JWT input using the private key (RS256)."""
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.backends import default_backend

            key = serialization.load_pem_private_key(
                self.private_key.encode(),
                password=None,
                backend=default_backend()
            )
            signature = key.sign(
                signing_input,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return signature
        except ImportError:
            # Fallback: use openssl CLI if cryptography lib not available
            return self._sign_with_openssl(signing_input)

    def _sign_with_openssl(self, signing_input):
        """Fallback: sign using openssl CLI."""
        import tempfile
        import subprocess

        # Write private key to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as key_file:
            key_file.write(self.private_key)
            key_path = key_file.name

        # Write signing input to temp file
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.bin', delete=False) as input_file:
            input_file.write(signing_input)
            input_path = input_file.name

        try:
            # Sign with openssl
            result = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", key_path, "-binary", input_path],
                capture_output=True,
                timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError(f"openssl signing failed: {result.stderr.decode()}")
            return result.stdout
        finally:
            os.unlink(key_path)
            os.unlink(input_path)

    def send_command(self, fcm_token, command, extra_args=None):
        """
        Send a command via FCM data message to a specific device.

        Args:
            fcm_token: The device's FCM registration token.
            command: The command string (e.g. "get_location", "capture_front").
            extra_args: Optional dict of extra key-value pairs to include.

        Returns:
            dict: Response from FCM API or error info.
        """
        try:
            access_token = self._get_access_token()
            url = self.FCM_URL_TEMPLATE.format(project_id=self.project_id)

            # Build the data message payload
            data = {"command": command}
            if extra_args:
                data.update(extra_args)

            # FCM HTTP v1 message format
            message = {
                "message": {
                    "token": fcm_token,
                    "data": data,
                    "android": {
                        "priority": "high",
                        "ttl": "86400s"  # 24 hours
                    }
                }
            }

            body = json.dumps(message).encode('utf-8')

            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Authorization", f"Bearer {access_token}")
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=10) as resp:
                response_data = json.loads(resp.read().decode())
                logger.info(f"FCM command '{command}' sent successfully: {response_data.get('name', '')}")
                return {"status": "success", "response": response_data}

        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            logger.error(f"FCM send failed (HTTP {e.code}): {error_body}")
            return {"status": "error", "code": e.code, "message": error_body}

        except Exception as e:
            logger.error(f"FCM send error: {e}")
            return {"status": "error", "message": str(e)}

    def send_command_multi(self, fcm_tokens, command, extra_args=None):
        """
        Send a command to multiple devices.

        Args:
            fcm_tokens: List of FCM registration tokens.
            command: The command string.
            extra_args: Optional dict of extra key-value pairs.

        Returns:
            list: List of response dicts, one per token.
        """
        results = []
        for token in fcm_tokens:
            result = self.send_command(token, command, extra_args)
            results.append({"token": token[:20] + "...", "result": result})
        return results
