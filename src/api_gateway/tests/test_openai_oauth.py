"""Unit and integration tests for OpenAI OAuth Device Code Flow subsystem."""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from api_gateway.models import ExternalService
from api_gateway.gateway import ApiGateway
from api_gateway.oauth import (
    DeviceCodeResponse,
    OAuthAccessDeniedError,
    OAuthCredentials,
    OAuthError,
    OAuthExpiredTokenError,
    OAuthTimeoutError,
    OpenAIOAuthClient,
    apply_oauth_credentials_to_gateway,
    clear_oauth_credentials,
    get_default_api_key_credentials_path,
    get_default_credentials_path,
    get_valid_openai_token,
    load_oauth_credentials,
    save_oauth_credentials,
    verify_and_save_real_openai_credentials,
    verify_real_openai_api_key,
)


def test_device_code_response_lifecycle():
    resp = DeviceCodeResponse(
        device_code="dev_12345",
        user_code="ABCD-EFGH",
        verification_uri="https://auth.openai.com/activate",
        verification_uri_complete="https://auth.openai.com/activate?user_code=ABCD-EFGH",
        expires_in=600,
        interval=5,
    )
    assert resp.device_code == "dev_12345"
    assert resp.user_code == "ABCD-EFGH"
    assert resp.is_expired() is False
    assert resp.expires_at > time.time() + 500

    data = resp.to_dict()
    assert data["user_code"] == "ABCD-EFGH"
    assert data["interval"] == 5


def test_oauth_credentials_serialization_and_expiry():
    now = time.time()
    creds = OAuthCredentials(
        access_token="test_access_token_abc",
        token_type="Bearer",
        expires_at=now + 120.0,
        refresh_token="test_refresh_token_xyz",
        scope="openid profile email offline_access",
        client_id="test_client_id",
    )
    assert creds.is_expired(skew_seconds=60.0) is False
    assert creds.is_expired(skew_seconds=180.0) is True

    dict_data = creds.to_dict()
    assert dict_data["access_token"] == "test_access_token_abc"
    assert dict_data["refresh_token"] == "test_refresh_token_xyz"

    loaded = OAuthCredentials.from_dict(dict_data)
    assert loaded.access_token == creds.access_token
    assert loaded.refresh_token == creds.refresh_token
    assert loaded.expires_at == creds.expires_at


def test_credentials_file_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "test_creds.json"

        creds = OAuthCredentials(
            access_token="tok_secret_123",
            expires_at=time.time() + 3600,
            refresh_token="ref_secret_456",
            client_id="my_client",
        )

        # 1. Save
        saved_file = save_oauth_credentials(creds, file_path=save_path)
        assert saved_file.exists()
        assert saved_file == save_path

        # 2. Load
        loaded = load_oauth_credentials(file_path=save_path)
        assert loaded is not None
        assert loaded.access_token == "tok_secret_123"
        assert loaded.refresh_token == "ref_secret_456"
        assert loaded.client_id == "my_client"

        # 3. Clear
        cleared = clear_oauth_credentials(file_path=save_path)
        assert cleared is True
        assert not save_path.exists()

        # Loading missing file returns None
        assert load_oauth_credentials(file_path=save_path) is None


@pytest.mark.asyncio
async def test_async_request_device_code():
    client = OpenAIOAuthClient(client_id="test-client-id")

    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "device_code": "dev_code_abc123",
        "user_code": "XYZ-999",
        "verification_uri": "https://auth.openai.com/activate",
        "verification_uri_complete": "https://auth.openai.com/activate?user_code=XYZ-999",
        "expires_in": 900,
        "interval": 5,
    }

    mock_http_client = AsyncMock()
    mock_http_client.post.return_value = mock_resp

    dev_code_res = await client.async_request_device_code(custom_client=mock_http_client)
    assert dev_code_res.device_code == "dev_code_abc123"
    assert dev_code_res.user_code == "XYZ-999"
    assert dev_code_res.verification_uri == "https://auth.openai.com/activate"
    assert dev_code_res.interval == 5


