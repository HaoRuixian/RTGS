# RT NTRIP to RINEX systemd 部署

这套部署文件用于把实时多站 NTRIP 转 RINEX 常驻运行在 Linux 服务器上，并交给 `systemctl` 管理。

## 目录约定

- 应用目录：`/opt/rtgs`
- systemd 服务：`rtgs-rt-ntrip-rinex.service`
- 运行配置：`/etc/rtgs/rt_multi_ntrip_rinex.yaml`
- 环境配置：`/etc/default/rtgs-rt-ntrip-rinex`
- 默认输出目录：`/mnt/20t/RT_RINEX`

## 本机打包

```bash
chmod +x deploy/*.sh
./deploy/build_rt_ntrip_rinex_package.sh
```

脚本会在 `dist/` 下生成类似：

```text
dist/rtgs-rt-ntrip-rinex-20260424153000.tar.gz
```

把这个压缩包传到服务器：

```bash
scp dist/rtgs-rt-ntrip-rinex-*.tar.gz user@server:/tmp/
```

## 服务器安装

```bash
cd /tmp
tar -xzf rtgs-rt-ntrip-rinex-*.tar.gz
cd rtgs-rt-ntrip-rinex-*
sudo ./deploy/install_rt_ntrip_rinex_systemd.sh
```

安装脚本会：

- 复制代码到 `/opt/rtgs`
- 创建专用系统用户 `rtgs`
- 创建 Python 虚拟环境并安装轻量运行依赖
- 安装 systemd 服务文件
- 首次安装时复制 `config/streams/rt_multi_ntrip_rinex.yaml` 到 `/etc/rtgs/`
- 创建默认输出目录 `/mnt/20t/RT_RINEX`
- 执行 `systemctl enable --now rtgs-rt-ntrip-rinex`

如果服务器上已经有 `/etc/rtgs/rt_multi_ntrip_rinex.yaml`，默认不会覆盖。需要强制覆盖时：

```bash
sudo OVERWRITE_CONFIG=1 ./deploy/install_rt_ntrip_rinex_systemd.sh
```

## 常用管理命令

```bash
sudo systemctl status rtgs-rt-ntrip-rinex
sudo journalctl -u rtgs-rt-ntrip-rinex -f
sudo systemctl restart rtgs-rt-ntrip-rinex
sudo systemctl stop rtgs-rt-ntrip-rinex
```

只运行部分站点时，编辑 `/etc/default/rtgs-rt-ntrip-rinex`：

```bash
RTGS_STATIONS=BUAA01,BUAA02
```

然后重启：

```bash
sudo systemctl restart rtgs-rt-ntrip-rinex
```

## 升级

重新打包、上传、解压后，再运行安装脚本即可。脚本默认保留服务器上的 `/etc/rtgs/rt_multi_ntrip_rinex.yaml` 和 `/etc/default/rtgs-rt-ntrip-rinex`。

## 注意

- `/etc/rtgs/rt_multi_ntrip_rinex.yaml` 内含 NTRIP 账号密码，安装脚本会设置为 `0640 root:rtgs`。
- 打包产物会包含当前 `config/streams/rt_multi_ntrip_rinex.yaml`，传输和存放压缩包时也按含密文件处理。
- 如果你把 `rinex.output_directory` 改到其他目录，请确保 `rtgs` 用户有写入权限。
- 服务收到 `systemctl stop` 时会向进程发送 `SIGTERM`，脚本会优雅关闭当前 RINEX writer。
