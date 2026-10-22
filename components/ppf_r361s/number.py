import esphome.codegen as cg
from esphome.components import number
import esphome.config_validation as cv

from . import CONF_PPF_R361S_ID, PPFR361SComponent, ppf_r361s_ns

DEPENDENCIES = ["ppf_r361s"]

CONF_FEED_PORTIONS = "feed_portions"

PPFR361SManualPortionsNumber = ppf_r361s_ns.class_("PPFR361SManualPortionsNumber", number.Number)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_PPF_R361S_ID): cv.use_id(PPFR361SComponent),
        cv.Optional(CONF_FEED_PORTIONS): number.number_schema(
            PPFR361SManualPortionsNumber,
            icon="mdi:counter",
        ),
    }
)


async def to_code(config):
    hub = await cg.get_variable(config[CONF_PPF_R361S_ID])
    if num_config := config.get(CONF_FEED_PORTIONS):
        num = await number.new_number(
            num_config,
            min_value=1.0,
            max_value=20.0,
            step=1.0,
        )
        await cg.register_parented(num, hub)
        cg.add(hub.set_manual_feed_portions_number(num))
