#!/usr/bin/env sh
# 一键把「材质替换」脚本安装到本机 Cinema 4D 的用户脚本目录。
# 只复制文件，不联网、不提权、不改动 C4D 设置。
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC="$HERE/材质替换.py"

if [ ! -f "$SRC" ]; then
  echo "找不到 材质替换.py —— 请在仓库根目录运行本脚本。" >&2
  exit 1
fi

# macOS / Linux / Wine 下的常见配置位置（逐个传参，避免路径空格被拆分）
set -- \
  "$HOME/Library/Preferences/Maxon" \
  "$HOME/.config/Maxon" \
  "$HOME/.wine/drive_c/users/$(id -un)/AppData/Roaming/Maxon"

FOUND=0
INSTALLED=0

for ROOT in "$@"; do
  [ -d "$ROOT" ] || continue

  for VERSION in "$ROOT"/Maxon\ Cinema\ 4D\ *; do
    [ -d "$VERSION" ] || continue
    FOUND=1

    # 只装 Python 3 版本（R23 / S24 / 2023+）；R21 及更早是 Python 2.7，未验证。
    BASE=${VERSION##*/}
    TOKEN=${BASE#"Maxon Cinema 4D "}
    MAJOR=$(printf '%s\n' "$TOKEN" | grep -oE '[0-9]+' | head -n 1)
    if [ -n "$MAJOR" ] && [ "$MAJOR" -lt 23 ] && [ "${C4D_INSTALL_ALL:-}" != "1" ]; then
      echo "  跳过：$BASE（Python 2.7 未验证）"
      continue
    fi

    SCRIPTS="$VERSION/library/scripts"
    mkdir -p "$SCRIPTS"
    DEST="$SCRIPTS/材质替换.py"

    if [ -f "$DEST" ] && cmp -s "$SRC" "$DEST"; then
      echo "  已是最新，跳过：$VERSION"
      INSTALLED=$((INSTALLED + 1))
      continue
    fi

    if [ -f "$DEST" ]; then
      cp -f "$DEST" "$DEST.bak"
      echo "  已备份旧文件：$DEST.bak"
    fi

    cp -f "$SRC" "$DEST"
    if ! cmp -s "$SRC" "$DEST"; then
      echo "复制后校验失败：$DEST" >&2
      exit 1
    fi
    echo "  已安装：$DEST"
    INSTALLED=$((INSTALLED + 1))
  done
done

if [ "$FOUND" -eq 0 ]; then
  echo "没有找到 Cinema 4D 配置目录。请先启动一次 C4D，或手动复制 $SRC。" >&2
  exit 1
fi

echo ""
echo "安装完成，共 $INSTALLED 处。请重启 C4D，菜单「脚本 → 材质替换」。"
