"""
Property-based tests for Chrome launch command correctness.

Uses Hypothesis to verify that _build_chrome_command() always produces
a command list with the correct flags, port, user-data-dir, and never
references the user's default Chrome profile.

Properties tested:
- Property 14: Chrome Launch Command Correctness
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.integrations.chrome_launcher import _build_chrome_command


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid port numbers (unprivileged range)
port_strategy = st.integers(min_value=1024, max_value=65535)

# Random directory paths — mix of Unix-style and Windows-style paths
# that are plausible automation profile directories
unix_path_segments = st.lists(
    st.text(
        alphabet=st.characters(categories=("L", "N"), whitelist_characters="-_"),
        min_size=1,
        max_size=20,
    ).filter(lambda s: s.strip()),
    min_size=1,
    max_size=5,
)

unix_dir_strategy = unix_path_segments.map(lambda parts: "/tmp/" + "/".join(parts))

windows_dir_strategy = unix_path_segments.map(
    lambda parts: "C:\\Users\\TestUser\\AppData\\" + "\\".join(parts)
)

user_data_dir_strategy = st.one_of(unix_dir_strategy, windows_dir_strategy)

# Chrome binary paths
chrome_binary_strategy = st.sampled_from([
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
])

# Default profile paths that must NEVER appear in the command
DEFAULT_PROFILE_PATHS = [
    "~/.config/google-chrome",
    "%LOCALAPPDATA%\\Google\\Chrome\\User Data",
    ".config/google-chrome",
    "Google/Chrome/User Data",
]


# ---------------------------------------------------------------------------
# Property 14: Chrome Launch Command Correctness
# ---------------------------------------------------------------------------


@given(
    chrome_binary=chrome_binary_strategy,
    port=port_strategy,
    user_data_dir=user_data_dir_strategy,
)
@settings(max_examples=200)
def test_chrome_command_includes_remote_debugging_port(
    chrome_binary: str,
    port: int,
    user_data_dir: str,
) -> None:
    """
    For any valid port number and user-data-dir path, the Chrome launch command
    SHALL always include --remote-debugging-port={port} with the exact port number.

    **Validates: Requirements 5.3, 5.4, 5.8**
    """
    cmd = _build_chrome_command(chrome_binary, port, user_data_dir)

    expected_flag = f"--remote-debugging-port={port}"
    assert expected_flag in cmd, (
        f"Command missing --remote-debugging-port={port}. "
        f"Got: {cmd}"
    )


@given(
    chrome_binary=chrome_binary_strategy,
    port=port_strategy,
    user_data_dir=user_data_dir_strategy,
)
@settings(max_examples=200)
def test_chrome_command_includes_user_data_dir(
    chrome_binary: str,
    port: int,
    user_data_dir: str,
) -> None:
    """
    For any valid port number and user-data-dir path, the Chrome launch command
    SHALL always include --user-data-dir={path} with the exact path.

    **Validates: Requirements 5.3, 5.4, 5.8**
    """
    cmd = _build_chrome_command(chrome_binary, port, user_data_dir)

    expected_flag = f"--user-data-dir={user_data_dir}"
    assert expected_flag in cmd, (
        f"Command missing --user-data-dir={user_data_dir}. "
        f"Got: {cmd}"
    )


@given(
    chrome_binary=chrome_binary_strategy,
    port=port_strategy,
    user_data_dir=user_data_dir_strategy,
)
@settings(max_examples=200)
def test_chrome_command_includes_no_first_run(
    chrome_binary: str,
    port: int,
    user_data_dir: str,
) -> None:
    """
    For any valid port number and user-data-dir path, the Chrome launch command
    SHALL always include --no-first-run.

    **Validates: Requirements 5.3, 5.4, 5.8**
    """
    cmd = _build_chrome_command(chrome_binary, port, user_data_dir)

    assert "--no-first-run" in cmd, (
        f"Command missing --no-first-run flag. Got: {cmd}"
    )


@given(
    chrome_binary=chrome_binary_strategy,
    port=port_strategy,
    user_data_dir=user_data_dir_strategy,
)
@settings(max_examples=200)
def test_chrome_command_never_includes_default_profile_path(
    chrome_binary: str,
    port: int,
    user_data_dir: str,
) -> None:
    """
    For any valid port number and user-data-dir path, the Chrome launch command
    SHALL never include the user's default Chrome profile path (no
    ~/.config/google-chrome, no %LOCALAPPDATA%\\Google\\Chrome\\User Data).

    **Validates: Requirements 5.3, 5.4, 5.8**
    """
    cmd = _build_chrome_command(chrome_binary, port, user_data_dir)
    cmd_joined = " ".join(cmd)

    for default_path in DEFAULT_PROFILE_PATHS:
        assert default_path not in cmd_joined, (
            f"Command contains default Chrome profile path '{default_path}'. "
            f"Automation must use a dedicated user-data-dir. Got: {cmd}"
        )


@given(
    chrome_binary=chrome_binary_strategy,
    port=port_strategy,
    user_data_dir=user_data_dir_strategy,
)
@settings(max_examples=200)
def test_chrome_command_first_element_is_binary(
    chrome_binary: str,
    port: int,
    user_data_dir: str,
) -> None:
    """
    For any valid port number and user-data-dir path, the first element of the
    Chrome launch command SHALL always be the chrome binary path.

    **Validates: Requirements 5.3, 5.4, 5.8**
    """
    cmd = _build_chrome_command(chrome_binary, port, user_data_dir)

    assert len(cmd) > 0, "Command list must not be empty"
    assert cmd[0] == chrome_binary, (
        f"First element should be the chrome binary '{chrome_binary}', "
        f"but got '{cmd[0]}'. Full command: {cmd}"
    )
