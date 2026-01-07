import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io
import platform

# ==============================================================================
# 🚀 深度定制界面
# ==============================================================================
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .viewerBadge_container__1QSob {display: none;}
            #stDecoration {display:none;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==============================================================================
# 1. 🎨 页面基本设置
# ==============================================================================
st.set_page_config(page_title="套期保值稳定性回测系统", layout="wide", page_icon="🛡️")

plt.style.use('seaborn-v0_8-whitegrid')

# 解决中文乱码
system_name = platform.system()
if system_name == "Windows":
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
elif system_name == "Darwin":
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC']
else:
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ==============================================================================
# 2. 🎛️ 侧边栏：参数控制中心
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")
uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

st.sidebar.subheader("🏭 业务场景")
quantity = st.sidebar.number_input("持仓数量 (吨)", value=30, step=10)
hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)
margin_rate = st.sidebar.number_input("保证金率 (0.12 = 12%)", value=0.12, step=0.01, format="%.2f")

st.sidebar.subheader("💰 资金区间管理")
inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)
withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)

st.sidebar.subheader("⏳ 模拟设置")
holding_days = st.sidebar.slider("库存周转/持仓周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (保留原始逻辑)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    equity_list, margin_req_list = [], []
    cash_in_list, cash_out_list = [], []
    risk_degree_list = []

    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        if i > 0:
            daily_pnl = -(price - df['Futures'].iloc[i - 1]) * q * ratio
            current_equity += daily_pnl

        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)
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
    
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    curr_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = curr_asset - base_asset
    return df

# ==============================================================================
# 4. 📊 主界面展示逻辑
# ==============================================================================
st.title("🛡️ 套期保值稳定性回测系统")
st.markdown("---")

