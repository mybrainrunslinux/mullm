"""TLS configuration applied to the context actually used by Uvicorn."""
import ssl


def tls_context_factory(config, default_factory):
    context = default_factory()
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    return context


def tls_options(certfile, keyfile, *, mtls=False, ca_certs=None):
    if mtls and not ca_certs:
        raise ValueError("mTLS requires a configured client CA certificate")
    return {
        "ssl_certfile": certfile,
        "ssl_keyfile": keyfile,
        "ssl_version": ssl.PROTOCOL_TLS_SERVER,
        "ssl_ciphers": None,  # Preserve Python/OpenSSL's secure defaults.
        "ssl_cert_reqs": ssl.CERT_REQUIRED if mtls else ssl.CERT_NONE,
        "ssl_ca_certs": ca_certs if mtls else None,
        "ssl_context_factory": tls_context_factory,
    }
