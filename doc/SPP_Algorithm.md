# 单点定位(SPP)算法原理与实现

## 1. 基本原理

### 1.1 观测方程

单点定位 (Single Point Positioning, SPP) 使用伪距观测值求解接收机位置和钟差。基本观测方程为：

$$P_i = \rho_i + c \cdot dt + \epsilon_i$$

其中：
- $P_i$：第 $i$ 颗卫星的伪距观测值 (米)
- $\rho_i$：接收机到卫星 $i$ 的几何距离 (米)
  $$\rho_i = \sqrt{(X^{sat}_i - X^{rec})^2 + (Y^{sat}_i - Y^{rec})^2 + (Z^{sat}_i - Z^{rec})^2}$$
- $c$：光速 = 299,792,458 m/s
- $dt$：接收机钟差 (秒)
- $\epsilon_i$：测量噪声及其他误差

### 1.2 待求解参数

$$\mathbf{x} = [X^{rec}, Y^{rec}, Z^{rec}, dt]^T$$

4个未知数：ECEF坐标系下的接收机XYZ位置 + 钟差

### 1.3 线性化

使用泰勒级数展开，对初始近似位置 $\mathbf{x}_0$ 进行线性化：

$$\rho_i(\mathbf{x}) \approx \rho_i(\mathbf{x}_0) + \nabla\rho_i^T (\mathbf{x} - \mathbf{x}_0)$$

其中梯度（方向余弦）为：

$$\frac{\partial \rho_i}{\partial X} = -\frac{X^{sat}_i - X^{rec}_0}{\rho_i(\mathbf{x}_0)} = -\cos\alpha_i$$

$$\frac{\partial \rho_i}{\partial Y} = -\cos\beta_i, \quad \frac{\partial \rho_i}{\partial Z} = -\cos\gamma_i$$

线性化的观测方程：

$$P_i = \rho_i(\mathbf{x}_0) - \cos\alpha_i \Delta X - \cos\beta_i \Delta Y - \cos\gamma_i \Delta Z + c \cdot \Delta dt + \epsilon_i$$

整理为标准形式：

$$l_i = P_i - [\rho_i(\mathbf{x}_0) + c \cdot dt_0] = a_i \Delta x + b_i \Delta y + c_i \Delta z - \Delta(cdt) + \epsilon_i$$

### 1.4 最小二乘求解

**设计矩阵 A**（每行为一颗卫星）：

$$\mathbf{A} = \begin{bmatrix}
-\cos\alpha_1 & -\cos\beta_1 & -\cos\gamma_1 & -1 \\
-\cos\alpha_2 & -\cos\beta_2 & -\cos\gamma_2 & -1 \\
\vdots & \vdots & \vdots & \vdots \\
-\cos\alpha_n & -\cos\beta_n & -\cos\gamma_n & -1
\end{bmatrix}$$

**权矩阵 W**（可选，基于仰角）：

$$W = \text{diag}\left(\frac{1}{\sin^2(El_1)}, \frac{1}{\sin^2(El_2)}, \cdots, \frac{1}{\sin^2(El_n)}\right)$$

高仰角卫星权重更高。

**法方程**：

$$(\mathbf{A}^T \mathbf{W} \mathbf{A}) \mathbf{x} = \mathbf{A}^T \mathbf{W} \mathbf{l}$$

**解的形式**：

$$\hat{\mathbf{x}} = (\mathbf{A}^T \mathbf{W} \mathbf{A})^{-1} \mathbf{A}^T \mathbf{W} \mathbf{l}$$

### 1.5 精度指标

**方差-协方差矩阵**：

$$\mathbf{Q} = \sigma_0^2 (\mathbf{A}^T \mathbf{W} \mathbf{A})^{-1}$$

其中 $\sigma_0^2$ 为单位权方差：

$$\sigma_0^2 = \frac{\mathbf{v}^T \mathbf{W} \mathbf{v}}{n - 4}$$

$\mathbf{v}$ 为残差向量，$n$ 为卫星数。

**DOP值（精度因子）**：

- GDOP (Geometric)：$GDOP = \sqrt{\text{trace}(\mathbf{Q}) / c^2}$
- PDOP (Position)：$PDOP = \sqrt{Q_{xx} + Q_{yy} + Q_{zz}} / c$
- HDOP (Horizontal)：$HDOP = \sqrt{Q_{ee} + Q_{nn}} / c$（ENU坐标系）
- VDOP (Vertical)：$VDOP = \sqrt{Q_{uu}} / c$
- TDOP (Time)：$TDOP = \sqrt{Q_{tt}} / c$

---

## 2. 算法流程

### 2.1 数据预处理

```
输入：EpochObservation（观测数据）
      approx_position（近似位置）
  ↓
提取伪距观测值
  ├─ 过滤条件：
  │  ├─ 卫星有有效信号
  │  ├─ 伪距有效 (> 0)
  │  └─ 仰角 > MIN_ELEVATION (通常10°)
  ↓
生成观测列表，每个观测包含：
  {
    'sat_key': 'G01',
    'pseudorange': 20000000.5,
    'elevation': 45.2,
    'azimuth': 120.5,
    'sat_pos': [X, Y, Z],
  }
  ↓
返回有效观测列表或None
```

