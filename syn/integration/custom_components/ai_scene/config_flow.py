from homeassistant import config_entries
import voluptuous as vol
from .const import ADDON_DEFAULT_URL, DOMAIN


class AIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            addon_url = user_input.get("addon_url", "").rstrip("/")
            return self.async_create_entry(
                title="AI Scene Planner",
                data={"addon_url": addon_url},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("addon_url", default=ADDON_DEFAULT_URL): str,
                }
            ),
            errors={},
        )
