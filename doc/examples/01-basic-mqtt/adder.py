"""The JSON transform used by the MQTT demo."""

import math

from pyrophone import Property, node_type
from pyrophone.nodes import JSONTransform, JSONValue


@node_type
class Adder(JSONTransform):
    """Add to a named numeric attribute, preserving other JSON properties."""

    amount = Property[int](
        default=1, description="Amount to add to the attribute.", step=1
    )
    attributeName = Property[str](
        default="value",
        description="Name of the top-level JSON attribute to increment.",
    )

    async def transform_json(self, value: JSONValue) -> JSONValue:
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        number = value.get(self.attributeName)
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or (isinstance(number, float) and not math.isfinite(number))
        ):
            raise ValueError(
                f"JSON object must have a finite numeric {self.attributeName!r} field"
            )
        return {**value, self.attributeName: number + self.amount}
