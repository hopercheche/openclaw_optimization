import matplotlib.pyplot as plt
import numpy as np

# 1. 设置高级商业学术排版样式
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
plt.rcParams['axes.linewidth'] = 1.2

datasets = ['MMLU-Pro', 'LongMemEval', 'LoCoMo', 'GPQA Diamond', 'ACEBench']
# 商业权重 (WTP)
WTP = np.array([1.0, 1.2, 1.5, 3.0, 2.5])

# 我们按照成本从低到高重新排列模块，形成 "升级路径"
# 路径: Router (基础) -> Baseline (+1) -> Architect (+2) -> Planner (+3)
upgrade_labels = ['Base (Router)', '+ Baseline', '+ Architect', '+ Planner']
# 配色: 基础(翠绿), 升级1(灰), 升级2(靛蓝), 升级3(珊瑚红)
colors = ['#00BFA5', '#B0BEC5', '#5C6BC0', '#EF5350']

# 真实数据 (已按 Router -> Baseline -> Architect -> Planner 的成本升序重新排列)
acc_sorted = np.array([
    [0.8680, 0.6840, 0.5623, 0.7850, 0.2283],  # Router (Base)
    [0.8810, 0.7000, 0.5960, 0.8000, 0.3200],  # Baseline
    [0.8820, 0.7380, 0.6280, 0.8010, 0.3240],  # Architect
    [0.8930, 0.7060, 0.6010, 0.8220, 0.3620]   # Planner
])
cost_sorted = np.array([
    [0.0235, 0.0812, 0.0214, 0.0163, 0.0141],  # Router (Base)
    [0.0639, 0.2415, 0.0990, 0.0456, 0.0639],  # Baseline
    [0.0641, 0.3241, 0.1325, 0.0461, 0.0642],  # Architect
    [0.0984, 0.3582, 0.1425, 0.0812, 0.1054]   # Planner
])

# 2. 计算效用 Utility = -ln(1 - Score) * WTP
utility_sorted = -np.log(1.0 - acc_sorted) * WTP

# 3. 计算边际数值 (Marginal Values)
marginal_roi = np.zeros_like(utility_sorted)

# a. 基础款 (Router) 的基础性价比 = U / C
marginal_roi[0, :] = utility_sorted[0, :] / cost_sorted[0, :]

# b. 升级款的边际性价比 = ΔU / ΔC
for i in range(1, 4):
    delta_u = utility_sorted[i, :] - utility_sorted[i-1, :]
    delta_c = cost_sorted[i, :] - cost_sorted[i-1, :]
    
    # 避免除以 0 或极小数 (例如 Baseline 到 Architect 在某些数据集上成本几乎没增加)
    # 如果 ΔC <= 0 或者 ΔU <= 0（比如 Planner 分数反降），则边际收益设为 0
    with np.errstate(divide='ignore', invalid='ignore'):
        roi = np.where((delta_c > 0) & (delta_u > 0), delta_u / delta_c, 0.1)
    marginal_roi[i, :] = roi

# 4. 创建画布
fig, ax = plt.subplots(figsize=(15, 8), facecolor='#F8F9FA')
ax.set_facecolor('#F8F9FA')

x = np.arange(len(datasets))
width = 0.18      
spacing = 0.03    

# 5. 绘制分组柱状图
for i, label in enumerate(upgrade_labels):
    offset = (i - 1.5) * (width + spacing)
    bars = ax.bar(x + offset, marginal_roi[i], width, label=label, 
                  color=colors[i], edgecolor='white', linewidth=1.5, zorder=3)
    
    # 标注数值
    for j, bar in enumerate(bars):
        height = bar.get_height()
        # 过滤掉几乎为 0 的异常无收益升级，保持画面整洁
        if height > 1.0:
            ax.text(bar.get_x() + bar.get_width()/2., height + (np.max(marginal_roi)*0.01),
                    f'{height:.1f}', 
                    ha='center', va='bottom', fontsize=10, fontweight='bold', color='#333333', zorder=4)

# 6. 坐标轴美化
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['left'].set_visible(False)  
ax.tick_params(axis='y', length=0)    
ax.tick_params(axis='x', length=5, colors='#333333')
ax.grid(axis='y', linestyle='-', color='#E0E0E0', linewidth=1, zorder=0)

# 7. 标题与排版设计 (对齐经济学理念)
ax.set_ylabel('Marginal ROI (Δ Utility / Δ Cost)', fontsize=12, fontweight='bold', color='#333333', labelpad=15)
ax.set_title('Law of Diminishing Marginal Returns in Agent Upgrades', 
             fontsize=20, fontweight='900', color='#1A1A1A', pad=35, loc='left')
             
subtitle = "Router serves as the highly efficient 'Base Model'. Subsequent bars show the ROI of paying extra for Baseline, Architect, or Planner.\n" \
           "A sharp drop indicates an 'IQ Tax' (low marginal value), while spikes (e.g., Architect on LongMemEval) justify the upgrade cost."
ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=13, color='#555555')

ax.set_xticks(x)
ax.set_xticklabels(datasets, fontsize=14, fontweight='bold', color='#333333')

# 对数刻度 (可选，如果首列 Router 的数值过分碾压，使用对数轴能看清后三个的细节)
# 我们这里保持线性，最能体现 Router 的基础断层优势和边际暴跌的惨烈感。
ax.set_ylim(0, np.max(marginal_roi) * 1.15)

legend = ax.legend(loc='upper right', fontsize=12, frameon=False, ncol=4, bbox_to_anchor=(1, 1.15))
for text in legend.get_texts():
    text.set_color('#333333')

plt.tight_layout()
plt.savefig('marginal_roi_upgrades.png', dpi=300, bbox_inches='tight', facecolor='#F8F9FA')
plt.show()