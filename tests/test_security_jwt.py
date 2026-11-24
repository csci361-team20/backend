from datetime import timedelta

from app.core.security import (
    EMAIL_VERIFICATION_PURPOSE,
    PASSWORD_RESET_PURPOSE,
    create_access_token,
    create_purpose_token,
    decode_access_payload,
    decode_access_token,
    decode_purpose_token,
    fingerprint,
)


def test_create_and_decode_token_round_trip():
    token = create_access_token(subject="some-user-id")
    assert decode_access_token(token) == "some-user-id"


def test_decode_rejects_garbage_token():
    assert decode_access_token("not-a-real-token") is None


def test_access_token_carries_token_version():
    payload = decode_access_payload(create_access_token("user", token_version=3))
    assert payload is not None
    assert payload["ver"] == 3


def test_purpose_token_round_trip_and_binding():
    token = create_purpose_token(
        "user", PASSWORD_RESET_PURPOSE, timedelta(minutes=5), binding="old-hash"
    )
    assert decode_purpose_token(token, PASSWORD_RESET_PURPOSE) == (
        "user",
        fingerprint("old-hash"),
    )


def test_purpose_tokens_are_not_interchangeable():
    reset = create_purpose_token(
        "user", PASSWORD_RESET_PURPOSE, timedelta(minutes=5), binding="x"
    )
    assert decode_purpose_token(reset, EMAIL_VERIFICATION_PURPOSE) is None
    # A reset token must never work as a sign-in token
    assert decode_access_token(reset) is None
    assert (
        decode_purpose_token(create_access_token("user"), PASSWORD_RESET_PURPOSE)
        is None
    )


def test_expired_purpose_token_is_rejected():
    token = create_purpose_token(
        "user", EMAIL_VERIFICATION_PURPOSE, timedelta(seconds=-1), binding="x"
    )
    assert decode_purpose_token(token, EMAIL_VERIFICATION_PURPOSE) is None
