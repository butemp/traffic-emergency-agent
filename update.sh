#!/usr/bin/env bash
# update.sh — git add/commit/push，带超时杀进程 + 自动重试
#
# 用法:
#   ./update.sh                        # 用默认 commit message 'update'
#   ./update.sh "fix: xxx"             # 自定义 commit message
#
# 可调环境变量:
#   PUSH_TIMEOUT=180        每次 push 的硬性超时秒数，超过会被 kill 重试
#   LOW_SPEED_TIME=30       连续 LOW_SPEED_TIME 秒上传速度低于 LOW_SPEED_LIMIT 字节/秒，git 自己放弃
#   LOW_SPEED_LIMIT=1000    单位字节/秒
#   MAX_RETRIES=0           最大重试次数，0=无限重试直到成功
#   RETRY_DELAY=3           失败后等待几秒再重试
#   GIT_PUSH_REMOTE=origin  远端名
#   GIT_PUSH_BRANCH=main    分支名

set -u  # 不用 set -e —— 失败的 git push 需要进 retry 循环

# ── 配置 ──────────────────────────────────────────────
COMMIT_MSG="${1:-update}"
REMOTE="${GIT_PUSH_REMOTE:-origin}"
BRANCH="${GIT_PUSH_BRANCH:-main}"
PUSH_TIMEOUT="${PUSH_TIMEOUT:-180}"
LOW_SPEED_LIMIT="${LOW_SPEED_LIMIT:-1000}"
LOW_SPEED_TIME="${LOW_SPEED_TIME:-30}"
MAX_RETRIES="${MAX_RETRIES:-0}"
RETRY_DELAY="${RETRY_DELAY:-3}"

# ── 日志辅助 ──────────────────────────────────────────
log()  { printf '\033[1;36m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[1;33m[%s] WARN: %s\033[0m\n' "$(date +%H:%M:%S)" "$*" >&2; }
err()  { printf '\033[1;31m[%s] ERROR: %s\033[0m\n' "$(date +%H:%M:%S)" "$*" >&2; }

# ── 跨平台超时执行 ────────────────────────────────────
# macOS 默认没 `timeout`，优先用 gtimeout（brew install coreutils），
# 退化到纯 bash 看门狗。看门狗也会清理子进程（curl/git-remote-https）。
run_with_timeout() {
    local timeout_secs=$1
    shift

    if command -v gtimeout >/dev/null 2>&1; then
        gtimeout --kill-after=10 "$timeout_secs" "$@"
        return $?
    fi
    if command -v timeout >/dev/null 2>&1; then
        timeout --kill-after=10 "$timeout_secs" "$@"
        return $?
    fi

    # 纯 bash 看门狗 fallback
    "$@" &
    local pid=$!

    (
        sleep "$timeout_secs"
        if kill -0 "$pid" 2>/dev/null; then
            # 先 TERM 子进程（curl 等），再 TERM 主进程；3 秒后 KILL 兜底
            pkill -TERM -P "$pid" 2>/dev/null
            kill -TERM "$pid" 2>/dev/null
            sleep 3
            pkill -KILL -P "$pid" 2>/dev/null
            kill -KILL "$pid" 2>/dev/null
        fi
    ) &
    local watchdog=$!

    wait "$pid" 2>/dev/null
    local rc=$?

    # 清理看门狗
    if kill -0 "$watchdog" 2>/dev/null; then
        kill "$watchdog" 2>/dev/null
        wait "$watchdog" 2>/dev/null
    fi
    return $rc
}

# ── 主流程 ───────────────────────────────────────────
cd "$(dirname "$0")" || exit 1

log "git add ."
if ! git add .; then
    err "git add 失败"
    exit 1
fi

# 没改动就不 commit（但仍尝试 push，可能有未推送的旧 commit）
if git diff --cached --quiet; then
    log "暂存区无改动，跳过 commit"
else
    log "git commit -m \"$COMMIT_MSG\""
    if ! git commit -m "$COMMIT_MSG"; then
        err "git commit 失败"
        exit 1
    fi
fi

# 让 git 自己在网络低速时主动放弃，配合外层超时双保险
export GIT_HTTP_LOW_SPEED_LIMIT="$LOW_SPEED_LIMIT"
export GIT_HTTP_LOW_SPEED_TIME="$LOW_SPEED_TIME"

attempt=0
start_ts=$(date +%s)

while :; do
    attempt=$((attempt + 1))
    log "尝试 push #${attempt} → ${REMOTE}/${BRANCH}，硬超时 ${PUSH_TIMEOUT}s，低速放弃 ${LOW_SPEED_TIME}s/${LOW_SPEED_LIMIT}B/s"

    if run_with_timeout "$PUSH_TIMEOUT" git push --progress "$REMOTE" "$BRANCH"; then
        elapsed=$(( $(date +%s) - start_ts ))
        log "✓ push 成功（共尝试 ${attempt} 次，总耗时 ${elapsed}s）"
        exit 0
    fi

    rc=$?
    case $rc in
        124|137|143)
            warn "第 ${attempt} 次 push 被超时杀掉 (rc=${rc})"
            ;;
        *)
            warn "第 ${attempt} 次 push 失败 (rc=${rc})"
            ;;
    esac

    if [ "$MAX_RETRIES" -gt 0 ] && [ "$attempt" -ge "$MAX_RETRIES" ]; then
        err "达到最大重试次数 ${MAX_RETRIES}，放弃。可设置 MAX_RETRIES=0 无限重试。"
        exit 1
    fi

    log "${RETRY_DELAY}s 后重试..."
    sleep "$RETRY_DELAY"
done
