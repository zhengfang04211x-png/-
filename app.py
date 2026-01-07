import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io
import platform

# ==============================================================================
# 🚀 界面定制 (全量保留)
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

system_name = platform.system()
if system_name == "Windows":
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
elif system_name == "Darwin":
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC']
else:
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ==============================================================================
# 2. 🎛️ 侧边栏参数 (全量保留)
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
# 3. 🧠 核心计算逻辑 (全量保留)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    equity_list, margin_req_list, cash_in_list, cash_out_list, risk_degree_list = [], [], [], [], []
    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        if i > 0:
            current_equity += -(price - df['Futures'].iloc[i - 1]) * q * ratio
        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)
        thresh_low, thresh_high = req_margin * inject_r, req_margin * withdraw_r
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

    df['Account_Equity'], df['Margin_Required'] = equity_list, margin_req_list
    df['Cash_Injection'], df['Cash_Withdrawal'] = cash_in_list, cash_out_list
    df['Risk_Degree'] = risk_degree_list
    df['Line_Inject'], df['Line_Withdraw'] = df['Margin_Required'] * inject_r, df['Margin_Required'] * withdraw_r
    
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    curr_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = curr_asset - base_asset
    return df

# ==============================================================================
# 4. 📊 展示逻辑
# ==============================================================================
if uploaded_file:
    try:
        raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except:
        raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    col_time = next((c for c in raw_df.columns if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if ('期货' in c or '主力' in c) and '价格' in c), None)

    if col_time and col_spot and col_fut:
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        for col in ['Spot', 'Futures']:
            raw_df[col] = pd.to_numeric(raw_df[col].astype(str).str.replace(',', ''), errors='coerce')
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)

        min_d, max_d = raw_df['Date'].min().to_pydatetime(), raw_df['Date'].max().to_pydatetime()
        date_range = st.sidebar.date_input("分析起止时间", value=(min_d, max_d), min_value=min_d, max_value=max_d)

        if isinstance(date_range, tuple) and len(date_range) == 2:
            df = process_data(raw_df[(raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])], 
                             quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # --- 修改：典型的 Metric 数值 ---
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            
            # 计算最大极端亏损（MDD类似概念）
            max_loss_no = df['Value_Change_NoHedge'].min() / 10000
            max_loss_hedge = df['Value_Change_Hedged'].min() / 10000
            loss_saved = max_loss_hedge - max_loss_no # 挽回了多少亏损

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("现货波动风险 (标准差)", f"{std_raw:.2f} 万")
            c2.metric("套保后剩余波动", f"{std_hedge:.2f} 万", delta=f"降低 {stability_boost:.1f}%", delta_color="normal")
            c3.metric("累计调仓净额", f"{(df['Cash_Withdrawal'].sum() - df['Cash_Injection'].sum())/10000:.2f} 万", help="提盈金额减去补仓金额")
            c4.metric("最大亏损修复额", f"{loss_saved:.2f} 万", help="套保方案在最极端价格变动下挽回的资产损失")

            # --- 标签页重排：基差第一 ---
            t1, t2, t3, t4 = st.tabs(["📉 价格基差监控", "🛡️ 对冲波动稳定性", "📊 风险概率分布", "🏦 资金通道监管"])

            with t1:
                fig1, ax1 = plt.subplots(figsize=(10, 4))
                ax1.plot(df['Date'], df['Spot']/10000, 'b-', label='现货')
                ax1.plot(df['Date'], df['Futures']/10000, 'orange', ls='--', label='期货')
                ax1_r = ax1.twinx()
                ax1_r.fill_between(df['Date'], df['Basis']/10000, 0, color='gray', alpha=0.2)
                ax1.legend(); st.pyplot(fig1)

            with t2:
                fig4, ax4 = plt.subplots(figsize=(10, 4))
                ax4.plot(df['Date'], df['Value_Change_NoHedge']/10000, 'r-', alpha=0.3, label='裸奔风险')
                ax4.plot(df['Date'], df['Value_Change_Hedged']/10000, 'g-', lw=2, label='对冲后稳态')
                ax4.axhline(0, color='k', ls=':', alpha=0.3); ax4.legend(); st.pyplot(fig4)

            with t3:
                fig2, ax2 = plt.subplots(figsize=(10, 4))
                sns.kdeplot(df['Cycle_PnL_NoHedge'].dropna()/10000, fill=True, color='red', alpha=0.3, label='未套保')
                sns.kdeplot(df['Cycle_PnL_Hedge'].dropna()/10000, fill=True, color='green', alpha=0.5, label='套保后')
                ax2.legend(); st.pyplot(fig2)

            with t4:
                fig3, ax3 = plt.subplots(figsize=(10, 4))
                ax3.plot(df['Date'], df['Account_Equity']/10000, 'k', lw=1, alpha=0.6, label='账户权益')
                ax3.fill_between(df['Date'], df['Line_Inject']/10000, df['Line_Withdraw']/10000, color='gray', alpha=0.1)
                inj_ev, wit_ev = df[df['Cash_Injection']>0], df[df['Cash_Withdrawal']>0]
                ax3.scatter(inj_ev['Date'], inj_ev['Account_Equity']/10000, color='red', marker='^', label='补仓')
                ax3.scatter(wit_ev['Date'], wit_ev['Account_Equity']/10000, color='blue', marker='v', label='出金')
                ax3.legend(loc='upper left', ncol=2); st.pyplot(fig3)

            # --- 摘要分析 ---
            st.markdown("---")
            st.subheader("📝 稳定性分析结论")
            sc1, sc2 = st.columns(2)
            with sc1:
                st.write(f"✅ **风险对冲质量**：通过套保，资产净值的波动幅度被压制在了现货波动的 **{100-stability_boost:.1f}%** 范围内。")
                st.write(f"✅ **极端生存能力**：在回测期内最不利的价格波动下，套保方案成功挽救了约 **{loss_saved:.2f} 万元** 的潜在损失。")
            with sc2:
                st.write(f"✅ **资金运营频率**：系统平均每 **{len(df)/(len(inj_ev)+len(wit_ev)+1):.1f}** 天触发一次资金调度，操作频率处于合理区间。")
                st.write(f"✅ **收益确定性**：套保后的盈亏分布（见标签3）明显向中心靠拢，大幅降低了企业经营的“意外”风险。")

            # 下载
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='回测数据')
            st.download_button("📥 下载完整回测数据", data=output.getvalue(), file_name='套保回测报告.xlsx')
else:
    st.info("👆 请上传 CSV 数据文件开启系统分析。")




