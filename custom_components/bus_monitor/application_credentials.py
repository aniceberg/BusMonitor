"""OAuth for Bouncie: each parent registers their own app at bouncie.dev and enters it here."""

from __future__ import annotations

from typing import cast

from aiohttp import ClientError, ClientResponseError
from homeassistant.components.application_credentials import (
    AuthImplementation,
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .providers.bouncie import AUTHORIZE_URL, TOKEN_URL


class BouncieOAuth2Implementation(AuthImplementation):
    """Bouncie's token endpoint takes a JSON body, not the form Home Assistant sends."""

    async def _token_request(self, data: dict) -> dict:
        data = {**data, "client_id": self.client_id, "client_secret": self.client_secret}
        session = async_get_clientsession(self.hass)
        try:
            resp = await session.post(self.token_url, json=data)
            resp.raise_for_status()
            return cast(dict, await resp.json(content_type=None))
        except (ClientResponseError, ClientError) as err:
            # Same mapping as Home Assistant's own: 4xx -> reauth, 429/5xx -> retry.
            config_entry_oauth2_flow._raise_mapped_token_error(err, self.service_domain)


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    return {
        "developer_portal_url": "https://www.bouncie.dev",
        "redirect_url": "https://my.home-assistant.io/redirect/oauth",
    }


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    return AuthorizationServer(authorize_url=AUTHORIZE_URL, token_url=TOKEN_URL)


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    return BouncieOAuth2Implementation(
        hass, auth_domain, credential, await async_get_authorization_server(hass)
    )
