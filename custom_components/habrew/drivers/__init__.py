"""Platform drivers for HA-Brew.

Everything under this package is plain asyncio/stdlib (+ ``cryptography``) and must not
import Home Assistant, so the drivers can be reused from a CLI or an add-on later.
"""
