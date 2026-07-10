# Reasonix project memory

Notes the user pinned via the `#` prompt prefix. The whole file is
loaded into the immutable system prefix every session — keep it terse.

- Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes
automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

# 空调虚拟传感器和开关
input_boolean:
  ac_power:
    name: "空调电源"
    icon: mdi:air-conditioner
input_number:
  ac_temperature:
    name: "空调温度"
    min: 16
    max: 30
    step: 1
    unit_of_measurement: "°C"
input_select:
  ac_mode:
    name: "空调模式"
    options:
      - "制冷"
      - "制热"
      - "送风"
      - "除湿"
    icon: mdi:cog
  ac_fan_speed:
    name: "风速"
    options:
      - "自动"
      - "低速"
      - "中速"
      - "高速"
    icon: mdi:fan是在这里加日志吗
- Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes
automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

# 空调虚拟传感器和开关
input_boolean:
  ac_power:
    name: "空调电源"
    icon: mdi:air-conditioner
input_number:
  ac_temperature:
    name: "空调温度"
    min: 16
    max: 30
    step: 1
    unit_of_measurement: "°C"
input_select:
  ac_mode:
    name: "空调模式"
    options:
      - "制冷"
      - "制热"
      - "送风"
      - "除湿"
    icon: mdi:cog
  ac_fan_speed:
    name: "风速"
    options:
      - "自动"
      - "低速"
      - "中速"
      - "高速"
    icon: mdi:fan 是这里加日志吗