@pytest.mark.asyncio
async def test_async_poll_for_token_success_after_pending():
    client = OpenAIOAuthClient(client_id="test-client")
    dev_auth = DeviceCodeResponse(
        device_code="dev_code_1",
        user_code="USER-CODE",
        verification_uri="https://auth.openai.com/activate",
        expires_in=60,
        interval=1,
    )

    # 1st call: authorization_pending, 2nd call: 200 OK
    resp_pending = MagicMock(status_code=400, is_success=False)
    resp_pending.json.return_value = {"error": "authorization_pending", "error_description": "User has not authorized yet"}

    resp_ok = MagicMock(status_code=200, is_success=True)
    resp_ok.json.return_value = {
        "access_token": "acc_tok_999",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "ref_tok_888",
        "scope": "openid model.request",
    }

    mock_http_client = AsyncMock()
    mock_http_client.post.side_effect = [resp_pending, resp_ok]

    polls = []
    def on_poll(attempt, elapsed):
        polls.append(attempt)

    # Patch sleep to make test instantaneous
    with patch("asyncio.sleep", AsyncMock()):
        creds = await client.async_poll_for_token(
            dev_auth,
            max_wait_seconds=10,
            on_poll=on_poll,
            custom_client=mock_http_client,
        )

    assert creds.access_token == "acc_tok_999"
    assert creds.refresh_token == "ref_tok_888"
    assert creds.token_type == "Bearer"
    assert creds.is_expired() is False
    assert len(polls) == 2


@pytest.mark.asyncio
async def test_async_poll_for_token_expired_error():
    client = OpenAIOAuthClient()
    dev_auth = DeviceCodeResponse(
        device_code="dev_code_1",
        user_code="USER-CODE",
        verification_uri="https://auth.openai.com/activate",
        expires_in=60,
        interval=1,
    )

    resp_expired = MagicMock(status_code=400, is_success=False)
    resp_expired.json.return_value = {"error": "expired_token", "error_description": "The code expired"}

    mock_http_client = AsyncMock()
    mock_http_client.post.return_value = resp_expired

    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(OAuthExpiredTokenError) as exc_info:
            await client.async_poll_for_token(dev_auth, custom_client=mock_http_client)
        assert "expired_token" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_poll_for_token_access_denied_error():
    client = OpenAIOAuthClient()
    dev_auth = DeviceCodeResponse(
        device_code="dev_code_1",
        user_code="USER-CODE",
        verification_uri="https://auth.openai.com/activate",
        expires_in=60,
        interval=1,
    )

    resp_denied = MagicMock(status_code=400, is_success=False)
    resp_denied.json.return_value = {"error": "access_denied", "error_description": "User denied"}

    mock_http_client = AsyncMock()
    mock_http_client.post.return_value = resp_denied

    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(OAuthAccessDeniedError) as exc_info:
            await client.async_poll_for_token(dev_auth, custom_client=mock_http_client)
        assert "access_denied" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_refresh_token():
    client = OpenAIOAuthClient(client_id="test-client")
    initial_creds = OAuthCredentials(
        access_token="expired_tok",
        expires_at=time.time() - 100,  # expired
        refresh_token="valid_refresh_token",
        client_id="test-client",
    )

    resp_refresh = MagicMock(status_code=200, is_success=True)
    resp_refresh.json.return_value = {
        "access_token": "new_refreshed_access_token",
        "token_type": "Bearer",
        "expires_in": 7200,
        "refresh_token": "new_rotated_refresh_token",
    }

    mock_http_client = AsyncMock()
    mock_http_client.post.return_value = resp_refresh

    new_creds = await client.async_refresh_token(initial_creds, custom_client=mock_http_client)
    assert new_creds.access_token == "new_refreshed_access_token"
    assert new_creds.refresh_token == "new_rotated_refresh_token"
    assert new_creds.is_expired() is False


def test_get_valid_openai_token_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "oauth.json"

        # 1. Valid token returns without refresh
        valid_creds = OAuthCredentials(
            access_token="valid_token_123",
            expires_at=time.time() + 3600,
            refresh_token="ref_123",
        )
        save_oauth_credentials(valid_creds, file_path=path)

        tok = get_valid_openai_token(file_path=path, auto_refresh=False)
        assert tok == "valid_token_123"

        # 2. Expired token triggers refresh
        expired_creds = OAuthCredentials(
            access_token="old_expired_token",
            expires_at=time.time() - 100,
            refresh_token="ref_to_refresh",
        )
        save_oauth_credentials(expired_creds, file_path=path)

        mock_client = MagicMock()
        mock_client.refresh_token.return_value = OAuthCredentials(
            access_token="refreshed_token_success",
            expires_at=time.time() + 3600,
            refresh_token="new_ref_456",
        )

        refreshed_tok = get_valid_openai_token(file_path=path, auto_refresh=True, client=mock_client)
        assert refreshed_tok == "refreshed_token_success"

        # Verify new credentials were saved to disk
        updated_creds = load_oauth_credentials(file_path=path)
        assert updated_creds.access_token == "refreshed_token_success"
        assert updated_creds.refresh_token == "new_ref_456"


