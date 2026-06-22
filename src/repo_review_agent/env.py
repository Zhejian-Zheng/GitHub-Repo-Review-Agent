"""Load environment variables from a local ``.env`` file at startup.

The application reads configuration (API keys, Supabase credentials, deployment
controls) straight from :data:`os.environ`. Entry points call
:func:`load_local_env` so a project-level ``.env`` is picked up automatically,
which means contributors can keep secrets such as ``OPENAI_API_KEY`` in ``.env``
instead of exporting them in every shell.

Real, already-exported environment variables always win over ``.env`` values, so
this never overrides values set by a deployment platform.
"""

from __future__ import annotations


def load_local_env() -> bool:
    """Load ``.env`` into the process environment if python-dotenv is available.

    Returns ``True`` when a dotenv loader ran, ``False`` when the optional
    dependency is missing. Missing the dependency is not an error: exported
    environment variables still work.
    """

    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return False

    load_dotenv(find_dotenv(usecwd=True), override=False)
    return True
