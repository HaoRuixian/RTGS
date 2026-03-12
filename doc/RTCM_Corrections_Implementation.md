# RTCM 广播星历改正参数实现说明

## 概述
本文档详细介绍了 RTCM 标准中的广播星历改正参数解析和应用实现。

## 更新内容

### 1. 数据模型扩展 (`core/data_models.py`)

#### 1.1 新增数据类

#### `IonosphericCorrection`
- 存储电离层斜延迟 (STEC - Slant Total Electron Content)
- 包含字段：
  - `satellite_id`: 卫星标识符 (e.g., "G01", "E02")
  - `stec`: 斜向总电子含量 (TECu)
  - `stec_rate`: STEC 变化率 (TECu/s)
  - `signal_id`: 信号标识符
  - `quality_indicator`: 质量指示器 (0-15)

#### `TroposphericCorrection`
- 存储对流层延迟改正
- 包含字段：
  - `ztd_hydro`: 天顶静水延迟 (m)
  - `ztd_wet`: 天顶湿度延迟 (m)
  - `ztd_rate_hydro`: 静水延迟变化率 (m/s)
  - `ztd_rate_wet`: 湿度延迟变化率 (m/s)
  - `quality_indicator`: 质量指示器

#### `SatelliteBiasCorrection`
- 存储卫星码和相位偏差改正
- 包含字段：
  - `satellite_id`: 卫星标识符
  - `code_biases`: 码偏差字典 {信号_id: 偏差(m)}
  - `phase_biases`: 相位偏差字典 {信号_id: 偏差(周期)}
  - `yaw_angle`: 偏航角 (弧度)
  - `yaw_rate`: 偏航角变化率 (弧度/秒)

#### `SatelliteClockCorrection`
- 存储卫星钟和轨道改正
- 包含字段：
  - `satellite_id`: 卫星标识符
  - `delta_clock`: 钟改正 (m)
  - `delta_clock_rate`: 钟改正速率 (m/s)
  - `delta_radial`, `delta_along_track`, `delta_cross_track`: 轨道改正 (m)
  - 对应的速率字段

#### `BroadcastEphemerisCorrections`
- **新增**：存储广播星历中包含的物理改正参数
- 包含字段：
  - `TGD`: 总群延迟 GPS (m)
  - `TGD1`, `TGD2`: BDS TGD 参数 (m)
  - `ISC_L1CA`, `ISC_L1C`, `ISC_L5I`, `ISC_L5Q`: Galileo/GPS 信号间修正 (m)
  - `BGD_E1E5a`, `BGD_E1E5b`: Galileo 偏差群延迟 (m)
  - `SISA`: Galileo 信号完好性指示器
  - `URAI`: BDS 用户距离精度指示器
  - `SatHealth`: 卫星健康状态
  - `FitInterval`: 拟合间隔指示器
  - `AODE`, `AODC`: BDS 数据年龄

#### `EpochObservation` 扩展
- 新增字段以支持改正参数存储：
  - `ionospheric_corrections`: 电离层改正字典
  - `tropospheric_correction`: 对流层改正
  - `satellite_bias_corrections`: 卫星偏差改正字典
  - `satellite_clock_corrections`: 卫星钟/轨道改正字典
  - `broadcast_eph_corrections`: **新增**广播星历改正字典
  - `gps_glonass_time_bias`, `gps_galileo_time_bias`, `gps_bds_time_bias`: GNSS 系统间时间偏差

### 2. RTCM 处理器扩展 (`core/rtcm_handler.py`)

#### 2.1 广播星历改正参数提取

##### GPS 星历 (消息 1019)
- 提取 `TGD` (总群延迟) - 用于电离层延迟改正
- 提取 `SatHealth` (卫星健康状态)
- 存储在 `broadcast_eph_cache` 中

##### Galileo 星历 (消息 1045/1046)
- 提取 `BGD_E1E5a`, `BGD_E1E5b` (偏差群延迟)
- 提取 `SISA` (信号完好性)
- 存储在 `broadcast_eph_cache` 中

##### BeiDou 星历 (消息 1042)
- 提取 `TGD1`, `TGD2` (两个 TGD 参数 - 代表不同频率对)
- 提取 `URAI` (用户距离精度指示器)
- 提取 `AODE`, `AODC` (数据年龄)
- 存储在 `broadcast_eph_cache` 中

##### GLONASS 星历 (消息 1020)
- 提取 `SatHealth` (卫星健康状态)
- 存储在 `broadcast_eph_cache` 中

