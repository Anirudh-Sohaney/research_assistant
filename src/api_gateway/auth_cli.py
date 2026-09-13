"""Command-line interface for OpenAI authentication and credential management in Research Aid.

Supports:
1. Live validation and secure extraction of OpenAI API credentials.
2. Checking credential status, permissions, and available models.
3. Clearing stored credentials.
4. RFC 8628 Device Code authorization (for enterprise/bridge environments).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
from typing import Optional

from api_gateway.oauth import (
    OAuthError,
    clear_oauth_credentials,
    get_default_api_key_credentials_path,
    get_default_credentials_path,
    load_oauth_credentials,
    start_openai_device_flow,
    verify_and_save_real_openai_credentials,
)


def print_banner() -> None:
    print("=" * 66)
    print("  RESEARCH AID - OPENAI ACCOUNT AUTHENTICATION")
    print("=" * 66)


def show_status() -> None:
    oauth_file = get_default_credentials_path()
    creds_file = get_default_api_key_credentials_path()

    print("\n--- Credential Status ---")
    print(f"  OAuth Path      : {oauth_file}")
    print(f"  Credentials Path: {creds_file}")

    if not oauth_file.exists() and not creds_file.exists():
        print("\n  Status: No OpenAI credentials configured yet.")
        print("  Run 'python -m api_gateway.auth_cli' to authenticate your account.\n")
        return

    if creds_file.exists():
        try:
            data = json.loads(creds_file.read_text(encoding="utf-8"))
            print("\n  [Active Real OpenAI Account]")
            print(f"  Auth Type   : {data.get('auth_type', 'api_key')}")
            print(f"  Key (Masked): {data.get('masked_key', '***')}")
            print(f"  Organization: {data.get('organization', 'N/A')}")
            print(f"  Project     : {data.get('project', 'N/A')}")
            print(f"  Models Found: {data.get('model_count', 0)}")
            sample_models = data.get("available_models", [])[:5]
            if sample_models:
                print(f"  Sample Models: {', '.join(sample_models)}...")
        except Exception as exc:
            print(f"  Could not read {creds_file}: {exc}")

    if oauth_file.exists():
        oauth_creds = load_oauth_credentials(oauth_file)
        if oauth_creds:
            print("\n  [OAuth Token Gateway View]")
            print(f"  Client ID   : {oauth_creds.client_id}")
            print(f"  Token Type  : {oauth_creds.token_type}")
            print(f"  Is Expired  : {oauth_creds.is_expired()}")
            if oauth_creds.refresh_token:
                print(f"  Refresh Tok : Configured")
    print()


def authenticate_with_key(
    key: str,
    organization: Optional[str] = None,
    project: Optional[str] = None,
) -> bool:
    print("\nConnecting to OpenAI API to validate credentials...")
    try:
        oauth_creds, meta = verify_and_save_real_openai_credentials(
            api_key=key,
            organization=organization,
            project=project,
        )
        print("\n" + "=" * 66)
        print("  [SUCCESS] OpenAI Account Authenticated Successfully!")
        print("=" * 66)
        print(f"  Organization    : {meta['organization']}")
        print(f"  Project         : {meta['project']}")
        print(f"  Masked Key      : {meta['masked_key']}")
        print(f"  Models Validated: {meta['model_count']} available")
        print(f"  OAuth Store     : {get_default_credentials_path()}")
        print(f"  Metadata Store  : {get_default_api_key_credentials_path()}")
        print("=" * 66 + "\n")
        return True
    except OAuthError as err:
        print("\n" + "!" * 66)
        print(f"  [ERROR] Authentication Failed: {err}")
        print("!" * 66 + "\n")
        return False
    except Exception as exc:
        print(f"\n[UNEXPECTED ERROR] {exc}\n")
        return False


def run_interactive_key_flow() -> None:
    print("\n" + "-" * 50)
    print("OpenAI accounts authenticate via API keys generated in your dashboard.")
    print("You can create or copy your API key from:")
    print("  https://platform.openai.com/api-keys\n")

    prompt_msg = "Enter your OpenAI API Key (sk-...): "
    try:
        if sys.stdin.isatty():
            key = getpass.getpass(prompt=prompt_msg)
        else:
            key = input(prompt_msg)
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return

    key = key.strip()
    if not key:
        print("Empty key provided. Aborting.")
        return
    if key.lower() in ("q", "quit", "exit"):
        print("Cancelled.")
        return

    authenticate_with_key(key)


def run_interactive_flow() -> None:
    print_banner()
    print("Choose an authentication method for your OpenAI account:\n")
    print("  [1] Device Code Flow (Recommended - uses OpenAI account/credits)")
    print("      Generates an 8-character code to confirm at https://auth.openai.com/codex/device")
    print("  [2] OpenAI API Key (sk-...)")
    print("      Enter a key from https://platform.openai.com/api-keys\n")

    try:
        choice = input("Select [1/2] (default 1): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return

    if choice in ("", "1"):
        print("\nStarting OpenAI Codex Device Code flow...")
        try:
            start_openai_device_flow()
        except Exception as exc:
            print(f"\n[ERROR] Device flow error: {exc}\n")
    elif choice == "2":
        run_interactive_key_flow()
    else:
        print("Invalid selection. Aborted.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research Aid OpenAI Account Authentication Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--key",
        type=str,
        help="OpenAI API key (sk-...) to authenticate and store.",
    )
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="Use OPENAI_API_KEY environment variable to authenticate.",
    )
    parser.add_argument(
        "--org",
        type=str,
        default=None,
        help="Optional OpenAI Organization ID (org-...).",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Optional OpenAI Project ID (proj_...).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display current stored credentials status and exit.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear currently saved OpenAI credentials.",
    )
    parser.add_argument(
        "--device-flow",
        action="store_true",
        help="Initiate OpenAI Codex Device Code authorization flow (https://auth.openai.com/codex/device).",
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.clear:
        c1 = clear_oauth_credentials()
        c2_path = get_default_api_key_credentials_path()
        c2 = False
        if c2_path.exists():
            c2_path.unlink()
            c2 = True
        print(f"Cleared credentials: OAuth={c1}, Metadata={c2}")
        return

    if args.device_flow:
        print_banner()
        print("Starting OpenAI Codex Device Code authorization flow...")
        start_openai_device_flow()
        return

    if args.key:
        authenticate_with_key(args.key, organization=args.org, project=args.project)
        return

    if args.from_env:
        env_key = os.getenv("OPENAI_API_KEY")
        if not env_key:
            print("[ERROR] Environment variable OPENAI_API_KEY is not set.")
            sys.exit(1)
        authenticate_with_key(env_key, organization=args.org, project=args.project)
        return

    # Default: Interactive prompt
    run_interactive_flow()


if __name__ == "__main__":
    main()
