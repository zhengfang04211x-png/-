import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io
import platform

# ==============================================================================
# 1. 🎨 页面基本设置与字体
# ==============================================================================
st.set_page_config(page_title="企业套保资金风控系统", layout="wide", page_icon="📈")

# 设置绘图风格
plt.style.use('seaborn-v0_8-whitegrid')

# 解决中文乱码 (兼容性处理)
system_name = platform.system()
if system_name == "Windows":
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
elif system_name == "Darwin":
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC']
else:
    # Linux/Cloud 环境通常需要字体支持，这里作为回退
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ==============================================================================
# 2. 🎛️ 侧边栏：参数控制中心
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")

# A. 文件上传
uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

# B. 业务参数
st.sidebar.subheader("🏭 业务场景")
quantity = st.sidebar.number_input("持仓数量 (吨)", value=30, step=10)
hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)
margin_rate = st.sidebar.number_input("保证金率 (0.12 = 12%)", value=0.12, step=0.01, format="%.2f")

# C. 资金策略
st.sidebar.subheader("💰 资金区间管理")
inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)
withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)

# D. 模拟参数
st.sidebar.subheader("⏳ 模拟设置")
holding_days = st.sidebar.slider("库存周转/持仓周期 (天)", 7, 90, 30)


# ==============================================================================
# 3. 🧠 核心计算逻辑 (缓存加速)
# ==============================================================================
@st.cache_data
def process_data(file, q, ratio, m_rate, inject_r, withdraw_r, days):
    # 读取数据
    try:
        df = pd.read_csv(file, encoding='gbk')
    except:
        df = pd.read_csv(file, encoding='utf-8-sig')

    # 清洗列名
    df.columns = [str(c).strip() for c in df.columns]
    cols = df.columns
    col_time = next((c for c in cols if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in cols if '现货' in c), None)
    col_fut = next((c for c in cols if ('期货' in c or '主力' in c) and '价格' in c), None)

    if not (col_time and col_spot and col_fut):
        return None, "无法识别列名，请确保包含：时间/Date, 现货, 期货/主力合约价格"

    df = df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
    df['Date'] = pd.to_datetime(df['Date'])
    for col in ['Spot', 'Futures']:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')
    df = df.sort_values('Date').reset_index(drop=True)

    # 基础指标
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    # 资金流模拟
    equity_list, margin_req_list = [], []
    cash_in_list, cash_out_list = [], []
    risk_degree_list = []

    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        # 盈亏
        if i > 0:
            daily_pnl = -(price - df['Futures'].iloc[i - 1]) * q * ratio
            current_equity += daily_pnl

        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)

        # 阈值
        thresh_low = req_margin * inject_r
        thresh_high = req_margin * withdraw_r

        in_amt, out_amt = 0, 0
        if current_equity < thresh_low:
            in_amt = thresh_low - current_equity
            current_equity += in_amt
        elif current_equity > thresh_high:
            out_amt = current_equity - thresh_high
            current_equity -= out_amt

        cash_in_list.append(in_amt)
        cash_out_list.append(out_amt)
        equity_list.append(current_equity)
        risk_degree_list.append((current_equity / req_margin) if req_margin > 0 else 0)

    df['Account_Equity'] = equity_list
    df['Margin_Required'] = margin_req_list
    df['Cash_Injection'] = cash_in_list
    df['Cash_Withdrawal'] = cash_out_list
    df['Risk_Degree'] = risk_degree_list
    df['Line_Inject'] = df['Margin_Required'] * inject_r
    df['Line_Withdraw'] = df['Margin_Required'] * withdraw_r

    # 净值计算
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    curr_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash

    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = curr_asset - base_asset

    return df, None


# ==============================================================================
# 4. 📊 主界面展示逻辑
# ==============================================================================
st.title("📊 企业套期保值资金风控看板")
st.markdown("---")

