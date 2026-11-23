---
title: CABE
description: The CABE node types.
sidebar:
  order: 20
---

:::note
This node type requires the `cabe` optional dependencies to be installed:

```shell
$ python3 -m pip install 'Pyrophone[cabe]'
```

You can still construct and define CABE nodes without installing the dependencies, but execution will not be possible.
:::

### Description

The `cabe.Encapsulator` and `cabe.Decapsulator` node types are transform-style node types operating over bytestrings which apply CABE encapsulation and decapsulation transforms on input data, applying or removing [CABE](https://cabespec.org/) cryptographic protection accordingly.

The `cabe.Printer` node type is a transform-style node type which prints the headers of an encrypted CABE Envelope for diagnostic purposes without modifying it. The unmodified CABE Envelope is passed through as-is.

### Properties

The `cabe.Encapsulator` and `cabe.Decapsulator` node types require a `service` property to be configured, providing details of how to access a CABE Key Service.

The `service` property is a dictionary which supports the following options:

- `url`: Required. The `https` URL to the CABE Key Service.

-  `tls`: Optional. A dictionary which may specify zero or more of the following options:

  - `cert_file`: Optional. A file containing a client certificate to use to authenticate using mTLS. If not specified, defaults to the file specified in the `CABE_CERTIFICATE_FILE` environment variable.

  - `key_file`: Optional. A file containing the corresponding key for the client certificate. If not specified, defaults to the file specified in the `CABE_KEY_FILE` environment variable.

  - `ca_file`: Optional. A file which can be used to override the CA trust anchor list when connecting to the key service. If not specified, the `CABE_CA_FILE` environment variable is also checked.

### Usage

```python
from pyrophone.script import *

CABE_SERVICE = dict(url='https://cabe-key-service/ckap')

@main
def graph():
    return (
        ... |
        cabe.Printer() |
        cabe.Decapsulator(service=CABE_SERVICE) |
        ...
        cabe.Encapsulator(service=CABE_SERVICE,
                          attrs=dict(foo='bar')) |
        cabe.Printer() |
        ...
    )
```