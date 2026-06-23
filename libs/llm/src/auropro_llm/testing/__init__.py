"""Conformance kit for LLMGateway adapters.

Any adapter claiming to implement the `LLMGateway` port must pass
`GatewayContractTests` — subclass it in your test suite and implement
`make_gateway()`. See README "Certifying an adapter".

pytest is required only here: install with `auropro-llm[testing]`.
"""

from auropro_llm.testing.conformance import GatewayCapabilities, GatewayContractTests

__all__ = ["GatewayCapabilities", "GatewayContractTests"]
