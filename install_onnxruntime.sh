#!/bin/bash
# install_onnxruntime.sh - 一键安装 onnxruntime (ARM64 + Python 3.13)
# 用法: bash install_onnxruntime.sh
# 在 HA 容器内执行

set -e

echo "=== 下载 onnxruntime ==="
pip download \
  --only-binary :all: \
  --platform manylinux_2_27_aarch64 \
  --python-version 3.13 \
  --dest /tmp/ \
  onnxruntime 2>/dev/null

cd /tmp

echo "=== 解压安装 (跳过平台检查) ==="
for whl in *.whl; do
  echo "解压: $whl"
  unzip -qo "$whl" -d "${whl%.whl}_pkg"
done

echo "=== 复制到 site-packages ==="
SITE=$(python3 -c "import sys; print([p for p in sys.path if 'site-packages' in p][0])")

# 安装 onnxruntime
cp -r onnxruntime-1.27.0-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64_pkg/onnxruntime "$SITE/"
cp -r onnxruntime-1.27.0-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64_pkg/onnxruntime-1.27.0.dist-info "$SITE/"

# 安装 numpy
cp -r numpy-2.5.1-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64_pkg/numpy "$SITE/"
cp -r numpy-2.5.1-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64_pkg/numpy-2.5.1.dist-info "$SITE/"

# 安装纯 Python 包
pip install protobuf-7.35.1-py3-none-any.whl flatbuffers-25.12.19-py2.py3-none-any.whl packaging-26.2-py3-none-any.whl 2>/dev/null

# 验证
echo "=== 验证 ==="
python3 -c "import onnxruntime; print(f'onnxruntime {onnxruntime.__version__} 安装成功!')"

echo "=== 完成 ==="