### 2.2 迭代最小二乘求解

```
初始化：
  x_curr = [0, 0, 0, 0]  # 状态值増量
  pos_curr = approx_position  # 当前位置估计
  iteration = 0
  
循环（最多MAX_ITERATIONS = 10次）：

(1) 构造法方程
    ├─ 对每颗卫星 i：
    │  ├─ 计算几何位置变化 dr = sat_pos - pos_curr
    │  ├─ 计算距离 rho = ||dr||
    │  ├─ 方向余弦（设计矩阵行）：
    │  │  A[i] = [-dr[0]/rho, -dr[1]/rho, -dr[2]/rho, -1]
    │  ├─ 计算伪距残差：
    │  │  b[i] = P_measured - (rho + x_curr[3]/c)
    │  └─ 计算权重（仰角加权）：
    │     W[i,i] = 1 / sin^2(elevation)
    │
    ├─ 法方程矩阵：
    │  AtWA = A^T · W · A
    │  AtWb = A^T · W · b
    │
    └─ 添加正则化项避免奇异：
       AtWA += 1e-6 · I

(2) 求解增量
    delta_x = (AtWA)^{-1} · AtWb
     ↓
    更新状态：
    pos_new = pos_curr + delta_x[0:3]
    x_new = x_curr + delta_x

(3) 检查收敛
    pos_change = ||delta_x[0:3]||
    
    若 pos_change < CONVERGENCE_THRESHOLD (1e-4 m)：
      ├─ convergence = True
      ├─ break (收敛，退出循环)
      └─ 返回最终解
    
    否则：
      ├─ x_curr = x_new
      └─ pos_curr = pos_new（继续迭代）

输出：
  position_ecef = pos_curr
  clock_bias = x_curr[3]
  convergence = 是否收敛
```

### 2.3 精度计算

```
(1) 计算最终残差
    对每颗卫星：
      residual = P_measured - (离职 + clock_bias/c)
    ↓
    残差统计：均值、标准差、最大值

(2) 计算方差-协方差矩阵
    ├─ 重构最终设计矩阵 A_final
    ├─ 计算协方差：
    │  Cov = σ₀² · (A^T·W·A)^{-1}
    │  其中 σ₀² = Σ(residual²) / (n - 4)
    │
    ├─ 提取标准差：
    │  std_x = √Cov[0,0]
    │  std_y = √Cov[1,1]
    │  std_z = √Cov[2,2]
    │  std_clock = √Cov[3,3]
    │
    └─ 转换到ENU坐标系获得 std_north, std_east, std_up

(3) 计算DOP值
    ├─ GDOP = √(trace(Cov) / c²)
    ├─ PDOP = √((Cov_xx + Cov_yy + Cov_zz) / c²)
    ├─ HDOP, VDOP（ENU中）
    └─ TDOP（时间）

(4) 坐标转换
    ├─ ECEF → LLA：
    │  X, Y, Z → Latitude, Longitude, Height
    │
    └─ 计算高度（椭圆体高）
```

### 2.4 解状态判断

```
若 convergence ∧ num_satellites ≥ 4：
  status = "Fixed"  # 固定解
否则若 num_satellites ≥ 4：
  status = "Uncertain"  # 浮点解
否则：
  status = "No Fix"  # 无解
```

---

## 3. 关键参数说明

### 3.1 SPPPositioner 类参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CLIGHT` | 299,792,458 | 光速 (m/s) |
| `WEIGHT_MODE` | 'elevation' | 权重模式：'equal'/'elevation'/'snr' |
| `MAX_ITERATIONS` | 10 | 最大迭代次数 |
| `CONVERGENCE_THRESHOLD` | 1e-4 | 收敛阈值 (米) |
| `MIN_SATELLITES` | 4 | 最少卫星数 |
| `MIN_ELEVATION` | 10.0 | 最低仰角 (度) |

### 3.2 信号精度相关

**伪距码精度** (~1-2米)：
- 受到电离层延迟
- 对流层延迟
- 多路径效应

**一般精度** (无校正)：
- 水平：5-10米 (明确天空视野)
- 竖直：8-15米

---

## 4. 实现细节

### 4.1 坐标转换

**ECEF → LLA (WGS84)**

```python
def ecef2lla(x, y, z):
    a = 6378137.0  # 地球长半轴
    e2 = 6.69437999014e-3  # 第一偏心率平方
    
    b = a * sqrt(1 - e2)
    ep = sqrt((a² - b²) / b²)
    p = sqrt(x² + y²)
    
    θ = atan2(a*z, b*p)
    lon = atan2(y, x)
    lat = atan2(z + ep²·b·sin³(θ), 
                 p - e2·a·cos³(θ))
    
    N = a / sqrt(1 - e2·sin²(lat))
    alt = p/cos(lat) - N
    
    return [lat_deg, lon_deg, alt]
```

