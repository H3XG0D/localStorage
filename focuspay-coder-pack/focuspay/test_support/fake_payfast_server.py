"""Process entrypoint for the isolated staging Fake PayFast service."""
from __future__ import annotations

import os

from fake_payfast_http import FakePayFastHttp


def main() -> None:
    FakePayFastHttp(
        api_key=os.environ["FAKE_PAYFAST_API_KEY"],
        secret_key=os.environ["FAKE_PAYFAST_SECRET_KEY"],
    ).serve_forever()


if __name__ == "__main__":
    main()
