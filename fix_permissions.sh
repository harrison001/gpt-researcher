#!/bin/bash

# 文件名: fix_permissions.sh

# 确保脚本以 root 权限运行
if [ "$(id -u)" != "0" ]; then
   echo "此脚本需要 root 权限" 1>&2
   exit 1
fi

# 设置变量
USER="rocky"
GROUP="rocky"
DIR="outputs"

# 检查目录是否存在
if [ ! -d "$DIR" ]; then
    echo "错误: $DIR 目录不存在"
    exit 1
fi

# 更改目录的所有者和权限
chown $USER:$GROUP $DIR
chmod 755 $DIR

# 更改目录内所有内容的所有者和权限
chown -R $USER:$GROUP $DIR
find $DIR -type d -exec chmod 755 {} \;
find $DIR -type f -exec chmod 644 {} \;

echo "权限已更新"

# 尝试创建测试文件
su - $USER -c "touch $DIR/test.txt"
if [ $? -eq 0 ]; then
    echo "测试文件创建成功"
    rm $DIR/test.txt
else
    echo "测试文件创建失败，可能还有其他问题"
fi

echo "完成"

#   chmod +x fix_permissions.sh
# sudo ./fix_permissions.sh