if uploaded_file is not None:
    try:
        raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except:
        raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    cols = raw_df.columns
    col_time = next((c for c in cols if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in cols if '现货' in c), None)
    col_fut = next((c for c in cols if ('期货' in c or '主力' in c) and '价格' in c), None)

    if not (col_time and col_spot and col_fut):
        st.error("列名识别失败")
    else:
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        for col in ['Spot', 'Futures']:
            raw_df[col] = pd.to_numeric(raw_df[col].astype(str).str.replace(',', ''), errors='coerce')
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)

        st.sidebar.subheader("📅 样本区间选择")
        min_date, max_date = raw_df['Date'].min().to_pydatetime(), raw_df['Date'].max().to_pydatetime()
        date_range = st.sidebar.date_input("选择时间段", value=(min_date, max_date), min_value=min_date, max_value=max_date)

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_d, end_d = date_range
            df = process_data(raw_df[(raw_df['Date'].dt.date >= start_d) & (raw_df['Date'].dt.date <= end_d)], 
                             quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # --- 顶部数值看板：聚焦稳定性 ---
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            basis_vol = (df['Basis'].std() / df['Spot'].mean()) * 100

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("现货价值波动标准差", f"{std_raw:.2f} 万")
            c2.metric("套保后综合波动标准差", f"{std_hedge:.2f} 万", delta=f"-{(std_raw-std_hedge):.2f}", delta_color="normal")
            c3.metric("稳定性提升比例", f"{stability_boost:.1f}%")
            c4.metric("资金覆盖稳定性", f"{df['Risk_Degree'].mean() * 100:.1f}%", help="账户权益/保证金的平均比值")

            # --- 图表标签页：价格基差监控放第一个 ---
            tab1, tab2, tab3, tab4 = st.tabs(["📉 价格基差监控", "🛡️ 对冲波动稳定性", "📊 风险概率分布", "🏦 资金通道监管"])

            with tab1:
                st.subheader("期现价格走势与基差动态")
                fig1, ax1 = plt.subplots(figsize=(10, 5))
                ax1.plot(df['Date'], df['Spot'] / 10000, 'b-', label='现货 (左轴)')
                ax1.plot(df['Date'], df['Futures'] / 10000, color='orange', linestyle='--', label='期货 (左轴)')
                ax1.set_ylabel("价格 (万元)")
                ax1.grid(True, alpha=0.3)
                ax1_r = ax1.twinx()
                basis = df['Basis'] / 10000
                ax1_r.fill_between(df['Date'], basis, 0, color='gray', alpha=0.2, label='基差范围')
                ax1_r.set_ylabel("基差 (万元)")
                st.pyplot(fig1)

            with tab2:
                st.subheader("对冲前后的资产净值稳定性对比")
                fig4, ax4 = plt.subplots(figsize=(10, 5))
                ax4.plot(df['Date'], df['Value_Change_NoHedge']/10000, 'r-', alpha=0.3, label='未套保风险暴露')
                ax4.plot(df['Date'], df['Value_Change_Hedged']/10000, 'g-', linewidth=2, label='套保后净值曲线')
                ax4.axhline(0, color='black', linestyle=':', alpha=0.3)
                ax4.set_ylabel("价值变动 (万元)")
                ax4.legend()
                st.pyplot(fig4)
                st.info(f"📊 **稳定性量化结论**：套保策略成功将资产风险波动从 {std_raw:.2f} 万降低至 {std_hedge:.2f} 万。")

            with tab3:
                st.subheader(f"{holding_days}天持仓周期盈亏概率分布")
                fig2, ax2 = plt.subplots(figsize=(10, 5))
                sns.kdeplot(df['Cycle_PnL_NoHedge'].dropna()/10000, fill=True, color='red', alpha=0.3, label='未套保', ax=ax2)
                sns.kdeplot(df['Cycle_PnL_Hedge'].dropna()/10000, fill=True, color='green', alpha=0.5, label='套保后', ax=ax2)
                ax2.set_xlabel("周期盈亏 (万元)")
                ax2.legend()
                st.pyplot(fig2)

            with tab4:
                st.subheader(f"资金调仓点监控 (补金线: {inject_ratio}x | 提盈线: {withdraw_ratio}x)")
                fig3, ax3 = plt.subplots(figsize=(10, 5))
                l_inj, l_wit, l_eq = df['Line_Inject']/10000, df['Line_Withdraw']/10000, df['Account_Equity']/10000
                ax3.fill_between(df['Date'], l_inj, l_wit, color='gray', alpha=0.1, label='安全缓冲区')
                ax3.plot(df['Date'], l_eq, color='black', linewidth=1, alpha=0.6, label='账户权益')
                
                # 标注补仓和出金点
                inj_ev = df[df['Cash_Injection'] > 0]
                wit_ev = df[df['Cash_Withdrawal'] > 0]
                ax3.scatter(inj_ev['Date'], inj_ev['Account_Equity']/10000, color='red', marker='^', s=60, label='补仓点', zorder=5)
                ax3.scatter(wit_ev['Date'], wit_ev['Account_Equity']/10000, color='blue', marker='v', s=60, label='出金点', zorder=5)
                
                ax3.plot(df['Date'], l_inj, 'r--', alpha=0.5, label='补金线')
                ax3.plot(df['Date'], l_wit, 'b--', alpha=0.5, label='提金线')
                ax3.set_ylabel("资金 (万元)")
                ax3.legend(loc='upper left', ncol=2)
                st.pyplot(fig3)

            # 下载逻辑
            st.markdown("---")
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                out_df = df[['Date', 'Spot', 'Futures', 'Basis', 'Margin_Required', 'Account_Equity', 'Cash_Injection', 'Cash_Withdrawal', 'Value_Change_Hedged']].copy()
                for c in out_df.columns[4:]: out_df[c] /= 10000
                out_df.columns = ['日期', '现货', '期货', '基差', '保证金(万)', '权益(万)', '补金(万)', '提金(万)', '净值变动(万)']
                out_df.to_excel(writer, index=False, sheet_name='稳定性分析数据')
            st.download_button(label="📥 下载回测明细", data=output.getvalue(), file_name='稳定性回测报告.xlsx')

else:
    st.info("👆 请上传数据文件开启稳定性回测。")



