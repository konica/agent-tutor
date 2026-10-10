# Sourced, not run: deploy.sh and ensure-healthy.sh source it and call `check_worker || exit 1` after
# `compose up -d --wait`, so every deploy and every patch window proves the running worker is isolated and
# egress-limited (#153, ADR 0014). It uses the caller's `compose` array and `here`, and returns non-zero instead of
# exiting, so the caller decides. A worker that isn't isolated, or whose egress check finds a leak or can't run, is
# stopped first, so it parses no more untrusted PDFs.

check_worker() {
  local worker isolation user readonly_rootfs cap_drop security_opt status=0
  local -a problems=()

  # The worker parses untrusted PDFs: fail unless the running container really is isolated, whatever
  # compose.yaml says (an override file or a hand-started container would otherwise go unnoticed).
  echo "Checking the worker's isolation"
  worker=$("${compose[@]}" ps -q worker)
  [[ -n $worker ]] || { echo "The worker container is not running" >&2; return 1; }
  isolation=$(docker inspect --format \
    '{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{json .HostConfig.CapDrop}}|{{json .HostConfig.SecurityOpt}}' "$worker")
  IFS='|' read -r user readonly_rootfs cap_drop security_opt <<<"$isolation"
  [[ $user == 10001:10001 ]] || problems+=("runs as '$user', not 10001:10001")
  [[ $readonly_rootfs == true ]] || problems+=("ReadonlyRootfs is $readonly_rootfs")
  [[ $cap_drop == *'"ALL"'* ]] || problems+=("CapDrop $cap_drop does not drop ALL")
  [[ $security_opt == *'"no-new-privileges:true"'* ]] || problems+=("SecurityOpt $security_opt lacks no-new-privileges")
  if ((${#problems[@]})); then
    printf 'The worker is not isolated: %s\n' "${problems[@]}" >&2
    # Don't leave it consuming uploads after the check fails.
    docker stop "$worker" >/dev/null
    echo "Stopped the worker" >&2
    return 1
  fi

  # The worker reaches only Postgres and, through egress-proxy, its AWS endpoints. Prove it from inside: a leak, or a
  # check that can't run, stops the worker like a failed isolation check; an unreachable AWS endpoint or database
  # only fails the check.
  echo "Checking the worker's egress"
  "${compose[@]}" exec -T worker python - <"$here/check-egress.py" || status=$?
  case $status in
    0) ;;
    2) echo "The worker cannot reach a destination it needs (see above)" >&2; return 1 ;;
    *)
      docker stop "$worker" >/dev/null
      echo "Stopped the worker: the egress check found a leak or could not run (see above)" >&2
      return 1
      ;;
  esac
}
