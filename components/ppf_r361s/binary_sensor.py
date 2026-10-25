import esphome.codegen as cg
from esphome.components import binary_sensor
import esphome.config_validation as cv
from esphome.const import (
    DEVICE_CLASS_CONNECTIVITY,
    DEVICE_CLASS_PLUG,
    DEVICE_CLASS_PROBLEM,
    ENTITY_CATEGORY_DIAGNOSTIC,
)

from . import CONF_PPF_R361S_ID, PPFR361SComponent

DEPENDENCIES = ["ppf_r361s"]

CONF_POWER_ADAPTER = "power_adapter"
CONF_FOOD_LOW = "food_low"
CONF_MOTOR_JAMMED = "motor_jammed"
CONF_BOWL_CONNECTED = "bowl_connected"
CONF_BATTERY_INSTALLED = "battery_installed"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_PPF_R361S_ID): cv.use_id(PPFR361SComponent),
        cv.Optional(CONF_POWER_ADAPTER): binary_sensor.binary_sensor_schema(
            device_class=DEVICE_CLASS_PLUG,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
            icon="mdi:power-plug",
        ),
        cv.Optional(CONF_FOOD_LOW): binary_sensor.binary_sensor_schema(
            device_class=DEVICE_CLASS_PROBLEM,
            icon="mdi:tray-alert",
        ),
        cv.Optional(CONF_MOTOR_JAMMED): binary_sensor.binary_sensor_schema(
            device_class=DEVICE_CLASS_PROBLEM,
            icon="mdi:alert-octagon",
        ),
        cv.Optional(CONF_BOWL_CONNECTED): binary_sensor.binary_sensor_schema(
            device_class=DEVICE_CLASS_CONNECTIVITY,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
            icon="mdi:tray",
        ),
        cv.Optional(CONF_BATTERY_INSTALLED): binary_sensor.binary_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
            icon="mdi:battery-alert",
        ),
    }
)


async def to_code(config):
    hub = await cg.get_variable(config[CONF_PPF_R361S_ID])
    if power_adapter_config := config.get(CONF_POWER_ADAPTER):
        sens = await binary_sensor.new_binary_sensor(power_adapter_config)
        cg.add(hub.set_power_adapter_sensor(sens))
    if food_low_config := config.get(CONF_FOOD_LOW):
        sens = await binary_sensor.new_binary_sensor(food_low_config)
        cg.add(hub.set_food_low_sensor(sens))
    if motor_jammed_config := config.get(CONF_MOTOR_JAMMED):
        sens = await binary_sensor.new_binary_sensor(motor_jammed_config)
        cg.add(hub.set_motor_jammed_sensor(sens))
    if bowl_connected_config := config.get(CONF_BOWL_CONNECTED):
        sens = await binary_sensor.new_binary_sensor(bowl_connected_config)
        cg.add(hub.set_bowl_connected_sensor(sens))
    if battery_installed_config := config.get(CONF_BATTERY_INSTALLED):
        sens = await binary_sensor.new_binary_sensor(battery_installed_config)
        cg.add(hub.set_battery_installed_sensor(sens))
