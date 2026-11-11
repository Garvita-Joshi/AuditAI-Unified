"""Sandbox-only PayPal adapter. Secrets and provider requests stay server-side."""
import os
import requests
from fastapi import HTTPException

BASE = "https://api-m.sandbox.paypal.com"


def configuration():
    return {"client_id":os.getenv("PAYPAL_SANDBOX_CLIENT_ID", ""),
            "secret":os.getenv("PAYPAL_SANDBOX_CLIENT_SECRET", ""),
            "merchant_id":os.getenv("PAYPAL_SANDBOX_MERCHANT_ID", "")}


def configured():
    return all(configuration().values())


def call(method, path, payload=None, request_id=None):
    config = configuration()
    if not configured():
        raise HTTPException(503, "PayPal sandbox is not configured. No payment was attempted.")
    try:
        token = requests.post(BASE + "/v1/oauth2/token", auth=(config["client_id"], config["secret"]),
                              data={"grant_type":"client_credentials"}, timeout=15)
        token.raise_for_status()
        headers = {"Authorization":"Bearer " + token.json()["access_token"], "Content-Type":"application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        result = requests.request(method, BASE + path, headers=headers, json=payload, timeout=20)
        result.raise_for_status()
        return result.json()
    except (requests.RequestException, ValueError, KeyError):
        raise HTTPException(502, "PayPal could not confirm the operation. Check payment status before retrying.")
