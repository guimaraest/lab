import subprocess


GLUETUN_CONNECTIVITY_COMMAND = [
    "docker",
    "run",
    "--rm",
    "--network=container:gluetun",
    "alpine:3.18",
    "sh",
    "-c",
    "apk add wget && wget -qO- https://ipinfo.io",
]
CONTAINER_CONNECTIVITY_COMMANDS = {
    name: ["docker", "exec", name, "wget", "-qO-", "https://ipinfo.io"]
    for name in ("nzbget", "qbittorrent", "prowlarr")
}


def test_gluetun_connectivity():
    commands = [("gluetun", GLUETUN_CONNECTIVITY_COMMAND)]
    commands.extend(CONTAINER_CONNECTIVITY_COMMANDS.items())
    results = []
    passed = True

    for target, command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            passed = False
            results.append(f"{target}: connectivity check could not complete: {error}")
            continue

        if result.returncode != 0:
            passed = False
            details = result.stderr.strip() or result.stdout.strip() or "no command output"
            results.append(
                f"{target}: connectivity check failed (exit {result.returncode}): {details}"
            )
            continue

        response = result.stdout.strip()
        if not response:
            passed = False
            results.append(f"{target}: connectivity check returned an empty response")
            continue

        results.append(f"{target}: {response}")

    return passed, "\n".join(results)


TESTS = {
    "gluetun-connectivity": test_gluetun_connectivity,
}
