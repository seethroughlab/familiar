#!/usr/bin/env bash
#
# Make this repo's self-hosted macOS Actions runner able to reach the login keychain.
#
# Run after installing or reinstalling the runner: `svc.sh install` writes
# `SessionCreate = true` into the LaunchAgent every time, and that one key is what
# breaks `macOS Compose Integration`.
#
#   ./scripts/fix-macos-runner-session.sh                 # this repo's runner
#   ./scripts/fix-macos-runner-session.sh <label> [...]   # named runners
#
# ## Why
#
# `SessionCreate = true` tells launchd to put the runner in its **own security
# session**, separate from the GUI login session. `securityd` will not release a
# keychain item to a session that cannot present a prompt, so Docker Desktop's
# credential service — which resolves registry auth during a build, and which ignores
# `DOCKER_CONFIG` entirely — fails with:
#
#     error getting credentials - err: exit status 1, out: `keychain cannot be accessed
#     because the current session does not allow user interaction. The keychain may be
#     locked; unlock it by running "security -v unlock-keychain ..." and try again`
#
# That message misleads twice. The keychain is **not locked** — `security
# show-keychain-info ~/Library/Keychains/login.keychain-db` reports `no-timeout` — and
# unlocking it would not help, because the problem is the session rather than the lock.
# Removing the key is the fix; there is nothing to unlock.
#
# See `.github/workflows/ci.yml` (macos-compose-integration) for the full history,
# including the second, independent bug this one was hiding.
#
# **Scoped on purpose.** This machine hosts runners for more than one project, and a
# script in this repository has no business reconfiguring somebody else's. Defaults to
# `actions.runner.seethroughlab.*`; pass labels explicitly to go wider.
#
# Idempotent: safe to run repeatedly, and does nothing if the key is already absent.

set -euo pipefail

AGENTS="$HOME/Library/LaunchAgents"
DEFAULT_PREFIX="actions.runner.seethroughlab."

shopt -s nullglob

if [ $# -gt 0 ]; then
    plists=()
    for label in "$@"; do
        candidate="$AGENTS/${label%.plist}.plist"
        if [ -f "$candidate" ]; then
            plists+=("$candidate")
        else
            echo "error   no LaunchAgent at $candidate" >&2
            exit 1
        fi
    done
else
    plists=("$AGENTS/$DEFAULT_PREFIX"*.plist)
fi

if [ ${#plists[@]} -eq 0 ]; then
    echo "No runner LaunchAgents matching '${DEFAULT_PREFIX}*' under $AGENTS."
    echo "Nothing to do — is the runner installed as a service?"
    exit 0
fi

# Reload an agent, waiting for the unload to land before bootstrapping.
#
# **`bootout` returns before the job is gone**, so bootstrapping immediately after it
# races and can fail — leaving the runner unloaded and the machine quietly short one
# runner. Learned the hard way: the first version of this script did exactly that.
reload() {
    local label="$1" plist="$2" domain="gui/$(id -u)"

    launchctl bootout "$domain/$label" 2>/dev/null || true
    for _ in $(seq 1 50); do
        launchctl print "$domain/$label" >/dev/null 2>&1 || break
        sleep 0.2
    done

    launchctl bootstrap "$domain" "$plist"

    for _ in $(seq 1 50); do
        if launchctl print "$domain/$label" 2>/dev/null | grep -q "state = running"; then
            echo "        $label is running in $domain"
            return 0
        fi
        sleep 0.2
    done

    echo "error   $label did not come back up. Restore with:" >&2
    echo "          launchctl bootstrap $domain $plist" >&2
    return 1
}

changed=0

for plist in "${plists[@]}"; do
    label=$(basename "$plist" .plist)

    if ! plutil -extract SessionCreate raw "$plist" >/dev/null 2>&1; then
        echo "ok      $label — no SessionCreate key"
        continue
    fi

    value=$(plutil -extract SessionCreate raw "$plist")
    if [ "$value" != "true" ]; then
        echo "ok      $label — SessionCreate is $value"
        continue
    fi

    echo "fixing  $label — removing SessionCreate"
    cp "$plist" "$plist.bak.$(date +%Y%m%d%H%M%S)"
    plutil -remove SessionCreate "$plist"
    reload "$label" "$plist"
    changed=1
done

if [ "$changed" -eq 0 ]; then
    echo
    echo "Nothing needed changing."
fi
