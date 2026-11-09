import sys


def main() -> None:
    import uvicorn

    # Add the application path only after Uvicorn and its stdlib dependencies load.
    # The backend contains operator.py, which must not shadow stdlib operator.
    sys.path.insert(0, "/app/backend")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        server_header=False,
        limit_concurrency=100,
    )


if __name__ == "__main__":
    main()
