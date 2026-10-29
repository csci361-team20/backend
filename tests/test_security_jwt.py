from app.core.security import create_access_token, decode_access_token


def test_create_and_decode_token_round_trip():
    token = create_access_token(subject="some-user-id")
    assert decode_access_token(token) == "some-user-id"


def test_decode_rejects_garbage_token():
    assert decode_access_token("not-a-real-token") is None
