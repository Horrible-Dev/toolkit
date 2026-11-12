#!/bin/sh
# Posts one embed to a Discord webhook. Everything comes from the environment:
#   WEBHOOK      the webhook URL; empty: nothing is posted
#   KIND         release, issue or custom; release and issue read the event
#                file (GITHUB_EVENT_PATH) for the title, link and text
#   TITLE, URL, DESCRIPTION, COLOR   override what the event gives
#   PING_ROLE    a role ID to mention (only that role)
#   EVERYONE     true to mention @everyone; otherwise no mentions at all
# Rate limits (HTTP 429) and server errors are retried a few times; still
# failing, that's a warning, not a failed run. Any other answer (a deleted
# webhook, a bad request) fails.
set -eu

if [ -z "${WEBHOOK:-}" ]; then
	echo "No webhook given: nothing to post."
	exit 0
fi

KIND=${KIND:-custom}
event=${GITHUB_EVENT_PATH:-}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

from_event() {
	if [ -n "$event" ] && [ -f "$event" ]; then
		jq -r "$1 // \"\"" "$event"
	fi
}

case "$KIND" in
release)
	repo=$(from_event '.repository.name')
	tag=$(from_event '.release.tag_name')
	name=$(from_event '.release.name')
	default_title="$repo ${name:-$tag}"
	default_url=$(from_event '.release.html_url')
	default_description=$(from_event '.release.body')
	;;
issue)
	number=$(from_event '.issue.number')
	default_title="#$number $(from_event '.issue.title')"
	default_url=$(from_event '.issue.html_url')
	default_description=$(from_event '.issue.body')
	;;
custom)
	default_title="" default_url="" default_description=""
	;;
*)
	echo "::error::kind must be release, issue or custom, not '$KIND'"
	exit 1
	;;
esac

title=${TITLE:-$default_title}
url=${URL:-$default_url}
description=${DESCRIPTION:-$default_description}
if [ -z "$title" ] && [ -z "$description" ]; then
	echo "::error::Nothing to post: give a title or a description"
	exit 1
fi

jq -n \
	--arg title "$title" \
	--arg url "$url" \
	--arg description "$description" \
	--arg color "${COLOR:-5793266}" \
	--arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	--arg ping "${PING_ROLE:-}" \
	--arg everyone "${EVERYONE:-false}" \
	'def cut($n): if length > $n then .[0:$n - 1] + "…" else . end;
	{embeds: [{title: ($title | cut(256)), color: ($color | tonumber),
	           description: ($description | cut(4096)), timestamp: $timestamp}
	          + (if $url == "" then {} else {url: $url} end)]}
	+ if $everyone == "true" then {content: "@everyone", allowed_mentions: {parse: ["everyone"]}}
	  elif $ping != "" then {content: "<@&\($ping)>", allowed_mentions: {parse: [], roles: [$ping]}}
	  else {allowed_mentions: {parse: []}} end' \
	>"$work/payload.json"

code=000
for attempt in 1 2 3 4 5; do
	code=$(curl -sS --max-time 15 -o "$work/response.json" -w '%{http_code}' \
		-H "Content-Type: application/json" -d @"$work/payload.json" "$WEBHOOK") || code=000
	case "$code" in
	2??)
		echo "Posted to Discord."
		exit 0
		;;
	429)
		wait=$(jq -r '.retry_after // 5' "$work/response.json" 2>/dev/null || echo 5)
		wait=$(awk -v w="$wait" 'BEGIN { w += 0; if (w < 1) w = 1; if (w > 30) w = 30; printf "%d", w + 0.999 }')
		echo "Discord is rate limiting the webhook; trying again in ${wait}s (attempt $attempt of 5)"
		;;
	000 | 5??)
		wait=${RETRY_WAIT:-5}
		echo "Discord answered HTTP $code; trying again in ${wait}s (attempt $attempt of 5)"
		;;
	*)
		echo "::error::Discord answered HTTP $code: $(head -c 300 "$work/response.json" 2>/dev/null)"
		exit 1
		;;
	esac
	if [ "$attempt" -lt 5 ]; then
		sleep "$wait"
	fi
done
echo "::warning::The Discord post did not go through after 5 attempts (HTTP $code)"
