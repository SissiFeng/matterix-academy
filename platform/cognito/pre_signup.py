"""Cognito admission policy. Email ownership remains Cognito's responsibility."""

import json
import os
import re


def handler(event, context):
    trigger = event.get("triggerSource")
    if trigger == "PreSignUp_AdminCreateUser":
        # IAM-authorized operators may still invite learners from other domains.
        return event
    if trigger != "PreSignUp_SignUp":
        raise ValueError("This registration method is not enabled.")

    domains = json.loads(os.environ.get("SELF_SIGNUP_EMAIL_DOMAINS", "[]"))
    if (
        not isinstance(domains, list)
        or not domains
        or not all(
            isinstance(domain, str)
            and re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}", domain)
            for domain in domains
        )
    ):
        raise ValueError("Self-registration is not configured.")
    email = event.get("request", {}).get("userAttributes", {}).get("email", "")
    if (
        not isinstance(email, str)
        or not re.fullmatch(r"[^\s@]+@[^\s@]+", email)
        or email.rsplit("@", 1)[1].lower() not in domains
    ):
        raise ValueError("Use an eligible university email or ask for a learner invitation.")

    # Never trust client metadata or supplied email_verified to bypass the email challenge.
    event["response"] = {
        "autoConfirmUser": False,
        "autoVerifyEmail": False,
        "autoVerifyPhone": False,
    }
    return event