#### 2.2 新增改正消息处理

| 消息类型 | 描述 | 实现状态 |
|---------|------|---------|
| 1225-1227 | 对流层改正 | ✓ 已实现 |
| 1230 | SSR 电离层改正 | ✓ 已实现 |
| 1240 | SSR 组合改正 | ✓ 已实现 |
| 1241 | SSR 轨道和钟改正 | ✓ 已实现 |
| 1242 | SSR 详细钟改正 | ✓ 已实现 |
| 1244 | SSR 码偏差改正 | ✓ 已实现 |
| 1245 | SSR 相位偏差改正 | ✓ 已实现 |
| 1264-1268 | 网格化电离层改正 | ✓ 已实现 (框架) |
| 1269-1271 | 网格化对流层改正 | ✓ 已实现 (框架) |
| 1271-1273 | 系统间时间偏差改正 | ✓ 已实现 |

#### 2.3 公共接口方法

```python
# 获取广播星历改正参数
rtcm_handler.get_broadcast_eph_correction(satellite_id)  # 获取单个卫星改正
rtcm_handler.get_all_broadcast_eph_corrections()         # 获取所有卫星改正

# 便利方法
rtcm_handler.get_tgd_correction(satellite_id)  # 获取 TGD
rtcm_handler.get_bgd_correction(satellite_id)  # 获取 BGD

# 应用改正
rtcm_handler.apply_ionospheric_correction(pseudorange, sig_id, stec_value)
rtcm_handler.apply_tropospheric_correction(pseudorange, elevation_angle, tropo_corr)
```

### 3. 改正参数应用示例

#### 3.1 使用电离层改正
```python
from core.rtcm_handler import get_shared_handler

handler = get_shared_handler()

# 处理 RTCM 消息
epoch_data = handler.process_message(msg, epoch_data)

# 获取某颗卫星的电离层改正
if 'G01' in epoch_data.ionospheric_corrections:
    iono_corr = epoch_data.ionospheric_corrections['G01']
    corrected_range = handler.apply_ionospheric_correction(
        pseudorange=obs.pseudorange,
        sig_id=obs.signal_id,
        stec_value=iono_corr.stec
    )
```

#### 3.2 使用对流层改正
```python
# 对所有卫星应用对流层改正
if epoch_data.tropospheric_correction:
    for sat_key, sat_state in epoch_data.satellites.items():
        elevation_rad = math.radians(sat_state.elevation)
        for sig_id, obs in sat_state.signals.items():
            corrected_range = handler.apply_tropospheric_correction(
                pseudorange=obs.pseudorange,
                elevation_angle=elevation_rad,
                tropo_corr=epoch_data.tropospheric_correction
            )
```

#### 3.3 使用广播星历改正参数
```python
# 获取 TGD 改正
for sat_key in epoch_data.satellites:
    tgd = handler.get_tgd_correction(sat_key)
    if tgd:
        # 应用 TGD 改正以消除电离层延迟
        # TGD 对伪距的影响取决于使用的频率
        pass
```

### 4. 技术细节

#### 4.1 电离层延迟模型
- STEC 与伪距延迟的关系：延迟 ≈ 0.1017 × STEC (m/TECu)
- 对偶频率接收机，可以通过线性组合消除电离层延迟

#### 4.2 对流层延迟模型
- 静水成分：主要取决于地面气压和温度
- 湿成分：取决于大气水蒸汽含量
- 映射函数：将天顶延迟转换为斜向延迟
  - 简化模型：$delay = ZTD / \sin(elevation)$

#### 4.3 消息兼容性
- GPS 1019: DF101 (TGD)
- Galileo 1045/1046: DF312, DF313 (BGD)
- BeiDou 1042: DF513, DF514 (TGD1, TGD2)
- GLONASS 1020: DF104 (Health)

### 5. 使用建议

1. **广播星历改正**：在实时应用中用于原始导航
2. **SSR 改正**：精密定位应用，提供更高精度
3. **电离层改正**：关键用于长基线定位和高精度应用
4. **对流层改正**：特别重要在潮湿/赤道地区

### 6. 扩展可能性

- 实现 ISC (Inter-Signal Corrections) 对每个信号的精细改正
- 支持更复杂的对流层映射函数 (Niell, VMF1, GMF)
- 网格化改正的完整实现
- 多系统改正的融合算法

## 参考文献

- RTCM Standard 10403.3 (State Space Representation RTK)
- IGS SSR Message Format Documentation
- WGS84 电离层和对流层模型