def test_apply_oauth_credentials_to_gateway():
    gateway = ApiGateway()
    creds = OAuthCredentials(
        access_token="tok_gateway_123",
        expires_at=time.time() + 3600,
        refresh_token="ref_gateway",
    )

    apply_oauth_credentials_to_gateway(gateway, creds)
    auth_cfg = gateway.credentials[ExternalService.LLM_SERVICE]
    assert auth_cfg.api_key == "tok_gateway_123"
    assert "oauth_credentials" in auth_cfg.extra


def test_sync_login_workflow():
    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "login_creds.json"
        client = OpenAIOAuthClient(client_id="test-cli")

        fake_dev_auth = DeviceCodeResponse(
            device_code="dev_code_sync",
            user_code="CODE-SYNC",
            verification_uri="https://auth.openai.com/activate",
            expires_in=60,
        )
        fake_creds = OAuthCredentials(
            access_token="sync_access_token",
            expires_at=time.time() + 3600,
            refresh_token="sync_refresh_token",
        )

        codes_received = []
        def on_code(user_code, uri):
            codes_received.append((user_code, uri))

        with patch.object(client, "request_device_code", return_value=fake_dev_auth), \
             patch.object(client, "poll_for_token", return_value=fake_creds), \
             patch("webbrowser.open") as mock_open:

            result = client.login(
                open_browser=True,
                on_code_received=on_code,
                save_path=save_path,
            )

            assert result.access_token == "sync_access_token"
            assert mock_open.called
            assert len(codes_received) == 1
            assert codes_received[0][0] == "CODE-SYNC"
            assert save_path.exists()