### 4.2 ECEF → ENU 旋转

用于计算VDOP和HDOP：

```python
def ecef2enu_matrix(lat, lon):
    sl, cl = sin(lat), cos(lat)
    slon, clon = sin(lon), cos(lon)
    
    R = [[-slon,        clon,     0],
         [-sl·clon, -sl·slon,    cl],
         [ cl·clon,  cl·slon,    sl]]
    
    return R
```

### 4.3 权重函数

**仰角加权（推荐）**：

$$W_i = \frac{1}{\sin^2(El_i)}$$

优点：自动抑制低仰角卫星的影响（多路径强）

---

## 5. 数据流示例

### 输入数据（一个观测历元）

```
Epoch Time: 2026-02-09 12:34:56 UTC
GPS Week: 2345
Time of Week: 43200.0 seconds

卫星观测：
┌─────┬──────┬─────────┬──────────┬──────────┐
│ PRN │ Elev │ Azimuth │ PseudoR  │ SNR(dB)  │
├─────┼──────┼─────────┼──────────┼──────────┤
│ G01 │ 45.2 │  120.5  │ 20e6 +X  │  42      │
│ G08 │ 32.1 │  268.3  │ 20e6 +Y  │  38      │
│ G12 │ 65.8 │   45.2  │ 20e6 +Z  │  45      │
│ G28 │ 18.5 │  195.6  │ 20e6 +W  │  32      │
│ C01 │ 55.2 │  312.1  │ 20e6 +V  │  40      │
└─────┴──────┴─────────┴──────────┴──────────┘

近似位置：
X: 4,000,000 m
Y: 3,000,000 m  
Z: 5,000,000 m
```

### 输出数据（定位解）

```
PositioningSolution:
├─ Time: 2026-02-09 12:34:56.000 UTC
├─ Position (LLA):
│  ├─ Latitude:  37.426773°N
│  ├─ Longitude: 127.361389°E
│  └─ Height:    50.234 m
├─ Position (ECEF):
│  ├─ X: 3,999,876.45 m
│  ├─ Y: 3,000,123.89 m
│  └─ Z: 5,000,045.12 m
├─ Clock:
│  ├─ Bias: -1234.56 m (≈ -4.11 μs)
│  └─ Std: ±0.89 m
├─ Accuracy:
│  ├─ HDOP: 2.34
│  ├─ VDOP: 3.89
│  ├─ PDOP: 4.45
│  ├─ Std North: ±4.2 m
│  ├─ Std East:  ±3.8 m
│  └─ Std Up:    ±7.1 m
├─ Quality:
│  ├─ Satellites: 5
│  ├─ Status: "Fixed"
│  ├─ Convergence: True
│  └─ σ₀²: 1.23 m²
└─ Residuals:
   ├─ Mean: +0.14 m
   ├─ Std: ±0.67 m
   └─ Max: ±1.89 m
```

---

## 6. 常见问题和改进

### 6.1 精度改进

| 技术 | 精度改进 | 实现 |
|------|--------|------|
| 电离层模型 | ±2-4 m | 使用Klobuchar或IRI模型 |
| 对流层模型 | ±1-2 m | Saastamoinen或UNB3m模型 |
| 相位平滑 | ±0.5-1 m | 伪距+载波相位组合 |
| 差分GNSS | ±1-10 m | 基准站修正 |
| 实时动态(RTK) | ±1-5 cm | 载波相位高精度定位 |

### 6.2 已知限制

1. **多路径**：信号反射导致伪距偏差 (±1-10 m)
2. **信号丢失**：城市峡谷环境卫星可用性低
3. **时间延拓**：长时间无新信号导致钟差增大
4. **轨道误差**：广播星历精度 ±1-2 m

### 6.3 后续发展

本实现为基础SPP框架，可扩展为：
- **PPP (Precise Point Positioning)**：使用精密星历和钟差产品
- **RTK (Real-Time Kinematic)**：基准站+流动站相位定位
- **多源融合**：GNSS + INS/IMU 组合
- **滤波估计**：Kalman/粒子滤波平滑结果

---

## 参考资源

### 标准文献
1. Teunissen, P. J., & Montenbruck, O. (2017). *GNSS data processing* (Vols. I & II). Springer.
2. Leick, A., et al. (2015). *GPS satellite surveying* (4th ed.). Wiley.
3. Hofmann-Wellenhof, B., et al. (2008). *GNSS Global Navigation Satellite Systems*. Springer.

### 标准规范
- RTCM SC-104：国际RTCM标准委员会 (伪距观测值格式)
- IERS：国际地球自转服务 (极移、周年差)
- NIST：美国国家标准与技术研究所 (时间系统定义)

### 在线资源
- IGS (International GNSS Service)：https://www.igs.org
- UNAVCO：https://www.unavco.org
- GPSTk：开源GNSS工具包
