# Pyrophone — Project Vision

## Elevator Pitch

Pyrophone is a Python-based DSL programming environment for building message
routing flows with a minimal amount of code. It is intended to allow anyone, at
any skill level, to build flows which consume and produce messages from and to
common message sources and sinks and via common protocols, such as MQTT, AMQP,
ZeroMQ, HTTP/REST, WebSockets, XMPP, etc.

Consider the following program:

```python
import pyrophone, pyrophone.mqtt, pyrophone.cabe

with pyrophone.builder() as b:

@pyrophone.main()
def main(pyro):
  source              = pyrophone.mqtt.source(name='in')
  dec_filter          = pyrophone.cabe.decapsulator()
  json_filter         = pyrophone.json.query('.general')
  enc_filter          = pyrophone.cabe.encapsulator(attributes=dict(
                          sensitivity='S', compartment='GESTALT',
                        ))
  sink                = pyrophone.mqtt.sink(name='out')

  pyro(source | dec_filter | enc_filter | sink)
```

```yaml
!pyrophone/graph

graph_nodes:
  - id: n0
    type: pyrophone.mqtt.source
    name: in
  - id: n1
    type: pyrophone.cabe.decapsulator
  - id: n2
    type: pyrophone.json.query
    args:
      query: .general
  - id: n3
    type: pyrophone.cabe.encapsulator
    args:
      attributes:
        sensitivity: S
        compartment: GESTALT
  - id: n4
    type: pyrophone.mqtt.sink
    name: out
graph_edges:
  - from: n0
    to: n1
  - from: n1
    to: n2
  - from: n2
    to: n3
  - from: n3
    to: n4
```

```shell
$ pyrophone ./graph.yaml
$ pyrophone ./graph.py
$ python3 ./graph.py # equivalent

$ pyrophone --config graph-config.yaml ./graph.py

# graph built automatically and used to autogen CLI config args for e.g. MQTT connection params
$ pyrophone --in-host HOSTNAME:PORT --in-user USER --in-password FOO --in-topic FOO ./graph.py
```
