# Realtime EKF-GNSSIR

实时 EKF-GNSSIR 海面高反演 Web 服务。这个目录已经整理成可独立发布的软件包，包含：

- Web 前端与 API：`static/`、`web.py`
- 实时运行管理：`runtime.py`、`station_worker.py`
- 默认配置与测站 IR 配置模板：`config/`
- 从 RTGS 拷入的运行依赖：`_vendor/core`、`_vendor/rt_ntrip_rinex_service`

默认 Web 地址：

```text
http://127.0.0.1:8090
```

默认登录用户：

```text
adminHRX / hao20030801
viewer / 123456
```

部署时建议通过环境变量修改：

```bash
export RT_EKF_ADMIN_USER=adminHRX
export RT_EKF_ADMIN_PASSWORD='hao20030801'
export RT_EKF_VIEWER_USER=viewer
export RT_EKF_VIEWER_PASSWORD='123456'
```

## 快速启动

在本目录内安装依赖：

```bash
python -m pip install -r requirements.txt
```

直接从源码目录运行：

```bash
python run.py --config config/app.yaml
```

Windows 也可以双击或执行：

```powershell
.\start.ps1
```

Linux/macOS：

```bash
./start.sh
```

## 作为 Python 包安装

```bash
python -m pip install .
realtime-ekf-gnssir --config config/app.yaml
```

构建 wheel/sdist：

```bash
python -m pip install build
python -m build
```

构建产物会出现在 `dist/`。

## 配置

日常只需要改两个文件：

- `config/app.yaml`：Web 端口、输出目录、测站启停、OBS/EPH NTRIP 数据源。
- `config/ir/NBFH.yaml`：NBFH 测站坐标、反射区域、核心 GNSS-IR 参数、EKF 参数和水位产品参数。

当前 `config/app.yaml` 已按 NBFH 旧配置写好：

```yaml
stations:
  - name: NBFH
    enabled: true
    reflectometry_config: ir/NBFH.yaml
    obs_settings:
      host: grserg.top
      port: 2101
      mountpoint: NBFH
      user: adminHRX
      password: hao20030801
    eph_settings:
      enabled: true
      host: ntrip.data.gnss.ga.gov.au
      port: 2101
      mountpoint: BCEP00BKG0
    runtime:
      auto_start: false
```

`reflectometry_config` 指向测站反演配置，路径相对 `config/app.yaml` 所在目录解析。`config/ir/NBFH.yaml` 已经简化，只保留常用项；没有写出的高级参数会使用程序默认值。该 IR 配置应满足：

- `ir.estimation_mode: ekf`
- `station.receiver_position.x_m/y_m/z_m` 有 ECEF 坐标
- `geometry.use_external_az_el: true`，实时 RTCM 解码会提供卫星方位角/高度角
- `ir.ekf.output_interval_seconds` 控制产品输出间隔

默认输出目录：

```text
output/realtime_ekf_gnssir/<station>/
```

每个测站会追加写入：

- `products.jsonl`
- `products.csv`

## Web API

- `GET /api/status`
- `GET /api/stations`
- `POST /api/stations`
- `PUT /api/stations/{name}`
- `DELETE /api/stations/{name}`
- `POST /api/stations/{name}/start`
- `POST /api/stations/{name}/stop`
- `POST /api/stations/{name}/restart`
- `GET /api/stations/{name}/products?limit=200`
- `GET /api/logs?source=NBFH&limit=200`

## 发布建议

发布时直接分发整个 `realtime_ekf_gnssir` 目录即可。建议保留目录名不变；如果需要换目录名，请优先使用 `python run.py` 或安装后的 `realtime-ekf-gnssir` 命令启动。

部署现场如果要避免改动默认文件，可以另存一份本地配置，例如 `config/app.local.yaml`，再用 `--config config/app.local.yaml` 启动。