def test_verify_real_openai_api_key_valid():
    fake_models_resp = {
        "object": "list",
        "data": [
            {"id": "gpt-4o", "object": "model"},
            {"id": "gpt-4o-mini", "object": "model"},
            {"id": "text-embedding-3-small", "object": "model"},
        ],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = fake_models_resp
    mock_resp.headers = {
        "openai-organization": "org-test-org-123",
        "openai-project": "proj_test_proj_456",
    }

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    result = verify_real_openai_api_key(
        api_key="sk-proj-valid-test-key-1234567890",
        client=mock_client,
    )

    assert result["valid"] is True
    assert result["organization"] == "org-test-org-123"
    assert result["project"] == "proj_test_proj_456"
    assert result["model_count"] == 3
    assert "gpt-4o" in result["models"]
    assert result["masked_key"].startswith("sk-proj")


def test_verify_real_openai_api_key_invalid_format():
    with pytest.raises(OAuthError) as exc_info:
        verify_real_openai_api_key(api_key="invalid_no_sk_prefix")
    assert "invalid_key_format" in str(exc_info.value)

    with pytest.raises(OAuthError) as exc_info2:
        verify_real_openai_api_key(api_key="   ")
    assert "invalid_api_key" in str(exc_info2.value)


def test_verify_real_openai_api_key_unauthorized():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.is_success = False
    mock_resp.text = "Incorrect API key provided"

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    with pytest.raises(OAuthError) as exc_info:
        verify_real_openai_api_key(
            api_key="sk-proj-invalid-key-999",
            client=mock_client,
        )
    assert "unauthorized" in str(exc_info.value)


def test_verify_and_save_real_openai_credentials():
    fake_models_resp = {
        "data": [{"id": "gpt-4o"}],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = fake_models_resp
    mock_resp.headers = {"openai-organization": "org-auto"}

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    with tempfile.TemporaryDirectory() as tmpdir:
        oauth_file = Path(tmpdir) / "oauth.json"
        creds_file = Path(tmpdir) / "creds.json"

        oauth_creds, meta = verify_and_save_real_openai_credentials(
            api_key="sk-proj-real-test-key-abc",
            oauth_path=oauth_file,
            creds_path=creds_file,
            client=mock_client,
        )

        assert oauth_creds.access_token == "sk-proj-real-test-key-abc"
        assert oauth_file.exists()
        assert creds_file.exists()

        # Check OAuth loaded
        loaded_oauth = load_oauth_credentials(oauth_file)
        assert loaded_oauth is not None
        assert loaded_oauth.access_token == "sk-proj-real-test-key-abc"

        # Check detailed JSON loaded
        saved_meta = json.loads(creds_file.read_text())
        assert saved_meta["auth_type"] == "api_key"
        assert saved_meta["organization"] == "org-auto"
        assert saved_meta["model_count"] == 1


@pytest.mark.asyncio
async def test_openai_official_deviceauth_workflow():
    client = OpenAIOAuthClient(
        device_auth_endpoint="https://auth.openai.com/api/accounts/deviceauth/usercode",
        token_endpoint="https://auth.openai.com/api/accounts/deviceauth/token",
        client_id="app_EMoamEEZ73f0CkXaXp7hrann",
    )

    # 1. Mock usercode response
    mock_usercode_resp = MagicMock()
    mock_usercode_resp.status_code = 200
    mock_usercode_resp.is_success = True
    mock_usercode_resp.json.return_value = {
        "device_auth_id": "deviceauth_test_123456",
        "user_code": "BARC-12345",
        "interval": "5",
        "expires_at": "2026-09-13T17:15:00.000000+00:00",
    }

    mock_async_client = AsyncMock()
    mock_async_client.post.return_value = mock_usercode_resp

    dev_auth = await client.async_request_device_code(custom_client=mock_async_client)
    assert dev_auth.device_code == "deviceauth_test_123456"
    assert dev_auth.user_code == "BARC-12345"
    assert "https://auth.openai.com/codex/device" in dev_auth.verification_uri
    assert dev_auth.interval == 5

    # 2. Mock polling pending then success
    mock_pending_resp = MagicMock()
    mock_pending_resp.status_code = 403
    mock_pending_resp.json.return_value = {
        "error": {
            "code": "deviceauth_authorization_pending",
            "message": "Device authorization is pending. Please try again.",
        }
    }

    mock_success_resp = MagicMock()
    mock_success_resp.status_code = 200
    mock_success_resp.json.return_value = {
        "access_token": "sess-openai-extracted-token-xyz",
        "refresh_token": "rt-openai-extracted-rt-abc",
        "expires_in": 3600,
        "token_type": "Bearer",
    }

    mock_poll_client = AsyncMock()
    mock_poll_client.post.side_effect = [mock_pending_resp, mock_success_resp]

    # Fast interval for test
    dev_auth.interval = 0

    creds = await client.async_poll_for_token(dev_auth, custom_client=mock_poll_client)
    assert creds.access_token == "sess-openai-extracted-token-xyz"
    assert creds.refresh_token == "rt-openai-extracted-rt-abc"
    assert creds.token_type == "Bearer"


@pytest.mark.asyncio
async def test_openai_official_deviceauth_with_code_verifier_exchange():
    client = OpenAIOAuthClient(
        device_auth_endpoint="https://auth.openai.com/api/accounts/deviceauth/usercode",
        token_endpoint="https://auth.openai.com/api/accounts/deviceauth/token",
        client_id="app_EMoamEEZ73f0CkXaXp7hrann",
    )

    dev_auth = DeviceCodeResponse(
        device_code="deviceauth_pkce_123",
        user_code="PKCE-CODE",
        verification_uri="https://auth.openai.com/codex/device",
        interval=0,
    )

    # 1. First poll returns authorization_code + code_verifier
    mock_auth_code_resp = MagicMock()
    mock_auth_code_resp.status_code = 200
    mock_auth_code_resp.json.return_value = {
        "status": "success",
        "authorization_code": "ac_pkce_auth_code_123",
        "code_verifier": "verifier_secret_abc",
    }

    # 2. Code exchange at /oauth/token returns final tokens
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "eyJhbGciOi_final_jwt_token",
        "refresh_token": "rt.1.final_refresh_token",
        "id_token": "id_tok_123",
        "expires_in": 7200,
        "token_type": "Bearer",
    }

    mock_client = AsyncMock()
    mock_client.post.side_effect = [mock_auth_code_resp, mock_token_resp]

    creds = await client.async_poll_for_token(dev_auth, custom_client=mock_client)
    assert creds.access_token == "eyJhbGciOi_final_jwt_token"
    assert creds.refresh_token == "rt.1.final_refresh_token"
    assert creds.id_token == "id_tok_123"
    assert creds.token_type == "Bearer"