if uploaded_file is not None:
    df, err = process_data(uploaded_file, quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio,
                           holding_days)

    if err:
        st.error(err)
    else:
        # --- 顶部 KPI 指标 ---
        col1, col2, col3, col4 = st.columns(4)
        total_inject = df['Cash_Injection'].sum() / 10000
        total_withdraw = df['Cash_Withdrawal'].sum() / 10000
        net_flow = total_withdraw - total_inject

        col1.metric("累计补入资金", f"{total_inject:.2f} 万", delta_color="inverse")
        col2.metric("累计提取盈余", f"{total_withdraw:.2f} 万")
        col3.metric("资金净回流", f"{net_flow:.2f} 万", delta=f"{net_flow:.2f} 万")
        col4.metric("最新风险度", f"{df['Risk_Degree'].iloc[-1] * 100:.1f}%")

        # --- 图表区 ---
        tab1, tab2, tab3, tab4 = st.tabs(["📉 价格与基差", "🏦 资金通道监控", "🛡️ 对冲效果对比", "📊 风险分布"])

        # Tab 1: 价格与基差
        with tab1:
            st.subheader("期现价格走势与基差监控")
            fig1, ax1 = plt.subplots(figsize=(10, 5))
            ax1.plot(df['Date'], df['Spot'] / 10000, 'b-', label='现货 (左轴)')
            ax1.plot(df['Date'], df['Futures'] / 10000, color='orange', linestyle='--', label='期货 (左轴)')
            ax1.set_ylabel("价格 (万元)")
            ax1.grid(True, alpha=0.3)

            ax1_r = ax1.twinx()
            basis = df['Basis'] / 10000
            ax1_r.fill_between(df['Date'], basis, 0, color='gray', alpha=0.2, label='基差范围')
            ax1_r.plot(df['Date'], basis, color='gray', alpha=0.5, linewidth=1)
            ax1_r.set_ylabel("基差 (万元)")

            lines, labels = ax1.get_legend_handles_labels()
            lines2, labels2 = ax1_r.get_legend_handles_labels()
            ax1.legend(lines + lines2, labels + labels2, loc='upper left')
            st.pyplot(fig1)
            st.info("💡 灰色阴影代表基差（现货-期货）。基差走强有利于卖出套保，基差走弱则会产生成本。")

        # Tab 2: 资金通道
        with tab2:
            st.subheader(f"资金安全通道 ({inject_ratio}x ~ {withdraw_ratio}x)")
            fig3, ax3 = plt.subplots(figsize=(10, 5))

            # 数据准备
            l_inj = df['Line_Inject'] / 10000
            l_wit = df['Line_Withdraw'] / 10000
            l_eq = df['Account_Equity'] / 10000

            ax3.fill_between(df['Date'], l_inj, l_wit, color='gray', alpha=0.1, label='安全缓冲区')
            ax3.plot(df['Date'], l_eq, color='green', linewidth=2, label='账户权益')
            ax3.plot(df['Date'], l_inj, 'r--', alpha=0.5, label='补金线')
            ax3.plot(df['Date'], l_wit, 'b--', alpha=0.5, label='提金线')

            # 标记点
            inj_pts = df[df['Cash_Injection'] > 0]
            wit_pts = df[df['Cash_Withdrawal'] > 0]
            if not inj_pts.empty:
                ax3.scatter(inj_pts['Date'], inj_pts['Account_Equity'] / 10000, c='red', marker='^', s=50, zorder=5)
            if not wit_pts.empty:
                ax3.scatter(wit_pts['Date'], wit_pts['Account_Equity'] / 10000, c='blue', marker='v', s=50, zorder=5)

            ax3.set_ylabel("资金 (万元)")
            ax3.legend(loc='upper left')
            st.pyplot(fig3)
            st.success("✅ 绿色线条在灰色通道内运行最为健康。红色三角表示补钱操作，蓝色倒三角表示提钱操作。")

        # Tab 3: 对冲效果
        with tab3:
            st.subheader("账面资产价值变动对比")
            fig4, ax4 = plt.subplots(figsize=(10, 5))
            val_raw = df['Value_Change_NoHedge'] / 10000
            val_hedge = df['Value_Change_Hedged'] / 10000

            ax4.plot(df['Date'], val_raw, 'r-', alpha=0.3, label='未套保: 库存价值波动')
            ax4.plot(df['Date'], val_hedge, 'g-', linewidth=2, label='套保后: 综合资产变动')
            ax4.axhline(0, color='black', linestyle=':', alpha=0.3)
            ax4.set_ylabel("价值变动 (万元)")
            ax4.legend()
            st.pyplot(fig4)

            std_raw = val_raw.std()
            std_hedge = val_hedge.std()
            reduce = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            st.caption(f"📊 统计结论: 套保策略将资产波动率降低了 **{reduce:.1f}%**。")

        # Tab 4: 风险分布
        with tab4:
            st.subheader(f"{holding_days}天周期盈亏分布")
            fig2, ax2 = plt.subplots(figsize=(10, 5))
            sns.kdeplot(df['Cycle_PnL_NoHedge'].dropna() / 10000, fill=True, color='red', alpha=0.3, label='未套保',
                        ax=ax2)
            sns.kdeplot(df['Cycle_PnL_Hedge'].dropna() / 10000, fill=True, color='green', alpha=0.5, label='套保后',
                        ax=ax2)
            ax2.set_xlabel("盈亏金额 (万元)")
            ax2.legend()
            st.pyplot(fig2)
            st.info("💡 绿色山峰越陡峭、越窄，说明风险控制越好（盈亏波动范围小）。")

        # --- 数据下载区域 ---
        st.markdown("---")
        st.subheader("📥 报表导出")

        # 准备 Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            export_df = df.copy()
            # 格式化导出数据
            cols = ['Date', 'Spot', 'Futures', 'Basis', 'Margin_Required', 'Account_Equity', 'Cash_Injection',
                    'Cash_Withdrawal', 'Value_Change_Hedged']
            out_df = export_df[cols].copy()
            for c in cols[4:]: out_df[c] /= 10000
            out_df.columns = ['日期', '现货', '期货', '基差', '保证金(万)', '权益(万)', '补金(万)', '提金(万)',
                              '净值变动(万)']
            out_df.to_excel(writer, index=False, sheet_name='运营日报')

        st.download_button(
            label="📥 下载 Excel 分析日报",
            data=output.getvalue(),
            file_name='套保运营日报.xlsx',
            mime='application/vnd.ms-excel'
        )

else:
    st.info("👆 请在左侧侧边栏上传 CSV 文件以开始分析。")
    st.markdown("""
    **CSV 格式说明：**
    必须包含以下列（自动识别）：
    - `时间` 或 `Date`
    - `现货`
    - `期货` 或 `主力合约价格`
    """)
