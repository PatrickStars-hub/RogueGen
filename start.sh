#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# ── 颜色 ───────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
PURPLE='\033[0;35m'
RESET='\033[0m'

log_banner() {
  echo ""
  echo -e "${PURPLE}╔══════════════════════════════════════════════╗${RESET}"
  echo -e "${PURPLE}║     🎮 ROGUELIKE GENERATOR — STARTING UP     ║${RESET}"
  echo -e "${PURPLE}╚══════════════════════════════════════════════╝${RESET}"
  echo ""
}

log_info()    { echo -e "${CYAN}[INFO]${RESET}  $1"; }
log_ok()      { echo -e "${GREEN}[ OK ]${RESET}  $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${RESET}  $1"; }
log_error()   { echo -e "${RED}[ERR ]${RESET}  $1"; }
log_section() { echo -e "\n${YELLOW}──── $1 ────${RESET}"; }

# ── 清理函数（Ctrl+C 时关闭所有子进程） ───────────────────────
cleanup() {
  echo ""
  log_info "正在关闭所有服务..."
  [ -n "$BACKEND_PID" ]  && kill "$BACKEND_PID"  2>/dev/null
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
  log_ok "已关闭，再见 👋"
  exit 0
}
trap cleanup SIGINT SIGTERM

log_banner

# ── 检查 .env ──────────────────────────────────────────────────
log_section "环境检查"

if [ ! -f "$BACKEND_DIR/.env" ]; then
  log_warn ".env 不存在，正在从 .env.example 创建..."
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
  log_warn "请编辑 backend/.env 填写 OPENAI_API_KEY，然后重新运行本脚本"
  exit 1
fi

# 检查 API Key 是否已填写
OPENAI_KEY=$(grep -E "^OPENAI_API_KEY=" "$BACKEND_DIR/.env" | cut -d'=' -f2 | tr -d ' ')
if [ -z "$OPENAI_KEY" ] || [ "$OPENAI_KEY" = "sk-xxx" ]; then
  log_error "OPENAI_API_KEY 尚未配置，请编辑 backend/.env"
  exit 1
fi
log_ok "OPENAI_API_KEY 已配置"

# ── 后端：Python 虚拟环境 ──────────────────────────────────────
log_section "后端初始化"

VENV_DIR="$BACKEND_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  log_info "创建 Python 虚拟环境..."
  python3 -m venv "$VENV_DIR"
  log_ok "虚拟环境创建完成"
fi

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# 检查依赖是否已安装（用 fastapi 作为标志）
if ! "$PYTHON" -c "import fastapi" 2>/dev/null; then
  log_info "安装后端依赖（首次运行需要一些时间）..."
  "$PIP" install -q --upgrade pip
  "$PIP" install -q -r "$BACKEND_DIR/requirements.txt"
  log_ok "后端依赖安装完成"
else
  log_ok "后端依赖已就绪"
fi

# 读取端口
PORT=$(grep -E "^PORT=" "$BACKEND_DIR/.env" | cut -d'=' -f2 | tr -d ' ')
PORT=${PORT:-8765}

# 启动后端
log_info "启动后端服务（端口 $PORT）..."
cd "$BACKEND_DIR"
"$VENV_DIR/bin/uvicorn" main:app --reload --port "$PORT" \
  --log-level warning 2>&1 | sed "s/^/${CYAN}[backend]${RESET} /" &
BACKEND_PID=$!
log_ok "后端进程已启动 (PID $BACKEND_PID)"

# 等待后端就绪
log_info "等待后端就绪..."
MAX_WAIT=20
COUNT=0
until curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; do
  sleep 1
  COUNT=$((COUNT + 1))
  if [ $COUNT -ge $MAX_WAIT ]; then
    log_error "后端启动超时，请检查日志"
    cleanup
  fi
done
log_ok "后端已就绪 → http://localhost:$PORT"
log_ok "API 文档  → http://localhost:$PORT/docs"

# ── 前端 ──────────────────────────────────────────────────────
log_section "前端初始化"

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  log_info "安装前端依赖（使用淘宝镜像，首次运行需要一些时间）..."
  cd "$FRONTEND_DIR"
  npm install --registry https://registry.npmmirror.com --silent
  log_ok "前端依赖安装完成"
else
  log_ok "前端依赖已就绪"
fi

log_info "启动前端开发服务器（端口 5173）..."
cd "$FRONTEND_DIR"
npm run dev 2>&1 | sed "s/^/${GREEN}[frontend]${RESET} /" &
FRONTEND_PID=$!
log_ok "前端进程已启动 (PID $FRONTEND_PID)"

# ── 就绪提示 ──────────────────────────────────────────────────
echo ""
echo -e "${PURPLE}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${PURPLE}║            🚀 ALL SYSTEMS ONLINE             ║${RESET}"
echo -e "${PURPLE}╠══════════════════════════════════════════════╣${RESET}"
echo -e "${PURPLE}║${RESET}  前端界面  →  ${GREEN}http://localhost:5173${RESET}         ${PURPLE}║${RESET}"
echo -e "${PURPLE}║${RESET}  后端 API  →  ${CYAN}http://localhost:$PORT${RESET}          ${PURPLE}║${RESET}"
echo -e "${PURPLE}║${RESET}  API 文档  →  ${CYAN}http://localhost:$PORT/docs${RESET}     ${PURPLE}║${RESET}"
echo -e "${PURPLE}╠══════════════════════════════════════════════╣${RESET}"
echo -e "${PURPLE}║${RESET}  按 ${RED}Ctrl+C${RESET} 关闭所有服务                    ${PURPLE}║${RESET}"
echo -e "${PURPLE}╚══════════════════════════════════════════════╝${RESET}"
echo ""

# 持续等待，直到 Ctrl+C
wait
