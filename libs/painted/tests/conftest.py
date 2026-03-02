"""Root test configuration — registers flags used by test subdirectories."""


def pytest_addoption(parser):
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Regenerate golden files instead of comparing against them",
    )
