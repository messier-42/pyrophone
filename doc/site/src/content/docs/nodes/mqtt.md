---
title: MQTT
description: The MQTT node types.
sidebar:
  order: 15
---

:::note
This node type requires the `mqtt` optional dependencies to be installed:

```shell
$ python3 -m pip install 'Pyrophone[mqtt]'
```

You can still construct and define MQTT nodes without installing the dependencies, but execution will not be possible.
:::

### Description

The `mqtt.Source` and `mqtt.Sink` node types provide source and sink nodes which receive published messages from an MQTT topic and publish messages to an MQTT topic respectively.

### Properties

The `mqtt.Source` and `mqtt.Sink` node types expect the following properties:

- `host`: Required. String. Hostname to connect to. Defaults to `127.0.0.1`.

- `port`: Required. Integer. Port to connect to. Defaults to the standard MQTT port, 1883.

- `username`: Optional. String. Connection username. Defaults to environment variable `MQTT_USERNAME` if not specified.

- `password`: Optional. String. Connection password. Defaults to environment variable `MQTT_PASSWORD` if not specified.

- `topic`: Required. String. The MQTT topic to subscribe to or publish on.

- `qos`: Required. Integer. Defaults to 1. The MQTT QoS level to use.

### Usage

```python
from pyrophone.script import *

MQTT_ARGS = dict(host='127.0.0.1')

@main
def graph():
    return (
        mqtt.Source(**MQTT_ARGS) |
        ... |
        mqtt.Sink(**MQTT_ARGS)
    )
```