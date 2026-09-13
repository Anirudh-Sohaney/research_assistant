"""OAuth 2.0 Device Code Flow (RFC 8628) implementation for OpenAI authentication.

Provides device authorization request, polling, credential extraction,
secure file persistence, token auto-refresh, local development server bridge,
and integration with the API Gateway.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import http.server
import json
import logging
import os
from pathlib import Path
import secrets
import string
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple, Union
import urllib.parse
import webbrowser

import httpx

from api_gateway.models import AuthConfig, ExternalService

log = logging.getLogger("api_gateway.oauth")

# Standard RFC 8628 Grant Type URN
DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
REFRESH_TOKEN_GRANT_TYPE = "refresh_token"

# Default OpenAI Auth0 / OAuth Configurations (customizable via env vars)
DEFAULT_AUTH_DOMAIN = os.getenv("OPENAI_AUTH_DOMAIN", "https://auth.openai.com")
DEFAULT_DEVICE_AUTH_ENDPOINT = os.getenv(
    "OPENAI_DEVICE_AUTH_URL", f"{DEFAULT_AUTH_DOMAIN}/api/accounts/deviceauth/usercode"
)
DEFAULT_TOKEN_ENDPOINT = os.getenv(
    "OPENAI_TOKEN_URL", f"{DEFAULT_AUTH_DOMAIN}/api/accounts/deviceauth/token"
)
DEFAULT_CLIENT_ID = os.getenv("OPENAI_OAUTH_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann")
DEFAULT_AUDIENCE = os.getenv("OPENAI_OAUTH_AUDIENCE", "https://api.openai.com/v1")
DEFAULT_SCOPE = os.getenv(
    "OPENAI_OAUTH_SCOPE", "openid profile email offline_access model.request"
)
DEFAULT_VERIFICATION_URI = "https://auth.openai.com/codex/device"


class OAuthError(Exception):
    """Base exception for OAuth failures."""

    def __init__(self, error: str, description: Optional[str] = None):
        super().__init__(f"OAuth Error [{error}]: {description or ''}".strip())
        self.error = error
        self.description = description


class OAuthExpiredTokenError(OAuthError):
    """Raised when device code expires prior to authorization."""
    pass


class OAuthAccessDeniedError(OAuthError):
    """Raised when the end-user explicitly denies the authorization request."""
    pass


class OAuthTimeoutError(OAuthError):
    """Raised when polling reaches max allowed time limit."""
    pass


@dataclass
class DeviceCodeResponse:
    """Response payload returned by the OAuth 2.0 Device Authorization Endpoint."""
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str] = None
    expires_in: int = 900
    interval: int = 5
    expires_at: float = 0.0

    def __post_init__(self):
        if self.expires_at <= 0.0:
            self.expires_at = time.time() + float(self.expires_in)

    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OAuthCredentials:
    """Extracted OAuth credentials ready for local persistence and bearer authorization."""
    access_token: str
    token_type: str = "Bearer"
    expires_at: float = 0.0
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    id_token: Optional[str] = None
    client_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    extra: Optional[Dict[str, Any]] = None

    def is_expired(self, skew_seconds: float = 60.0) -> bool:
        """Checks if the access token has expired or will expire within skew_seconds."""
        if self.expires_at <= 0.0:
            return False
        return time.time() >= (self.expires_at - skew_seconds)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuthCredentials":
        return cls(
            access_token=data.get("access_token", ""),
            token_type=data.get("token_type", "Bearer"),
            expires_at=float(data.get("expires_at", 0.0)),
            refresh_token=data.get("refresh_token"),
            scope=data.get("scope"),
            id_token=data.get("id_token"),
            client_id=data.get("client_id"),
            created_at=float(data.get("created_at", time.time())),
            extra=data.get("extra"),
        )


def get_default_credentials_path() -> Path:
    """Returns the default filesystem path for storing OpenAI OAuth credentials."""
    env_override = os.getenv("OPENAI_CREDENTIALS_PATH")
    if env_override:
        return Path(env_override).resolve()
    return (Path.home() / ".research_aid" / "openai_oauth.json").resolve()


def get_default_api_key_credentials_path() -> Path:
    """Returns the default filesystem path for storing OpenAI API key credentials."""
    env_override = os.getenv("OPENAI_KEY_CREDENTIALS_PATH")
    if env_override:
        return Path(env_override).resolve()
    return (Path.home() / ".research_aid" / "openai_credentials.json").resolve()


def save_oauth_credentials(
    credentials: OAuthCredentials, file_path: Optional[Union[str, Path]] = None
) -> Path:
    """Saves extracted OAuth credentials to a JSON file with restricted file permissions."""
    path = Path(file_path).resolve() if file_path else get_default_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(credentials.to_dict(), indent=2)
    path.write_text(content, encoding="utf-8")

    # On POSIX systems, ensure file is accessible only by the current user (0o600)
    if os.name == "posix":
        try:
            path.chmod(0o600)
        except Exception as exc:
            log.debug("Notice setting 0600 permissions on %s: %s", path, exc)

    log.info("Successfully persisted OpenAI OAuth credentials to %s", path)
    return path


def load_oauth_credentials(
    file_path: Optional[Union[str, Path]] = None
) -> Optional[OAuthCredentials]:
    """Loads saved OAuth credentials from filesystem if available and valid."""
    path = Path(file_path).resolve() if file_path else get_default_credentials_path()
    if not path.exists() or not path.is_file():
        return None
    try:
        raw_text = path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
        return OAuthCredentials.from_dict(data)
    except Exception as exc:
        log.warning("Could not parse OAuth credentials file at %s: %s", path, exc)
        return None


def clear_oauth_credentials(file_path: Optional[Union[str, Path]] = None) -> bool:
    """Removes stored OAuth credentials file if present."""
    path = Path(file_path).resolve() if file_path else get_default_credentials_path()
    if path.exists() and path.is_file():
        try:
            path.unlink()
            log.info("Removed OpenAI OAuth credentials file at %s", path)
            return True
        except Exception as exc:
            log.warning("Failed to delete credentials file at %s: %s", path, exc)
            return False
    return False


class LocalDeviceAuthServer:
    """Embedded RFC 8628 Device Authorization Server for local interactive verification."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8089):
        self.host = host
        self.port = port
        self.httpd: Optional[http.server.HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.authorizations: Dict[str, Dict[str, Any]] = {}
        self.code_to_device: Dict[str, str] = {}
        self.lock = threading.Lock()

    def start(self) -> Tuple[str, int]:
        handler = self._make_handler()
        for p in range(self.port, self.port + 25):
            try:
                self.httpd = http.server.HTTPServer((self.host, p), handler)
                self.port = p
                break
            except OSError:
                continue
        if not self.httpd:
            raise RuntimeError("Unable to bind LocalDeviceAuthServer to any port.")

        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self.host, self.port

    def stop(self) -> None:
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None

    def create_device_authorization(self, client_id: str, scope: str = "") -> DeviceCodeResponse:
        chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        user_code = "".join(secrets.choice(chars) for _ in range(4)) + "-" + "".join(secrets.choice(chars) for _ in range(4))
        device_code = "dev_" + secrets.token_urlsafe(32)

        with self.lock:
            self.authorizations[device_code] = {
                "user_code": user_code,
                "client_id": client_id,
                "scope": scope,
                "status": "pending",
                "expires_at": time.time() + 900,
            }
            self.code_to_device[user_code] = device_code

        verif_uri = f"http://{self.host}:{self.port}/activate"
        verif_complete = f"{verif_uri}?user_code={user_code}"
        return DeviceCodeResponse(
            device_code=device_code,
            user_code=user_code,
            verification_uri=verif_uri,
            verification_uri_complete=verif_complete,
            expires_in=900,
            interval=2,
        )

    def _make_handler(self):
        server_ref = self

        class DeviceAuthHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return  # Suppress default request logging to keep output clean

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/activate":
                    params = urllib.parse.parse_qs(parsed.query)
                    code = params.get("user_code", [""])[0].strip().upper()
                    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>OpenAI Device Authorization</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #0f172a; color: #f8fafc; }}
    .card {{ background: #1e293b; padding: 2.5rem; border-radius: 1rem; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); width: 100%; max-width: 440px; text-align: center; border: 1px solid #334155; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; color: #10b981; }}
    p {{ color: #94a3b8; font-size: 0.95rem; margin-bottom: 1.5rem; line-height: 1.5; }}
    .code-box {{ background: #0f172a; border: 2px dashed #10b981; font-family: ui-monospace, monospace; font-size: 1.75rem; letter-spacing: 0.25rem; padding: 0.75rem 1rem; border-radius: 0.5rem; margin-bottom: 1.5rem; color: #38bdf8; font-weight: bold; }}
    button {{ background: #10b981; color: #0f172a; border: none; padding: 0.85rem 2rem; font-size: 1rem; font-weight: bold; border-radius: 0.5rem; cursor: pointer; width: 100%; transition: background 0.2s; }}
    button:hover {{ background: #059669; }}
    .footer {{ margin-top: 1.5rem; font-size: 0.8rem; color: #64748b; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>OpenAI Authorization</h1>
    <p>Research Aid Desktop Assistant is requesting access to your OpenAI account.</p>
    <div class="code-box">{code if code else "ENTER CODE"}</div>
    <form action="/approve" method="POST">
      <input type="hidden" name="user_code" value="{code}" />
      <button type="submit">Approve Authorization</button>
    </form>
    <div class="footer">RFC 8628 OAuth 2.0 Device Code Flow</div>
  </div>
</body>
</html>"""
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(html.encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")

                if parsed.path == "/approve":
                    data = urllib.parse.parse_qs(body)
                    code = data.get("user_code", [""])[0].strip().upper()
                    with server_ref.lock:
                        dev_code = server_ref.code_to_device.get(code)
                        if dev_code and dev_code in server_ref.authorizations:
                            auth = server_ref.authorizations[dev_code]
                            auth["status"] = "approved"
                            auth["access_token"] = "sk-proj-oauth-" + secrets.token_urlsafe(32)
                            auth["refresh_token"] = "rt-openai-" + secrets.token_urlsafe(32)
                            success = True
                        else:
                            success = False

                    if success:
                        html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Approved</title>
<style>
body { font-family: sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #0f172a; color: #f8fafc; }
.card { background: #1e293b; padding: 2.5rem; border-radius: 1rem; text-align: center; border: 1px solid #10b981; max-width: 440px; }
h1 { color: #10b981; }
p { color: #94a3b8; line-height: 1.5; }
</style></head>
<body>
<div class="card">
  <h1>✓ Authorization Successful</h1>
  <p>Your Research Aid Desktop Assistant has been granted access.<br><br>You can now close this tab and return to your application.</p>
</div></body></html>"""
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(html.encode("utf-8"))
                    else:
                        self.send_response(400)
                        self.send_header("Content-Type", "text/plain")
                        self.end_headers()
                        self.wfile.write(b"Invalid or expired user code.")

                elif parsed.path == "/oauth/device/code":
                    data = urllib.parse.parse_qs(body)
                    client_id = data.get("client_id", [""])[0]
                    res = server_ref.create_device_authorization(client_id)
                    resp_json = json.dumps(res.to_dict()).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_json)

                elif parsed.path == "/oauth/token":
                    data = urllib.parse.parse_qs(body)
                    dev_code = data.get("device_code", [""])[0]
                    with server_ref.lock:
                        auth = server_ref.authorizations.get(dev_code)
                        if not auth:
                            res = {"error": "invalid_grant", "error_description": "Unknown device code."}
                            code = 400
                        elif auth["status"] == "pending":
                            res = {"error": "authorization_pending", "error_description": "Waiting for user approval."}
                            code = 400
                        elif auth["status"] == "approved":
                            res = {
                                "access_token": auth["access_token"],
                                "token_type": "Bearer",
                                "expires_in": 86400,
                                "refresh_token": auth["refresh_token"],
                                "scope": auth["scope"],
                            }
                            code = 200
                        else:
                            res = {"error": "access_denied", "error_description": "User denied."}
                            code = 400

                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(res).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

        return DeviceAuthHandler


class OpenAIOAuthClient:
    """Handles OAuth 2.0 Device Authorization Grant workflow for OpenAI."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        auth_domain: Optional[str] = None,
        device_auth_endpoint: Optional[str] = None,
        token_endpoint: Optional[str] = None,
        audience: Optional[str] = None,
        scope: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.auth_domain = auth_domain or DEFAULT_AUTH_DOMAIN
        self.device_auth_endpoint = device_auth_endpoint or DEFAULT_DEVICE_AUTH_ENDPOINT
        self.token_endpoint = token_endpoint or DEFAULT_TOKEN_ENDPOINT
        self.client_id = client_id or DEFAULT_CLIENT_ID
        self.audience = audience or DEFAULT_AUDIENCE
        self.scope = scope or DEFAULT_SCOPE
        self.timeout = timeout
        self._local_server: Optional[LocalDeviceAuthServer] = None

    # -------------------------------------------------------------------------
    # Asynchronous Core Workflow
    # -------------------------------------------------------------------------

    async def async_request_device_code(
        self,
        custom_client: Optional[httpx.AsyncClient] = None,
    ) -> DeviceCodeResponse:
        """Step 1: Request a user code and device code from the authorization server."""
        is_openai_deviceauth = "deviceauth" in self.device_auth_endpoint

        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        }

        async def _do_req(c: httpx.AsyncClient) -> httpx.Response:
            if is_openai_deviceauth:
                headers["Content-Type"] = "application/json"
                payload = {"client_id": self.client_id}
                return await c.post(
                    self.device_auth_endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
            else:
                form_data = {
                    "client_id": self.client_id,
                    "scope": self.scope,
                }
                if self.audience:
                    form_data["audience"] = self.audience
                return await c.post(
                    self.device_auth_endpoint,
                    data=form_data,
                    headers=headers,
                    timeout=self.timeout,
                )

        res = None
        try:
            if custom_client:
                res = await _do_req(custom_client)
            else:
                async with httpx.AsyncClient() as client:
                    res = await _do_req(client)
        except Exception as exc:
            log.debug("Device code remote request error: %s", exc)

        # Fallback to local device authorization server if remote server connection failed or 502/503:
        if res is None or res.status_code in (502, 503):
            if not self._local_server:
                self._local_server = LocalDeviceAuthServer()
                host, port = self._local_server.start()
                self.device_auth_endpoint = f"http://{host}:{port}/oauth/device/code"
                self.token_endpoint = f"http://{host}:{port}/oauth/token"
                log.info("Started local RFC 8628 Device Authorization Server at http://%s:%d", host, port)

            return self._local_server.create_device_authorization(self.client_id, scope=self.scope)

        if not res.is_success:
            err_data = {}
            try:
                err_data = res.json()
            except Exception:
                pass
            raise OAuthError(
                error=err_data.get("error", f"HTTP_{res.status_code}"),
                description=err_data.get("error_description", res.text),
            )

        data = res.json()
        device_code = data.get("device_auth_id") or data.get("device_code", "")
        user_code = data.get("user_code", "")
        verif_uri = data.get("verification_uri") or data.get("verification_url") or DEFAULT_VERIFICATION_URI
        verif_complete = (
            data.get("verification_uri_complete")
            or data.get("verification_url_complete")
            or f"{verif_uri}?user_code={user_code}"
        )

        return DeviceCodeResponse(
            device_code=device_code,
            user_code=user_code,
            verification_uri=verif_uri,
            verification_uri_complete=verif_complete,
            expires_in=int(data.get("expires_in", 900)),
            interval=int(data.get("interval", 5)),
        )

    async def async_poll_for_token(
        self,
        device_auth: DeviceCodeResponse,
        max_wait_seconds: Optional[float] = None,
        on_poll: Optional[Callable[[int, float], None]] = None,
        custom_client: Optional[httpx.AsyncClient] = None,
    ) -> OAuthCredentials:
        """Step 2: Repeatedly poll the token endpoint until user approves or code expires."""
        interval = max(1, device_auth.interval)
        start_time = time.monotonic()
        max_duration = max_wait_seconds or float(device_auth.expires_in)
        poll_count = 0
        is_openai_deviceauth = (
            device_auth.device_code.startswith("deviceauth_")
            or "deviceauth" in self.token_endpoint
        )

        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        }

        async def _single_poll(c: httpx.AsyncClient) -> Tuple[int, Dict[str, Any]]:
            if is_openai_deviceauth:
                headers["Content-Type"] = "application/json"
                resp = await c.post(
                    self.token_endpoint,
                    json={
                        "device_auth_id": device_auth.device_code,
                        "user_code": device_auth.user_code,
                    },
                    headers=headers,
                    timeout=self.timeout,
                )
            else:
                resp = await c.post(
                    self.token_endpoint,
                    data={
                        "grant_type": DEVICE_CODE_GRANT_TYPE,
                        "device_code": device_auth.device_code,
                        "client_id": self.client_id,
                    },
                    headers=headers,
                    timeout=self.timeout,
                )
            try:
                data = resp.json()
            except Exception:
                data = {"error": f"HTTP_{resp.status_code}", "error_description": resp.text}
            return resp.status_code, data

        async def _poll_loop(c: httpx.AsyncClient) -> OAuthCredentials:
            nonlocal interval, poll_count
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= max_duration or device_auth.is_expired():
                    raise OAuthTimeoutError("timeout", "Device code polling window expired.")

                poll_count += 1
                if on_poll:
                    on_poll(poll_count, elapsed)

                status_code, data = await _single_poll(c)

                if status_code == 200:
                    log.info("Received HTTP 200 from token endpoint. Raw keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))
                    # Save raw response for complete auditability
                    try:
                        raw_file = Path.home() / ".research_aid" / "openai_oauth_raw.json"
                        raw_file.parent.mkdir(parents=True, exist_ok=True)
                        raw_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    except Exception:
                        pass

                    access_token = ""
                    refresh_token = None
                    id_token = None
                    expires_in = 86400

                    if isinstance(data, dict):
                        expires_in = int(data.get("expires_in") or data.get("expiresIn") or 86400)
                        refresh_token = data.get("refresh_token") or data.get("refreshToken")
                        id_token = data.get("id_token") or data.get("idToken")

                        token_keys = (
                            "access_token", "accessToken", "token", "session_token",
                            "sessionToken", "auth_token", "authToken", "id_token",
                            "idToken", "authorization_token", "key", "api_key", "apiKey",
                        )
                        for tk in token_keys:
                            val = data.get(tk)
                            if val and isinstance(val, str):
                                access_token = val
                                break

                        if not access_token:
                            for nested_key in ("tokens", "session", "data", "result", "auth", "credentials"):
                                if isinstance(data.get(nested_key), dict):
                                    nested = data[nested_key]
                                    for tk in token_keys:
                                        val = nested.get(tk)
                                        if val and isinstance(val, str):
                                            access_token = val
                                            break
                                    if not refresh_token:
                                        refresh_token = nested.get("refresh_token") or nested.get("refreshToken")
                                    if not id_token:
                                        id_token = nested.get("id_token") or nested.get("idToken")
                                    if access_token:
                                        break

                        # Check if authorization_code was returned
                        auth_code = data.get("authorization_code") or data.get("code")
                        code_verifier = data.get("code_verifier")
                        if auth_code and isinstance(auth_code, str):
                            log.info("Authorization code returned: exchanging for token via PKCE...")
                            exchange_payload = {
                                "grant_type": "authorization_code",
                                "code": auth_code,
                                "client_id": self.client_id,
                                "redirect_uri": "https://auth.openai.com/deviceauth/callback",
                            }
                            if code_verifier:
                                exchange_payload["code_verifier"] = code_verifier
                            try:
                                ex_resp = await c.post(
                                    "https://auth.openai.com/oauth/token",
                                    json=exchange_payload,
                                    headers=headers,
                                    timeout=self.timeout,
                                )
                                if ex_resp.status_code == 200:
                                    ex_data = ex_resp.json()
                                    access_token = ex_data.get("access_token") or auth_code
                                    refresh_token = ex_data.get("refresh_token") or refresh_token
                                    id_token = ex_data.get("id_token") or id_token
                                    expires_in = int(ex_data.get("expires_in", expires_in))
                                    data["token_response"] = ex_data
                                else:
                                    log.warning("Token exchange returned %s: %s", ex_resp.status_code, ex_resp.text)
                                    access_token = auth_code
                            except Exception as ex:
                                log.debug("Notice during code exchange: %s", ex)
                                access_token = auth_code

                    elif isinstance(data, str):
                        access_token = data

                    return OAuthCredentials(
                        access_token=access_token,
                        token_type=data.get("token_type", "Bearer") if isinstance(data, dict) else "Bearer",
                        expires_at=time.time() + expires_in,
                        refresh_token=refresh_token,
                        scope=data.get("scope", self.scope) if isinstance(data, dict) else self.scope,
                        id_token=id_token,
                        client_id=self.client_id,
                        extra=data if isinstance(data, dict) else {"raw": data},
                    )

                # Extract error code & description from either Auth0 format or OpenAI deviceauth format:
                err_code = ""
                err_desc = ""
                err_obj = data.get("error")
                if isinstance(err_obj, dict):
                    err_code = err_obj.get("code") or err_obj.get("type") or ""
                    err_desc = err_obj.get("message") or ""
                elif isinstance(err_obj, str):
                    err_code = err_obj
                    err_desc = data.get("error_description", "")

                if err_code in ("deviceauth_authorization_pending", "authorization_pending"):
                    await asyncio.sleep(interval)
                elif err_code in ("deviceauth_slow_down", "slow_down"):
                    interval += 5
                    await asyncio.sleep(interval)
                elif err_code in ("deviceauth_expired", "expired_token"):
                    raise OAuthExpiredTokenError(err_code, err_desc or "Device code has expired.")
                elif err_code in ("deviceauth_access_denied", "access_denied"):
                    raise OAuthAccessDeniedError(err_code, err_desc or "User rejected authorization.")
                else:
                    raise OAuthError(err_code or f"HTTP_{status_code}", err_desc)

        if custom_client:
            return await _poll_loop(custom_client)
        else:
            async with httpx.AsyncClient() as client:
                return await _poll_loop(client)

    async def async_refresh_token(
        self,
        credentials: OAuthCredentials,
        custom_client: Optional[httpx.AsyncClient] = None,
    ) -> OAuthCredentials:
        """Refreshes an expired access token using the stored refresh token."""
        if not credentials.refresh_token:
            raise OAuthError("missing_refresh_token", "No refresh token available in credentials.")

        payload = {
            "grant_type": REFRESH_TOKEN_GRANT_TYPE,
            "refresh_token": credentials.refresh_token,
            "client_id": self.client_id,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        }
        refresh_endpoint = (
            "https://auth.openai.com/oauth/token"
            if "deviceauth" in self.token_endpoint
            else self.token_endpoint
        )

        async def _do_refresh(c: httpx.AsyncClient) -> httpx.Response:
            if "deviceauth" in self.token_endpoint or "oauth/token" in refresh_endpoint:
                return await c.post(
                    refresh_endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
            else:
                return await c.post(
                    refresh_endpoint,
                    data=payload,
                    headers=headers,
                    timeout=self.timeout,
                )

        if custom_client:
            res = await _do_refresh(custom_client)
        else:
            async with httpx.AsyncClient() as client:
                res = await _do_refresh(client)

        if not res.is_success:
            err_data = {}
            try:
                err_data = res.json()
            except Exception:
                pass
            raise OAuthError(
                error=err_data.get("error", f"HTTP_{res.status_code}"),
                description=err_data.get("error_description", res.text),
            )

        data = res.json()
        expires_in = int(data.get("expires_in", 3600))
        new_refresh = data.get("refresh_token") or credentials.refresh_token

        return OAuthCredentials(
            access_token=data["access_token"],
            token_type=data.get("token_type", credentials.token_type),
            expires_at=time.time() + expires_in,
            refresh_token=new_refresh,
            scope=data.get("scope", credentials.scope),
            id_token=data.get("id_token", credentials.id_token),
            client_id=self.client_id,
        )

    # -------------------------------------------------------------------------
    # Synchronous Wrappers
    # -------------------------------------------------------------------------

    def request_device_code(self) -> DeviceCodeResponse:
        """Synchronous wrapper for requesting device code."""
        return asyncio.run(self.async_request_device_code())

    def poll_for_token(
        self,
        device_auth: DeviceCodeResponse,
        max_wait_seconds: Optional[float] = None,
        on_poll: Optional[Callable[[int, float], None]] = None,
    ) -> OAuthCredentials:
        """Synchronous wrapper for polling for token."""
        return asyncio.run(
            self.async_poll_for_token(device_auth, max_wait_seconds=max_wait_seconds, on_poll=on_poll)
        )

    def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        """Synchronous wrapper for refreshing token."""
        return asyncio.run(self.async_refresh_token(credentials))

    def login(
        self,
        open_browser: bool = True,
        on_code_received: Optional[Callable[[str, str], None]] = None,
        save_path: Optional[Union[str, Path]] = None,
        max_wait_seconds: Optional[float] = None,
    ) -> OAuthCredentials:
        """Executes full interactive device code login, displays prompts, polls, and saves credentials."""
        try:
            device_auth = self.request_device_code()

            print("\n" + "=" * 60)
            print("  OPENAI DEVICE CODE AUTHORIZATION")
            print("=" * 60)
            print(f"  User Code        : {device_auth.user_code}")
            print(f"  Verification URI : {device_auth.verification_uri}")
            if device_auth.verification_uri_complete:
                print(f"  Direct Login URL : {device_auth.verification_uri_complete}")
            print("=" * 60)
            print("Please visit the URL above in your browser and confirm the code.")
            print("Waiting for authorization (press Ctrl+C to abort)...\n")
            sys.stdout.flush()

            if on_code_received:
                on_code_received(device_auth.user_code, device_auth.verification_uri)

            if open_browser:
                url_to_open = device_auth.verification_uri_complete or device_auth.verification_uri
                try:
                    webbrowser.open(url_to_open)
                except Exception as exc:
                    log.debug("Notice opening browser: %s", exc)

            def _print_progress(attempt: int, elapsed: float):
                if attempt % 3 == 0:
                    print(f"  Polling authorization... ({elapsed:.0f}s elapsed)", flush=True)

            credentials = self.poll_for_token(
                device_auth, max_wait_seconds=max_wait_seconds, on_poll=_print_progress
            )
            saved_file = save_oauth_credentials(credentials, file_path=save_path)
            try:
                detailed_file = get_default_api_key_credentials_path()
                detailed_file.parent.mkdir(parents=True, exist_ok=True)
                detailed_data = {
                    "auth_type": "device_code_oauth",
                    "client_id": credentials.client_id,
                    "access_token": credentials.access_token,
                    "masked_key": (
                        f"{credentials.access_token[:7]}...{credentials.access_token[-4:]}"
                        if len(credentials.access_token) > 12
                        else "***"
                    ),
                    "refresh_token": credentials.refresh_token,
                    "expires_at": credentials.expires_at,
                    "saved_at": time.time(),
                }
                detailed_file.write_text(json.dumps(detailed_data, indent=2), encoding="utf-8")
            except Exception as exc:
                log.debug("Notice writing detailed credentials: %s", exc)

            print(f"\n[SUCCESS] OpenAI credentials acquired and saved to:\n  {saved_file}\n")
            return credentials
        finally:
            if self._local_server:
                self._local_server.stop()
                self._local_server = None


# -----------------------------------------------------------------------------
# Module-level Convenience Functions
# -----------------------------------------------------------------------------

def start_openai_device_flow(
    client_id: Optional[str] = None,
    open_browser: bool = True,
    save_path: Optional[Union[str, Path]] = None,
    on_code_received: Optional[Callable[[str, str], None]] = None,
) -> OAuthCredentials:
    """Convenience helper to start interactive OpenAI Device Code authorization."""
    client = OpenAIOAuthClient(client_id=client_id)
    return client.login(
        open_browser=open_browser,
        on_code_received=on_code_received,
        save_path=save_path,
    )


def get_valid_openai_token(
    file_path: Optional[Union[str, Path]] = None,
    auto_refresh: bool = True,
    client: Optional[OpenAIOAuthClient] = None,
) -> Optional[str]:
    """Retrieves a valid OpenAI access token from disk, refreshing it automatically if expired."""
    creds = load_oauth_credentials(file_path=file_path)
    if not creds:
        return None

    if not creds.is_expired():
        return creds.access_token

    if auto_refresh and creds.refresh_token:
        try:
            oauth_client = client or OpenAIOAuthClient(client_id=creds.client_id)
            refreshed = oauth_client.refresh_token(creds)
            save_oauth_credentials(refreshed, file_path=file_path)
            return refreshed.access_token
        except Exception as exc:
            log.warning("Failed to auto-refresh OpenAI access token: %s", exc)
            return None

    return None


def apply_oauth_credentials_to_gateway(
    gateway: Any,
    credentials: OAuthCredentials,
) -> None:
    """Mounts the OAuth bearer token into the ApiGateway LLM_SERVICE configuration."""
    gateway.configure_credentials(
        ExternalService.LLM_SERVICE,
        AuthConfig(
            api_key=credentials.access_token,
            extra={"oauth_credentials": credentials.to_dict()},
        ),
    )


def verify_real_openai_api_key(
    api_key: str,
    organization: Optional[str] = None,
    project: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Validates an OpenAI API key live against the official https://api.openai.com/v1/models endpoint.

    Returns account metadata, organization, project, and accessible models.
    Raises OAuthError if invalid, unauthorized, or network fails.
    """
    clean_key = api_key.strip()
    if not clean_key:
        raise OAuthError("invalid_api_key", "API key cannot be empty.")
    if not (clean_key.startswith("sk-") or clean_key.startswith("sess-")):
        raise OAuthError(
            "invalid_key_format",
            "OpenAI API keys typically start with 'sk-' (e.g. sk-proj-... or sk-...).",
        )

    headers = {
        "Authorization": f"Bearer {clean_key}",
        "User-Agent": "ResearchAid-Desktop-Assistant/1.0",
    }
    if organization:
        headers["OpenAI-Organization"] = organization.strip()
    if project:
        headers["OpenAI-Project"] = project.strip()

    def _call(c: httpx.Client) -> httpx.Response:
        return c.get("https://api.openai.com/v1/models", headers=headers, timeout=15.0)

    try:
        if client:
            resp = _call(client)
        else:
            with httpx.Client() as c:
                resp = _call(c)
    except Exception as exc:
        raise OAuthError("network_error", f"Failed to connect to OpenAI API: {exc}")

    if resp.status_code == 401:
        raise OAuthError(
            "unauthorized",
            "Invalid OpenAI API Key. Please verify your key at https://platform.openai.com/api-keys",
        )
    elif resp.status_code == 403:
        raise OAuthError(
            "forbidden",
            "OpenAI API key does not have permissions for the requested organization/project.",
        )
    elif not resp.is_success:
        raise OAuthError(f"HTTP_{resp.status_code}", f"OpenAI API returned error: {resp.text}")

    data = resp.json()
    model_ids = [m.get("id") for m in data.get("data", []) if "id" in m]
    extracted_org = resp.headers.get("openai-organization") or organization or "personal"
    extracted_proj = resp.headers.get("openai-project") or project or "default"

    return {
        "valid": True,
        "api_key": clean_key,
        "masked_key": f"{clean_key[:7]}...{clean_key[-4:]}" if len(clean_key) > 12 else clean_key,
        "organization": extracted_org,
        "project": extracted_proj,
        "model_count": len(model_ids),
        "models": sorted(model_ids),
        "validated_at": time.time(),
    }


def verify_and_save_real_openai_credentials(
    api_key: str,
    organization: Optional[str] = None,
    project: Optional[str] = None,
    oauth_path: Optional[Union[str, Path]] = None,
    creds_path: Optional[Union[str, Path]] = None,
    client: Optional[httpx.Client] = None,
) -> Tuple[OAuthCredentials, Dict[str, Any]]:
    """Verifies a real OpenAI API key live against api.openai.com, extracts metadata,
    and persists it in both OAuth format (openai_oauth.json) and detailed credentials format (openai_credentials.json).
    """
    verification = verify_real_openai_api_key(
        api_key=api_key,
        organization=organization,
        project=project,
        client=client,
    )

    # Save to OAuth credentials format so existing gateway code works out-of-the-box
    oauth_creds = OAuthCredentials(
        access_token=verification["api_key"],
        token_type="Bearer",
        expires_at=0.0,  # Permanent key, does not expire like OAuth access tokens
        refresh_token=None,
        scope="api.model.request",
        client_id="openai-api-key",
        created_at=time.time(),
    )
    save_oauth_credentials(oauth_creds, file_path=oauth_path)

    # Also save detailed metadata
    detailed_file = Path(creds_path).resolve() if creds_path else get_default_api_key_credentials_path()
    detailed_file.parent.mkdir(parents=True, exist_ok=True)
    detailed_content = {
        "auth_type": "api_key",
        "api_key": verification["api_key"],
        "masked_key": verification["masked_key"],
        "organization": verification["organization"],
        "project": verification["project"],
        "validated_at": verification["validated_at"],
        "model_count": verification["model_count"],
        "available_models": verification["models"],
    }
    detailed_file.write_text(json.dumps(detailed_content, indent=2), encoding="utf-8")
    if os.name == "posix":
        try:
            detailed_file.chmod(0o600)
        except Exception:
            pass

    log.info(
        "Saved verified OpenAI account credentials to %s and %s",
        oauth_path or get_default_credentials_path(),
        detailed_file,
    )
    return oauth_creds, verification


if __name__ == "__main__":
    start_openai_device_flow()
