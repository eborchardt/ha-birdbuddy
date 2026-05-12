"""Test the Bird Buddy config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

from birdbuddy.exceptions import AuthenticationFailedError, NoResponseError
from birdbuddy.user import BirdBuddyUser
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.birdbuddy.const import (
    AUTH_METHOD_EMAIL,
    AUTH_METHOD_GOOGLE,
    CONF_AUTH_METHOD,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)


def _user_payload(name: str = "Test User", email: str = "test@email.com") -> BirdBuddyUser:
    return BirdBuddyUser(
        {
            "id": "u1",
            "name": name,
            "avatarUrl": "",
            "email": email,
            "signInType": "EMAIL",
        }
    )


def _mock_client(
    *,
    refresh_result: bool | type[Exception] = True,
    user: BirdBuddyUser | None = None,
    refresh_token: str | None = None,
) -> MagicMock:
    """Build a MagicMock that stands in for a BirdBuddy instance.

    Patch BirdBuddy itself (the class), not its methods — patching only methods
    still triggers the real __init__ which constructs a GraphqlClient and trips
    pytest-socket.
    """
    client = MagicMock()
    if isinstance(refresh_result, type) and issubclass(refresh_result, Exception):
        client.refresh = AsyncMock(side_effect=refresh_result)
    else:
        client.refresh = AsyncMock(return_value=refresh_result)
    client.user = user if user is not None else _user_payload()
    client.refresh_token = refresh_token
    return client


async def _start_flow(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_menu_shown_at_start(hass: HomeAssistant) -> None:
    """Initial step is a menu with email and google options."""
    result = await _start_flow(hass)
    assert result["type"] == FlowResultType.MENU
    assert set(result["menu_options"]) == {"email", "google"}


async def test_email_happy_path(hass: HomeAssistant) -> None:
    """Selecting email and filling the form creates an entry with CONF_AUTH_METHOD=email."""
    init = await _start_flow(hass)
    pick = await hass.config_entries.flow.async_configure(
        init["flow_id"], {"next_step_id": "email"}
    )
    assert pick["type"] == FlowResultType.FORM
    assert pick["step_id"] == "email"

    client = _mock_client()
    with patch(
        "custom_components.birdbuddy.config_flow.BirdBuddy", return_value=client
    ), patch(
        "custom_components.birdbuddy.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            pick["flow_id"],
            {"email": "test@email.com", "password": "test-password"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test User"
    assert result["data"] == {
        CONF_AUTH_METHOD: AUTH_METHOD_EMAIL,
        "email": "test@email.com",
        "password": "test-password",
    }
    assert len(mock_setup_entry.mock_calls) == 1


async def test_email_invalid_auth(hass: HomeAssistant) -> None:
    """AuthenticationFailedError surfaces as invalid_auth in the email step."""
    init = await _start_flow(hass)
    pick = await hass.config_entries.flow.async_configure(
        init["flow_id"], {"next_step_id": "email"}
    )

    client = _mock_client(refresh_result=AuthenticationFailedError)
    with patch(
        "custom_components.birdbuddy.config_flow.BirdBuddy", return_value=client
    ):
        result = await hass.config_entries.flow.async_configure(
            pick["flow_id"],
            {"email": "test@email.com", "password": "test-password"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_email_cannot_connect(hass: HomeAssistant) -> None:
    """Any other exception during email refresh surfaces as cannot_connect."""
    init = await _start_flow(hass)
    pick = await hass.config_entries.flow.async_configure(
        init["flow_id"], {"next_step_id": "email"}
    )

    client = _mock_client(refresh_result=NoResponseError)
    with patch(
        "custom_components.birdbuddy.config_flow.BirdBuddy", return_value=client
    ):
        result = await hass.config_entries.flow.async_configure(
            pick["flow_id"],
            {"email": "test@email.com", "password": "test-password"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_google_happy_path(hass: HomeAssistant) -> None:
    """Pasting a Google token saves CONF_AUTH_METHOD=google + CONF_REFRESH_TOKEN."""
    init = await _start_flow(hass)
    pick = await hass.config_entries.flow.async_configure(
        init["flow_id"], {"next_step_id": "google"}
    )
    assert pick["type"] == FlowResultType.FORM
    assert pick["step_id"] == "google"

    client = _mock_client(refresh_token="captured-bb-refresh-token")
    with patch(
        "custom_components.birdbuddy.config_flow.BirdBuddy", return_value=client
    ) as mock_cls, patch(
        "custom_components.birdbuddy.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            pick["flow_id"],
            {"google_token": "captured-google-token"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test User"
    assert result["data"] == {
        CONF_AUTH_METHOD: AUTH_METHOD_GOOGLE,
        CONF_REFRESH_TOKEN: "captured-bb-refresh-token",
        "email": "test@email.com",
    }
    assert "google_token" not in result["data"]
    # Constructor was called with the pasted Google token.
    mock_cls.assert_called_once_with(google_token="captured-google-token")
    assert len(mock_setup_entry.mock_calls) == 1


async def test_google_invalid_auth(hass: HomeAssistant) -> None:
    """A rejected Google token surfaces as invalid_auth."""
    init = await _start_flow(hass)
    pick = await hass.config_entries.flow.async_configure(
        init["flow_id"], {"next_step_id": "google"}
    )

    client = _mock_client(refresh_result=AuthenticationFailedError)
    with patch(
        "custom_components.birdbuddy.config_flow.BirdBuddy", return_value=client
    ):
        result = await hass.config_entries.flow.async_configure(
            pick["flow_id"],
            {"google_token": "bad-token"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_google_cannot_connect(hass: HomeAssistant) -> None:
    """Network errors during Google validation surface as cannot_connect."""
    init = await _start_flow(hass)
    pick = await hass.config_entries.flow.async_configure(
        init["flow_id"], {"next_step_id": "google"}
    )

    client = _mock_client(refresh_result=NoResponseError)
    with patch(
        "custom_components.birdbuddy.config_flow.BirdBuddy", return_value=client
    ):
        result = await hass.config_entries.flow.async_configure(
            pick["flow_id"],
            {"google_token": "some-token"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_email_updates_existing_entry(hass: HomeAssistant) -> None:
    """Reauth for an email entry re-prompts for password and updates the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test@email.com",
        data={
            CONF_AUTH_METHOD: AUTH_METHOD_EMAIL,
            "email": "test@email.com",
            "password": "old-password",
        },
    )
    entry.add_to_hass(hass)

    init = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=entry.data,
    )
    assert init["step_id"] == "email"

    client = _mock_client()
    with patch(
        "custom_components.birdbuddy.config_flow.BirdBuddy", return_value=client
    ), patch(
        "custom_components.birdbuddy.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            init["flow_id"],
            {"email": "test@email.com", "password": "new-password"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-password"
    assert entry.data[CONF_AUTH_METHOD] == AUTH_METHOD_EMAIL


async def test_reauth_google_updates_refresh_token(hass: HomeAssistant) -> None:
    """Reauth for a Google entry re-prompts for a fresh token and updates CONF_REFRESH_TOKEN."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test@email.com",
        data={
            CONF_AUTH_METHOD: AUTH_METHOD_GOOGLE,
            CONF_REFRESH_TOKEN: "stale-refresh-token",
            "email": "test@email.com",
        },
    )
    entry.add_to_hass(hass)

    init = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=entry.data,
    )
    assert init["step_id"] == "google"

    client = _mock_client(refresh_token="fresh-refresh-token")
    with patch(
        "custom_components.birdbuddy.config_flow.BirdBuddy", return_value=client
    ), patch(
        "custom_components.birdbuddy.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            init["flow_id"],
            {"google_token": "freshly-captured-google-token"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "fresh-refresh-token"
    assert entry.data[CONF_AUTH_METHOD] == AUTH_METHOD_GOOGLE
