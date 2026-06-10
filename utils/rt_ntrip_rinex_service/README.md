# RT NTRIP RINEX Service

这个目录是可独立发布的多测站 RT NTRIP -> RINEX 服务，包含运行内核、RINEX 写入、RTCM 解析、日文件合并、配置持久化和 Web 管理界面。

## 功能

- 多路 NTRIP 并发采集，断流后自动重连。
- 观测类型自动识别后写回 YAML 配置，后续严格按配置写 RINEX。
- RTCM 1005/1006 中解析到的测站近似坐标会写回 `rinex.approx_position`。
- 每 60 秒轮询配置文件，Web 新增、删除、修改测站后自动同步 worker。
- 小文件按小时或自定义周期写入，按 GPS 时间每天自动扫描并合并上一日文件；缺少部分小时文件时也会在日期结束后合并已有数据。
- Web 界面可查看状态、按来源筛选日志、查看当前输出文件，并维护测站配置。

## 安装

```powershell
cd D:\GNSS_ToolBox\RTGS
python -m pip install -r utils\rt_ntrip_rinex_service\requirements.txt
```

## 启动

```powershell
python -m utils.rt_ntrip_rinex_service utils\rt_ntrip_rinex_service\examples\rt_multi_ntrip_rinex.yaml --web-host 127.0.0.1 --web-port 8088
```

打开 `http://127.0.0.1:8088` 管理测站。对外网开放时请放在受信任网络或反向代理认证后面。

## 配置要点

- `rinex.sys_obs_types` 为空且 `auto_detect_obs_types: true` 时，服务会从实时 RTCM MSM 观测中识别观测类型。
- 一旦识别成功，服务会把 `sys_obs_types` 写回配置，并把该测站的 `auto_detect_obs_types` 置为 `false`。
- `split_period_seconds < 86400` 时会写入分片目录 `站点/yyyy/ddd/`，其中 `ddd` 是三位年积日，并由合并线程生成 `01D` 日文件。
- `daily_merge_min_interval_seconds` 控制日合并输出采样间隔，默认不低于 15 秒。
- 时间系统固定为 `GPS`；Web 保存配置时也会写入 `rinex.time_system: GPS`。
- `header_refresh_seconds` 控制流式写入时 RINEX header 更新时间，降低进程异常退出导致 header 过旧的风险。
- `fsync_interval_seconds` 大于 0 时定期执行磁盘同步，可靠性更高但 I/O 压力更大。

## API

- `GET /api/status`
- `GET /api/stations`
- `POST /api/stations`
- `PUT /api/stations/{name}`
- `DELETE /api/stations/{name}`
- `POST /api/reload`
- `POST /api/merge`
- `GET /api/logs`
