# SPP 定位模块优化说明

## 概述

本次优化为 SPP (Single Point Positioning) 定位模块添加了多项重要的配置选项和功能增强，使其更加灵活和符合 RTKLIB 标准的做法。

## 新增配置选项

### 1. 电离层延迟修正方式

**参数名：`ionosphere_option`**

- **IFLC** (默认): 双频无电离层线性组合方式
  - 使用双频率信号(如 GPS L1/L2, Galileo E1/E5a 等)
  - 自动消除电离层延迟的一阶项
  - 适用于有双频接收机的场景
  - 噪声会放大约 3 倍

- **SINGLE**: 单频加 TGD 延迟修正方式
  - 只使用单个频率的信号
  - 通过卫星发射的 TGD (Time Group Delay) 修正电离层影响
  - 更简单但精度略低
  - 适用于单频接收机

### 2. 对流层延迟模型

**参数名：`troposphere_model`**

可选方案：

- **Sastamoinen** (默认): 经典 Sastamoinen 对流层模型
  - 基于温度、气压、相对湿度的参数化模型
  - 最广泛使用，精度可靠
  - 推荐用于常规 SPP 应用

- **HMSL**: 基于高度的简化模型
  - 只考虑接收机高度
  - 计算快速、简单
  - 适用于对精度要求不高的应用

- **None**: 不进行对流层延迟修正
  - 当对流层影响较小或已有其他补偿方式时使用

### 3. 截止高度角 (Elevation Mask)

**参数名：`cutoff_elevation_deg`** (单位：度)

- 默认值：10°
- 范围：0° ~ 90°
- 低于此角度的卫星将被排除
- 角度越低，可用卫星越多，但信号质量下降
- 建议值：
  - 开阔环境：5° ~ 10°
  - 城市环境：15° ~ 20°
  - 室内/复杂环境：20° ~ 30°

### 4. 观测值权重方式

**参数名：`weight_mode`**

- **elevation** (默认): 基于高度角的权重
  - 低高度角卫星权重低
  - 符合测量噪声模型
  - 最常用

- **snr**: 基于信噪比的权重
  - 高信噪比卫星权重高
  - 需要接收机提供 SNR 数据

- **equal**: 等权重
  - 所有卫星平等对待
  - 调试用

### 5. GNSS 系统选择

**参数名：`gnss_systems`** (列表)

可用系统：
- **G**: GPS (美国)
- **R**: GLONASS (俄罗斯)
- **E**: Galileo (欧洲)
- **C**: BeiDou (中国)

示例：`['G', 'E']` 表示只使用 GPS 和 Galileo

### 6. 平滑滤波

**参数名：`use_smoothing`, `smoothing_window`**

- `use_smoothing`: 是否启用位置平滑 (默认：False)
- `smoothing_window`: 平滑窗口大小，单位为历元 (默认：10)
- 通过滑动平均减少位置噪声波动

### 7. 随机游走噪声

**参数名：`random_walk`** (单位：m/√s)

- 接收机钟差的随机游走噪声强度
- 默认值：0.0 (无)
- 对于有内部时钟漂移的接收机设置此值

### 8. 解状态阈值

- `uncertain_std_pos`: 标准偏差阈值用于判断"不确定"状态 (默认：5.0 m)
- `fixed_std_pos`: 标准偏差阈值用于判断"固定"状态 (默认：2.5 m)

解状态判定：
- **No Fix**: 卫星少于最小值或精度太差
- **Uncertain**: 精度在 2.5 ~ 5.0 m 之间
- **Fixed**: 精度优于 2.5 m 且收敛

## 配置方式

### 方式一：通过 UI 对话框

点击定位模块中的"设置"按钮，打开"定位设置"对话框，可图形化配置所有参数。

### 方式二：通过全局配置文件

在 `core/global_config.py` 中的 `positioning_settings` 字典配置：

```python
positioning_settings = {
    'cutoff_elevation_deg': 15.0,
    'min_satellites': 4,
    'ionosphere_option': 'IFLC',
    'troposphere_model': 'Sastamoinen',
    'gnss_systems': ['G', 'E', 'C'],
    'weight_mode': 'elevation',
    'use_smoothing': True,
    'smoothing_window': 10,
    'random_walk': 0.0,
    'uncertain_std_pos': 5.0,
    'fixed_std_pos': 2.5,
}
```

### 方式三：代码中动态配置

```python
from core.spp_positioning import SPPPositioner

config = {
    'ionosphere_option': 'IFLC',
    'troposphere_model': 'Sastamoinen',
    'min_elevation': 10.0,
    'min_satellites': 4,
}

positioner = SPPPositioner(, config=config)
```

## 技术细节

### 对流层延迟计算

目前实现了两种对流层模型：

1. **Sastamoinen 模型**：
   - 使用温度(T)、气压(P)、水汽分压(e) 计算
   - 在经验上对中纬度地区精度最好
   - 典型误差：1~3 cm

2. **HMSL 模型**：
   - 简化的高度相关模型
   - 计算速度快
   - 典型误差：5~15 cm

### 电离层延迟处理

1. **IFLC 模式**：
   - 双频测距值组合：$P_{IF} = \frac{f_1^2 P_1 - f_2^2 P_2}{f_1^2 - f_2^2}$
   - 自动消除电离层一阶延迟
   - 观测噪声标准差放大因子：√3 ≈ 1.73

2. **SINGLE 模式**：
   - 单频测距 - TGD 修正
   - TGD 由卫星星历提供
   - 观测噪声标准差无额外放大

## 使用建议

### GNSS 用户推荐配置

1. **高精度 PPP (精密单点定位)**
   ```
   Ionosphere: IFLC
   Troposphere: Sastamoinen
   Min Elevation: 5°
   Systems: G, E, C
   Weighting: elevation
   ```

2. **城市峡谷环境**
   ```
   Ionosphere: SINGLE (若仅有单频数据)
   Troposphere: HMSL
   Min Elevation: 20°
   Systems: G, E
   Weighting: snr (如果可用)
   ```

3. **移动行车应用**
   ```
   Ionosphere: IFLC
   Troposphere: Sastamoinen
   Min Elevation: 15°
   Systems: G
   Weighting: elevation
   Smoothing: enabled (window: 5-10)
   ```

## 参考标准

本优化参考了以下标准和算法：

- RTKLIB: 开源 GNSS 处理库
- Sastamoinen, A.J. (1972): "Atmospheric Correction for the Troposphere and Stratosphere in Radio Ranging Satellites"
- GNSS Data Processing, Vol. I & II (Teunissen & Montenbruck)
- GPS Satellite Surveying (Leick, A., 2004)

## 文件修改清单

- `core/positioning_models.py`: 扩展 `PositioningConfig` 类
- `core/global_config.py`: 更新 `positioning_settings` 默认值
- `core/spp_positioning.py`: 
  - 增强 `SPPPositioner` 初始化接收配置
  - 添加 `_calculate_tropospheric_delay()` 方法
  - 更新 `_get_err_std()` 方法
  - 优化解状态判定逻辑
- `ui/positioning/positioning_config_dialog.py`: UI 对话框扩展
- `ui/positioning/workers.py`: 集成全局配置到定位线程

## 后续扩展方向

1. **对流层模型扩展**：可添加 VMF1、GPT2 等高精度模型
2. **电离层模型**：添加 Klobuchar、NeQuick 等延迟模型
3. **接收机自适应**：根据硬件特性自动调整参数
4. **多源融合**：支持 PPP、RTK 等高级定位方式

