#!/usr/bin/env python3
import logging

from adder import Adder

from pyrophone.script import *

MQTT_BROKER = dict(host="127.0.0.1")
CABE_SERVICE = dict(url="https://127.0.0.1:8443/ckap")


@main
def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return (
        mqtt.Source(**MQTT_BROKER, topic="pyrophone-example/S/MARBLE")
        # | PrintBytes()
        # | cabe.Printer()
        | cabe.Decapsulator(service=CABE_SERVICE)
        # | PrintText()
        # | Adder(amount=1, attributeName="hopCount")
        # | PrintBytes()
        # | JQ(expr="{hopCount, shipData: (.shipData | {name, outdoorTemperature})}")
        # | PrintText()
        | cabe.Encapsulator(
            service=CABE_SERVICE, attrs=dict(sensitivity="C", compartment="GESTALT")
        )
        # | cabe.Printer()
        # | PrintBytes()
        | mqtt.Sink(**MQTT_BROKER, topic="pyrophone-example/C/GESTALT")
    )
