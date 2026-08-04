"""I6 — cold outreach never goes through a transactional ESP.

Cold email may leave the platform only via managed cold-email infrastructure
(Smartlead/Instantly) or a factory's own connected mailbox (Gmail / Microsoft
OAuth). A transactional ESP (Amazon SES, Resend, SendGrid, Mailgun, Postmark,
SparkPost) is for *system* mail only and must never appear on the cold-send path.

The invariant was previously carried only by a docstring convention. These are
the automated guards, so a future change that wires a transactional ESP into the
sending path fails CI:

* the registry only ever hands back an approved cold adapter, whatever the keys;
* no module under ``app/providers/sending/`` imports a transactional-ESP SDK.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.config import get_settings
from app.providers.registry import get_mailbox_provider, get_sending_provider

# The only adapters allowed to carry cold outreach.
ALLOWED_SENDING = {"SmartleadSendingProvider", "MockSendingProvider"}
ALLOWED_MAILBOX = {"GmailOAuthProvider", "MicrosoftGraphProvider", "MockMailboxProvider"}

# Import names of transactional-ESP SDKs. SES is reached through boto3/botocore,
# so banning those from the sending package covers Amazon SES too.
TRANSACTIONAL_ESP_MODULES = {
    "boto3",
    "botocore",
    "sendgrid",
    "resend",
    "mailgun",
    "postmark",
    "postmarker",
    "sparkpost",
    "sendinblue",
    "mailjet",
}

SENDING_PKG = Path(__file__).resolve().parents[1] / "app" / "providers" / "sending"


def test_sending_provider_is_never_a_transactional_esp():
    base = get_settings()
    # With a Smartlead key → managed cold infra; without → the deterministic mock.
    # Neither branch (nor any key combination) may yield a transactional ESP.
    for key in ("", "test-smartlead-key"):
        settings = base.model_copy(update={"smartlead_api_key": key})
        provider = get_sending_provider(settings)
        assert type(provider).__name__ in ALLOWED_SENDING, (
            f"cold-send provider {type(provider).__name__!r} is not an approved cold adapter (I6)"
        )


def test_mailbox_provider_is_never_a_transactional_esp():
    base = get_settings()
    creds = {
        "google_oauth_client_id": "id",
        "google_oauth_client_secret": "secret",
        "microsoft_oauth_client_id": "id",
        "microsoft_oauth_client_secret": "secret",
    }
    for provider_type in ("gmail", "microsoft", "unknown"):
        # Both configured (real OAuth adapter) and blank (mock) paths.
        for update in ({}, creds):
            settings = base.model_copy(update=update)
            provider = get_mailbox_provider(provider_type, settings)
            assert type(provider).__name__ in ALLOWED_MAILBOX, (
                f"mailbox provider {type(provider).__name__!r} is not an approved cold adapter (I6)"
            )


def test_no_sending_module_imports_a_transactional_esp_sdk():
    offenders: list[str] = []
    for path in SENDING_PKG.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".", 1)[0]
                if root in TRANSACTIONAL_ESP_MODULES:
                    offenders.append(f"{path.name}: imports {name!r}")
    assert not offenders, "transactional-ESP SDK imported on the cold-send path (I6): " + "; ".join(
        offenders
    )
